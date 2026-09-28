"""Offline behavioral diagnostics from CNY event logs. Never calls an API/evaluator."""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from poweragentbench.voltage_costs import read_events, ledger_totals
from poweragentbench.voltage_evaluator import normalize_dispatch


def export_csv(path: Path, rows: list[dict], fields=None) -> None:
    columns = fields or list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v for k, v in row.items()})


def fraction_ci(frame: pd.DataFrame, column: str) -> dict:
    observed = frame.dropna(subset=[column])
    n = len(observed)
    result = {"n": n, "positive": int(observed[column].sum()) if n else 0,
              "rate": float(observed[column].mean()) if n else None, "ci_low": None, "ci_high": None,
              "n_scenarios": observed.scenario_id.nunique() if n else 0}
    # One-case smoke intervals falsely imply certainty; leave these as NA.
    if result["n_scenarios"] >= 2:
        groups = [group[column].to_numpy(dtype=float) for _, group in observed.groupby("scenario_id")]
        rng = np.random.default_rng(2026)
        samples = [np.concatenate([groups[i] for i in rng.integers(len(groups), size=len(groups))]).mean() for _ in range(1000)]
        result["ci_low"], result["ci_high"] = map(float, np.quantile(samples, [.025, .975]))
    return result


def dispatch_key(args: dict) -> str | None:
    try:
        dispatch = normalize_dispatch(args.get("dispatch"))
        pairs = sorted((row["bess_id"], float(row["p_mw"])) for row in dispatch if float(row["p_mw"]) != 0)
        return json.dumps(pairs)
    except (ValueError, TypeError):
        return None


