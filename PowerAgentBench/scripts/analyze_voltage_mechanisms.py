"""Mechanism metrics and structure-stratified I/V/R contrasts from recorded events.

Offline only: every quantity is derived from the physical feedback already logged in
events.jsonl, so no API, evaluator or power flow is called. Structure labels come from
the evaluator-side manifest and are never part of what the evaluated model saw.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from poweragentbench.voltage_costs import read_events
from scripts.analyze_voltage_trajectories import dispatch_key, export_csv, fraction_ci

CONDITIONS = [f"I{i}-V{v}-R{r}" for i in range(2) for v in range(2) for r in range(2)]
PROPOSAL_TOOLS = {"preview_bess_dispatch": "preview", "submit": "verification"}
BINARY_METRICS = ["success", "first_submit_success", "first_proposal_valid", "first_proposal_success",
                  "first_proposal_overcorrection", "any_overcorrection", "no_proposal",
                  "submitted_same_as_verified_candidate"]
CONTINUOUS_METRICS = ["first_candidate_violation_magnitude", "best_preview_violation_magnitude",
                      "repeated_candidate_count", "nonimproving_candidate_transitions", "n_proposals",
                      "parse_errors", "output_truncated", "n_actual_power_flows", "total_tokens", "accounted_cost_cny"]
# Plan section 12.2: equal weights over the factors not being contrasted.
CONTRASTS = {
    "dV": {c: (1 if c[4] == "1" else -1) / 4 for c in CONDITIONS},
    "dR_V0": {c: ((1 if c[7] == "1" else -1) / 2 if c[4] == "0" else 0) for c in CONDITIONS},
    "VR": {c: (1 if c[4] == c[7] else -1) / 2 for c in CONDITIONS},
    "dI_exploratory": {c: (1 if c[1] == "1" else -1) / 4 for c in CONDITIONS},
}
CONTRAST_METRICS = ["success", "first_submit_success", "first_proposal_success"]


def opposite_side(initial: str, feedback: dict) -> bool:
    side = {"UNDERVOLTAGE": "remaining_overvoltage_buses", "OVERVOLTAGE": "remaining_undervoltage_buses"}.get(initial)
    return bool(side and feedback.get(side))


def episode_metrics(events: list[dict], initial: str) -> dict:
    """Pure per-episode derivation; `events` are this attempt's events in turn order."""
    proposals = []
    for event in events:
        tool = str(event.get("tool", "")).strip().lower()
        if event["event"] != "tool_finished" or tool not in PROPOSAL_TOOLS:
            continue
        feedback = (event.get("observation") or {}).get(PROPOSAL_TOOLS[tool]) or {}
        proposals.append({"source": tool, "key": dispatch_key(event.get("args") or {}),
                          "valid": feedback.get("valid_action") is True, "success": feedback.get("success") is True,
                          "magnitude": feedback.get("voltage_violation_magnitude"),
                          "opposite": opposite_side(initial, feedback)})
    first = proposals[0] if proposals else None
    submits = [p for p in proposals if p["source"] == "submit"]
    previews = [p for p in proposals if p["source"] == "preview_bess_dispatch"]
    verified = set()
    same_as_verified = None
    for p in proposals:
        if p["source"] == "submit":
            same_as_verified = int(p["key"] in verified) if verified else None
            break
        if p["success"] and p["key"] is not None:
            verified.add(p["key"])
    seen, repeated = set(), 0
    for p in proposals:
        repeated += int(p["key"] is not None and p["key"] in seen)
        seen.add(p["key"])
    nonimproving = sum(1 for a, b in zip(proposals, proposals[1:])
                       if not a["success"] and a["magnitude"] is not None and b["magnitude"] is not None and b["magnitude"] >= a["magnitude"])
    magnitudes = [p["magnitude"] for p in previews if p["magnitude"] is not None]
    return {
        "n_proposals": len(proposals), "no_proposal": int(first is None),
        "first_proposal_source": first["source"] if first else None,
        "first_proposal_valid": int(first["valid"]) if first else None,
        "first_proposal_success": int(first["success"]) if first else None,
        "first_proposal_overcorrection": int(first["opposite"]) if first else None,
        "first_candidate_violation_magnitude": first["magnitude"] if first else None,
        "any_overcorrection": int(any(p["opposite"] for p in proposals)) if proposals else None,
        # Intention-to-treat like first_pass_success in episodes.csv: no submission counts as not successful.
        "first_submit_success": int(bool(submits and submits[0]["success"])),
        "best_preview_violation_magnitude": min(magnitudes) if magnitudes else None,
        "submitted_same_as_verified_candidate": same_as_verified,
        "repeated_candidate_count": repeated, "nonimproving_candidate_transitions": nonimproving,
        "parse_errors": sum(e["event"] == "parse_error" for e in events),
        "output_truncated": sum(e["event"] == "output_truncated" for e in events),
    }


