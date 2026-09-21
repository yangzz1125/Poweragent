from __future__ import annotations

import json

from poweragentbench.voltage_case import (
    DEFAULT_SCENARIO_ROOT,
    load_scenario_metadata,
    scenario_ids,
)
from poweragentbench.voltage_evaluator import evaluate_voltage_dispatch


def test_frozen_corpus_has_both_voltage_directions() -> None:
    conditions = {
        load_scenario_metadata(scenario_id)["initial_state"]["condition"]
        for scenario_id in scenario_ids()
    }
    assert conditions == {"UNDERVOLTAGE", "OVERVOLTAGE"}


def test_no_action_fails_every_frozen_case() -> None:
    for scenario_id in scenario_ids():
        report = evaluate_voltage_dispatch(scenario_id, [])
        assert report["converged"] == 1.0
        assert report["success"] == 0.0
        assert report["final_violation_count"] > 0


def test_private_witnesses_replay_successfully() -> None:
    witnesses = json.loads(
        (DEFAULT_SCENARIO_ROOT / "private" / "witnesses.json").read_text(
            encoding="utf-8"
        )
    )
    assert {row["scenario_id"] for row in witnesses} == set(scenario_ids())
    for witness in witnesses:
        report = evaluate_voltage_dispatch(witness["scenario_id"], witness["dispatch"])
        assert report["success"] == 1.0
        assert report["final_violation_count"] == 0.0
        assert report["new_thermal_violation"] == 0.0


def test_invalid_bess_action_is_rejected_before_power_flow() -> None:
    report = evaluate_voltage_dispatch("V0001", [{"bess_id": "BESS_1", "p_mw": 99.0}])
    assert report["valid_action"] == 0.0
    assert report["success"] == 0.0
    assert "outside" in report["error"]


def test_positive_benchmark_dispatch_improves_undervoltage() -> None:
    base = evaluate_voltage_dispatch("V0001", [])
    injected = evaluate_voltage_dispatch("V0001", [{"bess_id": "BESS_2", "p_mw": 0.25}])
    assert injected["final_min_vm_pu"] > base["final_min_vm_pu"]
