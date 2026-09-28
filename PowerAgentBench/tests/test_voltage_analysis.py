import csv
import json

import pytest

from scripts.analyze_voltage_experiments import analyze, absolute_factorial_effects
import pandas as pd


def test_absolute_interactions_use_scenario_pairs():
    rows = [dict(scenario_id=f'D{case}', condition=f'I{i}-V{v}-R{r}', success=i*v)
            for case in range(4) for i in range(2) for v in range(2) for r in range(2)]
    effects = absolute_factorial_effects(pd.DataFrame(rows), samples=50).set_index('term')
    assert effects.loc['I', 'absolute_rate_contrast'] == .5
    assert effects.loc['IV', 'absolute_rate_contrast'] == 1
    assert effects.loc['IVR', 'absolute_rate_contrast'] == 0
    assert effects.loc['IV', 'n_paired_scenarios'] == 4
    partial = absolute_factorial_effects(pd.DataFrame(rows[:-1]), samples=50)
    assert (partial.n_paired_scenarios == 3).all()
    assert (partial.excluded_unpaired_scenarios == 1).all()


def test_analysis_counts_scenarios_and_refuses_incomplete(tmp_path):
    path = tmp_path / 'episodes.csv'
    rows = []
    for case in range(6):
        for repeat in range(2):
            for i in range(2):
                for v in range(2):
                    for r in range(2):
                        rows.append(dict(run_id='mock', scenario_id=f'D{case:04d}', difficulty=['easy','medium','hard'][case//2],
                                         condition=f'I{i}-V{v}-R{r}', domain_interface=i, verification=v, recovery=r,
                                         repetition_index=repeat, status='complete', success=int((case + repeat + i + v + r) % 3 != 0),
                                         first_pass_success=int(case % 2 == 0), first_submit_failed=int(case % 2 == 1),
                                         recovered=int(case % 2 == 1 and r == 1), valid_action=1, n_actual_power_flows=1+v+r,
                                         total_tokens=100, latency_seconds=1.0, dataset_sha256='test'))
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0])
        writer.writeheader(); writer.writerows(rows)
    (tmp_path / 'run.json').write_text(json.dumps({'run_id': 'mock', 'planned_tasks': [[r['condition'], r['scenario_id'], r['repetition_index']] for r in rows]}), encoding='utf-8')
    report = analyze(path, tmp_path / 'figures', bootstrap=60)
    assert report['complete'] == report['expected'] == 96
    assert (tmp_path / 'figures' / 'figure3_success.png').is_file()
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0]); writer.writeheader(); writer.writerows([row for row in rows if row['scenario_id'] != 'D0005'])
    with pytest.raises(ValueError, match='incomplete matrix'):
        analyze(path, tmp_path / 'incomplete', bootstrap=10)