def analyze(run_dir: Path, campaign_dir: Path, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    totals = ledger_totals(campaign_dir / "requests.jsonl")
    events = read_events(run_dir / "events.jsonl")
    if len({e["event_id"] for e in events}) != len(events):
        raise ValueError("duplicate event_id")
    if any(e["run_id"] != run["run_id"] for e in events):
        raise ValueError("event/run identity mismatch")
    requests = [event for event in read_events(campaign_dir / "requests.jsonl") if event.get("context", {}).get("run_id") == run["run_id"]]
    export_csv(output_dir / "events.csv", events, fields=list(dict.fromkeys(k for row in events for k in row)) or ["event_id"])
    export_csv(output_dir / "requests.csv", requests, fields=list(dict.fromkeys(k for row in requests for k in row)) or ["request_id"])
    # Statistical inputs below are standardized CSV, not provider objects.
    event_rows = list(csv.DictReader((output_dir / "events.csv").open(encoding="utf-8")))
    episodes = pd.read_csv(run_dir / "episodes.csv")
    if episodes.empty:
        raise ValueError("no episode records")
    keys = ["condition", "scenario_id", "repetition_index"]
    if episodes.duplicated(keys).any() or episodes.run_id.nunique() != 1 or episodes.run_id.iloc[0] != run["run_id"]:
        raise ValueError("invalid episode identity")
    planned = {tuple(task) for task in run["planned_tasks"]}
    observed = set(episodes[keys].itertuples(index=False, name=None))
    if observed - planned:
        raise ValueError("unplanned episodes")
    recovery_rows, streak_rows, preview_rows, transitions = [], [], [], Counter()
    failure_types = Counter()
    for _, episode in episodes.iterrows():
        key = json.dumps([episode.condition, episode.scenario_id, int(episode.repetition_index)], separators=(",", ":"))
        attempt = int(episode.episode_attempt)
        trajectory = [e for e in event_rows if e.get("episode_key") == key and int(e["episode_attempt"]) == attempt]
        operations = [e for e in trajectory if e["event"] in ("tool_finished", "parse_error", "output_truncated")]
        if len({e["turn"] for e in operations}) != len(operations):
            raise ValueError("duplicate operations per turn: reconcile checkpoint events before analysis")
        for event in operations:
            error = event["event"] if event["event"] in ("parse_error", "output_truncated") else event.get("outcome")
            if error and error != "ok":
                failure_types[(episode.condition, error)] += 1
        done = episode.status == "complete"
        success = float(episode.success) if done else None
        common = dict(condition=episode.condition, scenario_id=episode.scenario_id, repetition_index=int(episode.repetition_index))
        tools = [e for e in operations if e["event"] == "tool_finished"]
        for previous, current in zip(tools, tools[1:]):
            transitions[(episode.condition, previous["tool"], current["tool"])] += 1
        submits = [e for e in tools if e["tool"].strip().lower() == "submit" and json.loads(e["observation"]).get("verification") is not None]
        if submits:
            first = json.loads(submits[0]["observation"])["verification"]
            if not first["success"]:
                recovery_rows.append({**common, "recovery_enabled": int(episode.recovery), "first_failure_type": submits[0]["outcome"],
                                      "final_success": success, "final_failure": 1 - success if success is not None else None,
                                      "censored": not done, "termination_reason": episode.termination_reason})
        for category in ("command", "physical"):
            relevant = [e for e in operations if e["event"] != "output_truncated"] if category == "command" else [e for e in tools if e["tool"] in ("submit", "preview_bess_dispatch") and e.get("outcome") not in ("invalid_dispatch", "tool_error")]
            def failed(e):
                return (e["event"] == "parse_error" or e.get("outcome") in ("invalid_dispatch", "unknown_tool", "tool_error")) if category == "command" else e.get("outcome") in ("voltage_unresolved", "pf_nonconverged")
            start = next((i for i, e in enumerate(relevant) if failed(e)), None)
            if start is not None:
                end = start
                while end < len(relevant) and failed(relevant[end]):
                    end += 1
                length = end - start
                for k in range(1, length + 1):
                    next_index = start + k
                    next_ok = int(not failed(relevant[next_index])) if next_index < len(relevant) else None
                    streak_rows.append({**common, "category": category, "k": k, "first_streak_length": length,
                                        "next_relevant_operation_success": next_ok, "next_unobserved": next_ok is None,
                                        "eventual_operation_recovery": int(end < len(relevant)) if end < len(relevant) or done else None,
                                        "final_success": success, "termination_reason": episode.termination_reason})
        previews = [e for e in tools if e["tool"].strip().lower() == "preview_bess_dispatch" and "preview" in json.loads(e["observation"])]
        stagnant = 0
        for index, event in enumerate(previews):
            feedback = json.loads(event["observation"])["preview"]
            args = json.loads(event["args"])
            next_event = previews[index + 1] if index + 1 < len(previews) else None
            later = json.loads(next_event["observation"])["preview"] if next_event else None
            before, after = feedback.get("voltage_violation_magnitude"), later.get("voltage_violation_magnitude") if later else None
            stagnant = stagnant + 1 if before is not None and after is not None and after >= before else 0
            following_submit = next((e for e in submits if int(e["turn"]) > int(event["turn"])), None)
            preview_rows.append({**common, "turn": int(event["turn"]), "preview_success": int(bool(feedback.get("success"))),
                                 "next_preview_success": int(bool(later.get("success"))) if later else None,
                                 "consecutive_nonimproving_transitions": stagnant,
                                 "violation_improvement": before - after if before is not None and after is not None else None,
                                 "repeated_next_dispatch": int(dispatch_key(args) == dispatch_key(json.loads(next_event["args"]))) if next_event and dispatch_key(args) is not None else None,
                                 "same_following_submit": int(dispatch_key(args) == dispatch_key(json.loads(following_submit["args"]))) if following_submit and dispatch_key(args) is not None else None,
                                 "following_submit_success": int(bool(json.loads(following_submit["observation"])["accepted"])) if following_submit else None})
    export_csv(output_dir / "first_failure_episodes.csv", recovery_rows,
               fields=list(recovery_rows[0]) if recovery_rows else ["condition", "scenario_id", "final_failure"])
    recovery = pd.DataFrame(recovery_rows)
    summaries = []
    if not recovery.empty:
        for (condition, error), group in recovery.groupby(["condition", "first_failure_type"]):
            summaries.append({"condition": condition, "first_failure_type": error, "first_failed_episodes": len(group),
                              "censored": int(group.censored.sum()), "R0_design_terminal": int(group.recovery_enabled.iloc[0] == 0),
                              **fraction_ci(group, "final_failure")})
    export_csv(output_dir / "recovery_summary.csv", summaries, fields=list(summaries[0]) if summaries else ["condition", "n", "rate"])
    export_csv(output_dir / "error_streaks.csv", streak_rows, fields=list(streak_rows[0]) if streak_rows else ["condition", "category", "k"])
    streak_summary = []
    if streak_rows:
        frame = pd.DataFrame(streak_rows)
        for (condition, category, k), group in frame.groupby(["condition", "category", "k"]):
            for field in ("next_relevant_operation_success", "eventual_operation_recovery", "final_success"):
                streak_summary.append({"condition": condition, "category": category, "k": k, "outcome": field,
                                       "eligible": len(group), "unobserved": int(group[field].isna().sum()), **fraction_ci(group, field)})
    export_csv(output_dir / "streak_summary.csv", streak_summary, fields=list(streak_summary[0]) if streak_summary else ["condition", "category", "k", "rate"])
    export_csv(output_dir / "preview_summary.csv", preview_rows, fields=list(preview_rows[0]) if preview_rows else ["condition", "turn"])
    export_csv(output_dir / "failure_types.csv", [{"condition": c, "failure_type": kind, "count": n} for (c, kind), n in failure_types.items()],
               fields=["condition", "failure_type", "count"])
    preview_stats = []
    if preview_rows:
        frame = pd.DataFrame(preview_rows)
        for condition, group in frame.groupby("condition"):
            for field in ("next_preview_success", "repeated_next_dispatch", "same_following_submit", "following_submit_success"):
                subset = group[group.preview_success == (0 if field == "next_preview_success" else 1)] if field != "repeated_next_dispatch" else group
                preview_stats.append({"condition": condition, "metric": field, "eligible": len(subset),
                                      "unobserved": int(subset[field].isna().sum()), **fraction_ci(subset, field)})
    export_csv(output_dir / "preview_rates.csv", preview_stats, fields=list(preview_stats[0]) if preview_stats else ["condition", "metric", "n", "rate"])
    transition_rows = [{"condition": c, "previous": a, "next": b, "count": count,
                        "probability": count / sum(n for (cc, aa, _), n in transitions.items() if cc == c and aa == a)} for (c, a, b), count in transitions.items()]
    export_csv(output_dir / "action_transitions.csv", transition_rows, fields=list(transition_rows[0]) if transition_rows else ["condition", "previous", "next", "count"])
    termination = episodes.groupby(["condition", "status", "termination_reason"], dropna=False).size().reset_index(name="count")
    termination.to_csv(output_dir / "termination_summary.csv", index=False)
    costs = []
    for (condition, status, reason), group in episodes.groupby(["condition", "status", "termination_reason"], dropna=False):
        cost = pd.to_numeric(group.accounted_cost_cny, errors="coerce")
        costs.append({"condition": condition, "status": status, "termination_reason": reason, "n": len(group),
                      "accounted_cost_mean_cny": cost.mean(), "accounted_cost_median_cny": cost.median(), "accounted_cost_p90_cny": cost.quantile(.9),
                      "unknown_requests": group.unknown_cost_requests.fillna(0).sum(), "mean_turns": group.n_llm_turns.mean(),
                      "mean_actual_pf": group.n_actual_power_flows.mean(), "note": "known estimates/upper bounds; not invoice; unknown charges excluded"})
    export_csv(output_dir / "cost_summary.csv", costs)
    budget_curve = []
    for condition, group in episodes.groupby("condition"):
        denominator = sum(task[0] == condition for task in planned)
        for threshold in (.02, .05, .10, .20):
            known = (group.status == "complete") & (group.success == 1) & (group.unknown_cost_requests == 0)
            successes = int((known & (pd.to_numeric(group.accounted_cost_cny, errors="coerce") <= threshold)).sum())
            budget_curve.append({"condition": condition, "threshold_cny": threshold, "known_success_by_amount": successes,
                                 "planned": denominator, "fraction": successes / denominator,
                                 "note": "observed trajectories only, not causal budget sweep; unobserved tasks retained in denominator"})
    export_csv(output_dir / "observed_budget_curve.csv", budget_curve)
    success_count = int(((episodes.status == "complete") & (episodes.success == 1)).sum())
    unresolved = len(planned) - int((episodes.status == "complete").sum())
    report = {"run_id": run["run_id"], "planned": len(planned), "recorded": len(episodes), "known_success": success_count,
              "unresolved": unresolved, "success_lower_bound": success_count / len(planned),
              "success_upper_bound": (success_count + unresolved) / len(planned), "n_scenarios": episodes.scenario_id.nunique(),
              "campaign_cost": totals, "note": "Dev diagnostics; bounds are coverage bounds, not confidence intervals"}
    (output_dir / "trajectory_summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    plot(termination, costs, summaries, output_dir)
    return report


def plot(termination, costs, recovery, root):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    cost_frame = pd.DataFrame(costs)
    cost_frame["weighted_cost"] = cost_frame.accounted_cost_mean_cny * cost_frame.n
    weighted = cost_frame.groupby("condition").weighted_cost.sum() / cost_frame.groupby("condition").n.sum()
    figures = [
        ("termination", termination.groupby("termination_reason")["count"].sum(), "Episodes (all recorded statuses)"),
        ("cost", weighted, "Accounted CNY (unknown charges excluded)"),
    ]
    if recovery:
        frame = pd.DataFrame(recovery)
        frame = frame[(frame.R0_design_terminal == 0) & frame.rate.notna()]
        if not frame.empty:
            figures.append(("recovery_failure", frame.set_index(["condition", "first_failure_type"])["rate"], "P(final failure | first submit failed, R1); see CSV denominators"))
    for name, values, label in figures:
        fig, ax = plt.subplots(figsize=(9, 4))
        values.plot.bar(ax=ax)
        ax.set_ylabel(label); fig.tight_layout()
        fig.savefig(root / f"{name}.png", dpi=150); plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(analyze(args.run_dir, args.campaign_dir, args.output_dir), indent=2))


if __name__ == "__main__":
    main()
