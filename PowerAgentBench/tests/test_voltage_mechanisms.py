import json

import numpy as np
import pandas as pd
import pytest

from scripts.analyze_voltage_mechanisms import CONDITIONS, analyze, episode_metrics


def dispatch(*powers):
    return {"dispatch": [{"bess_id": f"BESS_{i + 1}", "p_mw": p} for i, p in enumerate(powers)]}


def preview(turn, powers, *, magnitude, success=False, over=False, under=False, valid=True):
    feedback = {"success": success, "valid_action": valid, "voltage_violation_magnitude": magnitude,
                "remaining_overvoltage_buses": {"7": 1.06} if over else {},
                "remaining_undervoltage_buses": {"9": 0.93} if under else {}}
    return {"event": "tool_finished", "tool": "preview_bess_dispatch", "args": dispatch(*powers), "turn": turn,
            "observation": {"preview": feedback}, "outcome": "ok" if success else "voltage_unresolved"}


def submit(turn, powers, *, magnitude, success=False, over=False, under=False):
    feedback = preview(turn, powers, magnitude=magnitude, success=success, over=over, under=under)["observation"]["preview"]
    return {"event": "tool_finished", "tool": "submit", "args": dispatch(*powers), "turn": turn,
            "observation": {"accepted": success, "verification": feedback}, "outcome": "ok" if success else "voltage_unresolved"}


def test_overcorrection_only_counts_the_opposite_side():
    under = episode_metrics([preview(1, [1.0], magnitude=.04, over=True)], "UNDERVOLTAGE")
    assert under["first_proposal_overcorrection"] == 1 and under["any_overcorrection"] == 1
    # Residual undervoltage after an undervoltage start is an unresolved violation, not overcorrection.
    still = episode_metrics([preview(1, [1.0], magnitude=.04, under=True)], "UNDERVOLTAGE")
    assert still["first_proposal_overcorrection"] == 0
    over = episode_metrics([preview(1, [1.0], magnitude=.04, under=True)], "OVERVOLTAGE")
    assert over["first_proposal_overcorrection"] == 1


def test_submit_same_as_verified_candidate_and_null_without_preview():
    verified = episode_metrics([preview(1, [1.0, 0.0], magnitude=0, success=True), submit(2, [1.0], magnitude=0, success=True)], "UNDERVOLTAGE")
    assert verified["submitted_same_as_verified_candidate"] == 1  # zero-power entries are ignored
    failed_preview = episode_metrics([preview(1, [1.0], magnitude=.05), submit(2, [1.0], magnitude=.05)], "UNDERVOLTAGE")
    assert failed_preview["submitted_same_as_verified_candidate"] is None
    different = episode_metrics([preview(1, [1.0], magnitude=0, success=True), submit(2, [2.0], magnitude=.1)], "UNDERVOLTAGE")
    assert different["submitted_same_as_verified_candidate"] == 0
    direct = episode_metrics([submit(1, [1.0], magnitude=0, success=True)], "UNDERVOLTAGE")
    assert direct["submitted_same_as_verified_candidate"] is None and direct["first_proposal_source"] == "submit"


def test_no_proposal_leaves_candidate_fields_empty():
    row = episode_metrics([{"event": "parse_error", "turn": 1}, {"event": "output_truncated", "turn": 2}], "UNDERVOLTAGE")
    assert row["no_proposal"] == 1 and row["n_proposals"] == 0 and row["parse_errors"] == 1 and row["output_truncated"] == 1
    for field in ("first_proposal_source", "first_proposal_valid", "first_proposal_success", "first_proposal_overcorrection",
                  "first_candidate_violation_magnitude", "any_overcorrection", "best_preview_violation_magnitude"):
        assert row[field] is None
    assert row["first_submit_success"] == 0 and row["repeated_candidate_count"] == 0


def test_repeats_and_nonimproving_transitions():
    events = [preview(1, [1.0], magnitude=.05), preview(2, [1.0], magnitude=.05),  # repeat, no improvement
              preview(3, [2.0], magnitude=.06),  # worse
              preview(4, [1.5], magnitude=.02),  # improves
              preview(5, [1.0], magnitude=.05)]  # repeats turn 1 and is worse than turn 4
    row = episode_metrics(events, "UNDERVOLTAGE")
    assert row["repeated_candidate_count"] == 2
    # 1->2 (equal), 2->3 (worse) and 4->5 (worse) are nonimproving; only 3->4 improves.
    assert row["nonimproving_candidate_transitions"] == 3
    assert row["best_preview_violation_magnitude"] == .02


def test_same_turn_order_is_stable_in_analyze(tmp_path):
    run = make_run(tmp_path, [("I0-V0-R0", "D1", 1)], {("I0-V0-R0", "D1"): [
        submit(3, [1.0], magnitude=.1), preview(3, [2.0], magnitude=.2)]}, structure={"D1": "S1"})
    analyze(run, tmp_path / "out", manifest=tmp_path / "manifest.json")
    row = pd.read_csv(tmp_path / "out" / "mechanism_episodes.csv").iloc[0]
    assert row.first_proposal_source == "submit"


