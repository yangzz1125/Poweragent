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


def test_factorial_repeats_cover_all_cells():
    conditions = read_json(BENCHMARK_DIR / 'config' / 'experiments.json')['conditions']
    tasks = ordered_tasks([{'scenario_id': 'V0001'}], conditions, 2)
    assert len({(entry['scenario_id'], condition['id'], repeat) for entry, condition, repeat in tasks}) == 16


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
    with pytest.raises(ValueError, match='metadata mismatch'):
        run_matrix(options(tmp_path, temperature=0.4), lambda _: MockClient())


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