def stratum_label(extra: dict, episode) -> str:
    """Manifest structure class (v3), else the runtime difficulty; NaN/empty fall back to ALL."""
    for value in (extra.get("structure_class"), episode.get("difficulty")):
        if isinstance(value, str) and value:
            return value
    return "ALL"


def load_strata(manifest: Path | None) -> dict[str, dict]:
    if manifest is None:
        return {}
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    return {row["scenario_id"]: {key: row.get(key) for key in ("structure_class", "all_full_feasible", "severity", "recipe_id")}
            for row in payload["scenarios"]}


def paired_contrasts(frame: pd.DataFrame, metric: str, samples: int, rng: np.random.Generator) -> list[dict]:
    """Scenario-paired contrasts per stratum plus an equal-weight macro over strata."""
    cells = frame.groupby(["stratum", "scenario_id", "condition"])[metric].mean().unstack().reindex(columns=CONDITIONS)
    complete = cells.dropna()
    records, per_stratum = [], {}
    for name, weights in CONTRASTS.items():
        vector = np.array([weights[c] for c in CONDITIONS])
        values = {s: part.to_numpy() @ vector for s, part in complete.groupby(level="stratum")}
        for stratum, v in values.items():
            per_stratum[(name, stratum)] = v
            low = high = None
            if len(v) >= 2:
                draws = v[rng.integers(len(v), size=(samples, len(v)))].mean(axis=1)
                low, high = map(float, np.quantile(draws, [.025, .975]))
            records.append({"metric": metric, "contrast": name, "stratum": stratum, "estimate": float(v.mean()),
                            "ci_low": low, "ci_high": high, "n_paired_scenarios": len(v),
                            "excluded_unpaired_scenarios": int(len(cells.xs(stratum, level="stratum")) - len(v)),
                            "no_variation": bool(np.ptp(v) == 0)})
        if len(values) > 1:
            groups = list(values.values())
            draws = np.mean([[g[rng.integers(len(g), size=len(g))].mean() for g in groups] for _ in range(samples)], axis=1) \
                if all(len(g) >= 2 for g in groups) else None
            records.append({"metric": metric, "contrast": name, "stratum": "MACRO",
                            "estimate": float(np.mean([g.mean() for g in groups])),
                            "ci_low": float(np.quantile(draws, .025)) if draws is not None else None,
                            "ci_high": float(np.quantile(draws, .975)) if draws is not None else None,
                            "n_paired_scenarios": sum(len(g) for g in groups), "excluded_unpaired_scenarios": None,
                            "no_variation": bool(all(np.ptp(g) == 0 for g in groups))})
    return records


