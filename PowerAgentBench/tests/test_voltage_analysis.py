import csv

import pytest

from scripts.analyze_voltage_experiments import analyze


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
    report = analyze(path, tmp_path / 'figures', bootstrap=60)
    assert report['complete'] == report['expected'] == 96
    assert (tmp_path / 'figures' / 'figure3_success.png').is_file()
    with path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0]); writer.writeheader(); writer.writerows(rows[:-1])
    with pytest.raises(ValueError, match='incomplete matrix'):
        analyze(path, tmp_path / 'incomplete', bootstrap=10)