def make_run(root, outcomes, trajectories=None, *, structure=None, conditions_planned=None, difficulty="unstratified", extra_planned=()):
    """outcomes: [(condition, scenario_id, success)], one repetition each."""
    run = root / "run"
    run.mkdir(exist_ok=True)
    planned = [[c, s, 0] for c, s, _ in outcomes] + [list(t) for t in extra_planned]
    (run / "run.json").write_text(json.dumps({"run_id": "r", "planned_tasks": planned}))
    rows = [dict(run_id="r", condition=c, scenario_id=s, repetition_index=0, episode_attempt=1, status="complete", success=ok,
                 termination_reason="success" if ok else "budget", voltage_condition="UNDERVOLTAGE", difficulty=difficulty,
                 n_actual_power_flows=2, total_tokens=100, accounted_cost_cny=.01) for c, s, ok in outcomes]
    pd.DataFrame(rows).to_csv(run / "episodes.csv", index=False)
    events = []
    for c, s, _ in outcomes:
        for e in (trajectories or {}).get((c, s), []):
            events.append({**e, "event_id": str(len(events)), "run_id": "r", "episode_attempt": 1, "turn": e.get("turn", 0),
                           "episode_key": json.dumps([c, s, 0], separators=(",", ":"))})
    (run / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    if structure is not None:
        (root / "manifest.json").write_text(json.dumps({"scenarios": [{"scenario_id": k, "structure_class": v} for k, v in structure.items()]}))
    return run


def test_contrasts_match_hand_computation(tmp_path):
    # Stratum S1: scenarios A,B. Stratum S2: scenarios C,D. success[condition] per scenario, hand-picked.
    table = {
        "A": dict(zip(CONDITIONS, [0, 1, 1, 1, 0, 0, 1, 1])),
        "B": dict(zip(CONDITIONS, [0, 0, 1, 1, 1, 0, 1, 1])),
        "C": dict(zip(CONDITIONS, [0, 1, 0, 1, 0, 1, 0, 1])),
        "D": dict(zip(CONDITIONS, [1, 1, 0, 0, 1, 1, 0, 1])),
    }
    structure = {"A": "S1", "B": "S1", "C": "S2", "D": "S2"}
    run = make_run(tmp_path, [(c, s, table[s][c]) for s in table for c in CONDITIONS], structure=structure)
    analyze(run, tmp_path / "out", manifest=tmp_path / "manifest.json", bootstrap=50)
    contrasts = pd.read_csv(tmp_path / "out" / "structure_contrasts.csv")
    got = contrasts[contrasts.metric == "success"].set_index(["contrast", "stratum"]).estimate

    def sr(scenarios, i=None, v=None, r=None):
        vals = [table[s][f"I{ii}-V{vv}-R{rr}"] for s in scenarios for ii in range(2) for vv in range(2) for rr in range(2)
                if i in (None, ii) and v in (None, vv) and r in (None, rr)]
        return float(np.mean(vals))

    def expected(scenarios):
        return {"dV": sr(scenarios, v=1) - sr(scenarios, v=0),
                "dR_V0": sr(scenarios, v=0, r=1) - sr(scenarios, v=0, r=0),
                "VR": (sr(scenarios, v=1, r=1) - sr(scenarios, v=1, r=0)) - (sr(scenarios, v=0, r=1) - sr(scenarios, v=0, r=0)),
                "dI_exploratory": sr(scenarios, i=1) - sr(scenarios, i=0)}

    s1, s2 = expected("AB"), expected("CD")
    for name in s1:
        assert got[(name, "S1")] == pytest.approx(s1[name])
        assert got[(name, "S2")] == pytest.approx(s2[name])
        assert got[(name, "MACRO")] == pytest.approx((s1[name] + s2[name]) / 2)
    assert contrasts[contrasts.stratum == "S1"].n_paired_scenarios.eq(2).all()
    assert set(contrasts[contrasts.metric == "success"].contrast) == {"dV", "dR_V0", "VR", "dI_exploratory"}
    assert set(contrasts.metric) == {"success", "first_submit_success", "first_proposal_success"}


def test_single_stratum_has_no_macro_or_duplicate_all_rows(tmp_path):
    run = make_run(tmp_path, [(c, s, 1) for s in ("A", "B") for c in CONDITIONS])
    analyze(run, tmp_path / "out", bootstrap=20)
    summary = pd.read_csv(tmp_path / "out" / "mechanism_summary.csv")
    assert set(summary.stratum) == {"unstratified"}
    assert not summary.duplicated(["stratum", "condition", "metric"]).any()
    contrasts = pd.read_csv(tmp_path / "out" / "structure_contrasts.csv")
    assert "MACRO" not in set(contrasts.stratum) and contrasts.no_variation.all()


def test_nan_difficulty_falls_back_to_all(tmp_path):
    run = make_run(tmp_path, [("I0-V0-R0", "A", 1)], difficulty=None)
    analyze(run, tmp_path / "out", bootstrap=5)
    assert pd.read_csv(tmp_path / "out" / "mechanism_episodes.csv").stratum.iloc[0] == "ALL"


def test_incomplete_run_requires_flag_and_is_marked_exploratory(tmp_path):
    run = make_run(tmp_path, [("I0-V0-R0", "A", 1)], extra_planned=[("I1-V0-R0", "A", 0)])
    with pytest.raises(ValueError, match="incomplete"):
        analyze(run, tmp_path / "out")
    report = analyze(run, tmp_path / "out", allow_incomplete=True, bootstrap=5)
    assert report["exploratory"] is True and report["planned"] == 2 and report["complete"] == 1
    (tmp_path / "x").mkdir()
    complete = analyze(make_run(tmp_path / "x", [("I0-V0-R0", "A", 1)]), tmp_path / "out2", bootstrap=5)
    assert complete["exploratory"] is False


def test_missing_scenario_in_manifest_raises(tmp_path):
    run = make_run(tmp_path, [("I0-V0-R0", "A", 1), ("I0-V0-R0", "B", 1)], structure={"A": "S1"})
    with pytest.raises(ValueError, match="missing from manifest"):
        analyze(run, tmp_path / "out", manifest=tmp_path / "manifest.json")