def analyze(run_dir: Path, output_dir: Path, *, manifest: Path | None = None, allow_incomplete: bool = False,
            bootstrap: int = 1000) -> dict:
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    episodes = pd.read_csv(run_dir / "episodes.csv")
    events = read_events(run_dir / "events.jsonl")
    if any(e["run_id"] != run["run_id"] for e in events) or episodes.run_id.nunique() != 1 or episodes.run_id.iloc[0] != run["run_id"]:
        raise ValueError("event/episode/run identity mismatch")
    keys = ["condition", "scenario_id", "repetition_index"]
    planned = {tuple(task) for task in run["planned_tasks"]}
    observed = set(episodes[keys].itertuples(index=False, name=None))
    if observed - planned:
        raise ValueError("unplanned episodes")
    complete = episodes[episodes.status == "complete"]
    if not allow_incomplete and (observed != planned or len(complete) != len(planned)):
        raise ValueError(f"incomplete run: {len(complete)}/{len(planned)} complete; use --allow-incomplete and label exploratory")
    strata = load_strata(manifest)
    by_attempt: dict[tuple, list[dict]] = {}
    for event in events:
        by_attempt.setdefault((event["episode_key"], int(event["episode_attempt"])), []).append(event)
    rows = []
    for _, episode in complete.iterrows():
        key = json.dumps([episode.condition, episode.scenario_id, int(episode.repetition_index)], separators=(",", ":"))
        trajectory = sorted(by_attempt.get((key, int(episode.episode_attempt)), []), key=lambda e: int(e.get("turn") or 0))
        extra = strata.get(episode.scenario_id, {})
        if strata and not extra:
            raise ValueError(f"scenario {episode.scenario_id} missing from manifest")
        rows.append({"condition": episode.condition, "scenario_id": episode.scenario_id,
                     "repetition_index": int(episode.repetition_index),
                     "stratum": stratum_label(extra, episode),
                     "voltage_condition": episode.voltage_condition, "success": int(episode.success),
                     "termination_reason": episode.termination_reason,
                     **{k: episode.get(k) for k in ("n_actual_power_flows", "total_tokens", "accounted_cost_cny")},
                     **{k: v for k, v in extra.items() if k != "structure_class"},
                     **episode_metrics(trajectory, episode.voltage_condition)})
    frame = pd.DataFrame(rows)
    output_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_dir / "mechanism_episodes.csv", index=False)
    summary = []
    groups = list(frame.groupby(["stratum", "condition"]))
    if frame.stratum.nunique() > 1:
        groups += [(("ALL", c), g) for c, g in frame.groupby("condition")]
    for (stratum, condition), group in groups:
        for metric in BINARY_METRICS:
            summary.append({"stratum": stratum, "condition": condition, "metric": metric, "kind": "rate", **fraction_ci(group, metric)})
        for metric in CONTINUOUS_METRICS:
            values = pd.to_numeric(group[metric], errors="coerce").dropna()
            summary.append({"stratum": stratum, "condition": condition, "metric": metric, "kind": "mean", "n": len(values),
                            "rate": float(values.mean()) if len(values) else None, "n_scenarios": group.scenario_id.nunique()})
    export_csv(output_dir / "mechanism_summary.csv", summary)
    rng = np.random.default_rng(2026)
    contrasts = []
    for metric in CONTRAST_METRICS:
        # An episode with no proposal did not succeed at its first proposal (intention-to-treat).
        subset = frame.assign(**{metric: pd.to_numeric(frame[metric]).fillna(0)}) if metric == "first_proposal_success" else frame
        contrasts += paired_contrasts(subset, metric, bootstrap, rng)
    export_csv(output_dir / "structure_contrasts.csv", contrasts)
    report = {"run_id": run["run_id"], "planned": len(planned), "complete": len(complete),
              "strata": sorted(frame.stratum.unique().tolist()), "manifest": str(manifest) if manifest else None,
              "exploratory": bool(allow_incomplete and len(complete) != len(planned)),
              "note": "Dev diagnostics; contrasts are scenario-paired rate differences with scenario bootstrap, not frozen Test claims"}
    (output_dir / "mechanism_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, help="Evaluator-side corpus manifest with structure_class (v3)")
    parser.add_argument("--allow-incomplete", action="store_true", help="Exploratory only; never a complete-matrix result")
    parser.add_argument("--bootstrap", type=int, default=1000)
    args = parser.parse_args()
    print(json.dumps(analyze(args.run_dir, args.output_dir, manifest=args.manifest,
                             allow_incomplete=args.allow_incomplete, bootstrap=args.bootstrap), indent=2))


if __name__ == "__main__":
    main()
