import csv

import pytest

from scripts.audit_voltage_difficulty import audit
from poweragentbench.voltage_case import read_json
from poweragentbench.voltage_evaluator import evaluate_voltage_dispatch


@pytest.mark.parametrize("profile", ["exploratory", "stratified"])
def test_dev_study_keeps_every_candidate_and_replays_witness(tmp_path, profile):
    root = tmp_path / "study"
    summary = audit(root, seed=2027, count=4, profile=profile)
    rows = list(csv.DictReader((root / "candidates.csv").open(encoding="utf-8")))
    assert len(rows) == summary["candidate_count"] == 4
    assert len(read_json(root / "manifest.json")["scenarios"]) == 4
    for row in rows:
        if row["status"] == "evaluated":
            assert int(row["uniform_pf_calls"]) == 12
            assert int(row["search_pf_calls"]) > 0
            if row["condition"] in ("UNDERVOLTAGE", "OVERVOLTAGE"):
                assert int(row["one_shot_pf_calls"]) == 1
        if row["search_success"] == "1":
            dispatch = read_json(root / "evaluator_private" / f"{row['scenario_id']}_witness.json")
            assert evaluate_voltage_dispatch(row["scenario_id"], dispatch, scenario_root=root)["success"] == 1.0
            assert float(row["witness_margin_pu"]) >= 0
    with pytest.raises(ValueError, match="empty output"):
        audit(root, count=4)
