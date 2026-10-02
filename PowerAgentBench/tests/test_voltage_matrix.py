import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.run_voltage_experiment_matrix import run_matrix, ordered_tasks
from poweragentbench.voltage_case import read_json, BENCHMARK_DIR
from poweragentbench.voltage_case import DEFAULT_SCENARIO_ROOT


def options(tmp_path, **changes):
    args = dict(provider='openai', model='mock', api_mode='chat', split='dev', scenario_root=DEFAULT_SCENARIO_ROOT,
                output_dir=tmp_path / 'results', prompt_template=Path('benchmarks/steady/voltage_control/prompts/voltage_agent_prompt.json'),
                freeze_manifest=None, repeats=1, max_turns=1, max_episodes=2, max_total_tokens=None,
                max_cost_usd=None, input_usd_per_million=0.0, output_usd_per_million=0.0,
                temperature=0.0, timeout=30.0, url=None, api_key=None, continue_on_error=False,
                retry_errors=False, dry_run=False)
    args.update(changes)
    return SimpleNamespace(**args)


class MockClient:
    retry_count_last_call = 0

    def __call__(self, messages):
        self.last_debug = {'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}
        return json.dumps({'tool': 'submit', 'args': {'dispatch': []}})


def test_dev_diagnostic_subset_is_explicit_and_invalid_ids_rejected(tmp_path):
    args = options(tmp_path, scenario_ids=['V0001'], condition_ids=['I1-V0-R1'], dry_run=True)
    assert run_matrix(args)['tasks'] == 1
    args.scenario_ids=['NO_SUCH_CASE']
    with pytest.raises(ValueError, match='unknown diagnostic scenario'):
        run_matrix(args)
    args.scenario_ids=['V0001']; args.condition_ids=['I2-V0-R1']
    with pytest.raises(ValueError, match='unknown diagnostic condition'):
        run_matrix(args)


def test_factorial_repeats_cover_all_cells():
    conditions = read_json(BENCHMARK_DIR / 'config' / 'experiments.json')['conditions']
    tasks = ordered_tasks([{'scenario_id': 'V0001'}], conditions, 2)
    assert len({(entry['scenario_id'], condition['id'], repeat) for entry, condition, repeat in tasks}) == 16
    assert tasks == ordered_tasks([{'scenario_id': 'V0001'}], conditions, 2)
    assert [c['id'] for _, c, _ in tasks[:8]] != [c['id'] for c in conditions]


def test_matrix_resume_and_metadata(tmp_path):
    args = options(tmp_path)
    assert run_matrix(options(tmp_path, dry_run=True), lambda _: None)['tasks'] == 64
    first = run_matrix(args, lambda _: MockClient())
    assert first['complete'] == 2 and first['remaining'] == 62
    second = run_matrix(args, lambda _: MockClient())
    assert second['complete'] == 4 and second['remaining'] == 60
    with (args.output_dir / 'episodes.csv').open(newline='', encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == len({(r['condition'], r['scenario_id'], r['repetition_index']) for r in rows}) == 4
    assert all(r['total_tokens'] == '15' for r in rows)
    required = {'run_id', 'scenario_id', 'difficulty', 'voltage_condition', 'condition',
                'success', 'valid_action', 'first_pass_success', 'recovered',
                'n_llm_turns', 'n_preview_calls', 'n_submit_calls', 'n_evaluator_calls',
                'n_actual_power_flows', 'input_tokens', 'output_tokens', 'total_tokens',
                'latency_seconds', 'dataset_sha256', 'prompt_sha256', 'code_commit', 'status'}
    assert required <= set(rows[0])
    assert all(r['dataset_sha256'] and r['benchmark_config_sha256'] for r in rows)
    assert 'api_key' not in (args.output_dir / 'run.json').read_text(encoding='utf-8')
    identity = read_json(args.output_dir / 'run.json')
    assert len(identity['planned_tasks']) == 64
    assert len(identity['source_sha256']) == 64
    assert identity['max_output_tokens'] == 16384
    with pytest.raises(ValueError, match='metadata mismatch'):
        run_matrix(options(tmp_path, max_output_tokens=8192), lambda _: MockClient())
    with pytest.raises(ValueError, match='metadata mismatch'):
        run_matrix(options(tmp_path, temperature=0.4), lambda _: MockClient())


def test_source_change_refuses_resume(tmp_path, monkeypatch):
    import scripts.run_voltage_experiment_matrix as runner
    args = options(tmp_path, max_episodes=1)
    run_matrix(args, lambda _: MockClient())
    monkeypatch.setattr(runner, 'source_identity', lambda: 'changed-source')
    with pytest.raises(ValueError, match='metadata mismatch'):
        run_matrix(args, lambda _: MockClient())


def test_mock_matrix_eight_conditions_two_repeats(tmp_path):
    args = options(tmp_path, repeats=2, max_episodes=72)
    report = run_matrix(args, lambda _: MockClient())
    assert report['complete'] == 72
    with (args.output_dir / 'episodes.csv').open(newline='', encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    first_case = rows[0]['scenario_id']
    assert {(row['condition'], row['repetition_index']) for row in rows if row['scenario_id'] == first_case} == {
        (f'I{i}-V{v}-R{r}', str(repeat)) for i in range(2) for v in range(2) for r in range(2) for repeat in range(2)
    }
    assert sum(int(row['n_actual_power_flows']) for row in rows) == sum(int(row['n_evaluator_calls']) for row in rows)


def test_matrix_errors_and_explicit_retry(tmp_path):
    args = options(tmp_path, max_episodes=1, continue_on_error=True)
    def fail(_):
        def response(_messages):
            raise OSError('connection failure')
        return response
    assert run_matrix(args, fail)['errors'] == 1
    unchanged = run_matrix(args, lambda _: MockClient())
    assert unchanged['errors'] == 1  # errors not silently retried
    recovered = run_matrix(options(tmp_path, max_episodes=1, retry_errors=True), lambda _: MockClient())
    assert recovered['complete'] == unchanged['complete'] + 1
    assert (args.output_dir / 'retries.jsonl').exists()


def test_v3_preregistration_is_part_of_analysis_protocol_identity(tmp_path, monkeypatch):
    from scripts import run_voltage_experiment_matrix as matrix
    v3 = [path.name for path in matrix.protocol_documents("structure-v3")]
    assert "V3_PILOT_PREREGISTRATION.md" in v3 and all(path.exists() for path in matrix.protocol_documents("structure-v3"))
    assert "V3_PILOT_PREREGISTRATION.md" not in [path.name for path in matrix.protocol_documents("structure-v2")]
    assert [path.name for path in matrix.protocol_documents(None)] == v3[:3]
    docs = tmp_path / "docs"
    docs.mkdir()
    monkeypatch.setattr(matrix, "REPO_ROOT", tmp_path)
    for name in v3:
        (docs / name).write_text(name)
    digest = lambda: matrix.digest({path.name: matrix.sha256_file(path) for path in matrix.protocol_documents("structure-v3")})
    before = digest()
    (docs / "V3_PILOT_PREREGISTRATION.md").write_text("edited")
    assert digest() != before


TEST_ROOT = Path(__file__).resolve().parents[2] / '.local-data' / 'voltage_structure_v3_test' / 'test'
REDUCED = ['I0-V0-R0', 'I0-V0-R1', 'I0-V1-R0', 'I0-V1-R1']


@pytest.mark.skipif(not TEST_ROOT.exists(), reason='private v3 Test corpus is not on this machine')
def test_test_split_accepts_only_registered_reduced_matrix(tmp_path):
    args = options(tmp_path, split='test', scenario_root=TEST_ROOT, condition_ids=REDUCED, repeats=3, dry_run=True, max_episodes=None)
    assert run_matrix(args)['tasks'] == 96 * 4 * 3
    for changes in ({'condition_ids': ['I1-V0-R0'] + REDUCED[1:]}, {'condition_ids': REDUCED[:3]},
                    {'repeats': 1}, {'scenario_ids': ['T0001']}):
        bad = options(tmp_path, split='test', scenario_root=TEST_ROOT, condition_ids=REDUCED, repeats=3, dry_run=True, max_episodes=None)
        for key, value in changes.items():
            setattr(bad, key, value)
        with pytest.raises(ValueError, match='registered reduced matrix|only on Dev'):
            run_matrix(bad)


def test_main_preregistration_is_pinned_only_for_v3_test():
    import scripts.run_voltage_experiment_matrix as matrix
    names = lambda split: [path.name for path in matrix.protocol_documents('structure-v3', split)]
    assert 'V3_MAIN_PREREGISTRATION.md' in names('test') and 'V3_TEST_GENERATION_PROTOCOL.md' in names('test')
    assert 'V3_MAIN_PREREGISTRATION.md' not in names('dev') and 'V3_MAIN_PREREGISTRATION.md' not in names(None)
    assert all(path.exists() for path in matrix.protocol_documents('structure-v3', 'test'))
