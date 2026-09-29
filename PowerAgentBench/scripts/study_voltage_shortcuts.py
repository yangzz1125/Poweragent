"""Dev-only fixed policy/template audit. No LLM calls or new dataset selection."""
from __future__ import annotations

import argparse
import csv
import itertools
import json
from collections import Counter
from pathlib import Path

from poweragentbench.voltage_case import DEFAULT_CONFIG_PATH, load_scenario_metadata, read_json, sha256_file
from poweragentbench.voltage_evaluator import evaluate_voltage_dispatch


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def uniform_bisection(evaluate, condition: str, n_bess: int = 4, budget: int = 4):
    """Fixed 0.25 MW grid policy; uses only each proposed action's PF feedback."""
    if condition not in ("UNDERVOLTAGE", "OVERVOLTAGE"):
        raise ValueError("bisection requires a pure under/over initial condition")
    sign = 1 if condition == "UNDERVOLTAGE" else -1
    low, high = 1, 6
    trace = []
    for _ in range(budget):
        if low > high:
            break
        step = (low + high) // 2
        values = (sign * step * .25,) * n_bess
        result = evaluate(values)
        trace.append({"values": list(values), "success": bool(result["success"])})
        if result["success"]:
            return True, trace, "success"
        if not result.get("converged"):
            return False, trace, "pf_nonconverged"
        state = result["final_state"]
        under, over = bool(state["undervoltage_buses"]), bool(state["overvoltage_buses"])
        if under and over:
            return False, trace, "mixed_violation"
        needs_more = under if sign > 0 else over
        if needs_more:
            low = step + 1
        else:
            high = step - 1
    return False, trace, "bracket_empty" if low > high else "query_budget"


def classify(full_bound, uniform, single, zero_full):
    if full_bound:
        return "all_bess_full_power"
    if uniform:
        return "uniform_interior"
    if single:
        return "single_bess_nonuniform"
    if zero_full:
        return "zero_full_combination"
    return "outside_tested_templates"


def study(root: Path, output: Path):
    corpus = read_json(root.parent / "corpus_manifest.json")
    if sha256_file(root / "manifest.json") != corpus["split_manifest_sha256"]["dev"]:
        raise ValueError("only verified Dev may be audited")
    manifest = read_json(root / "manifest.json")
    if manifest["benchmark_config_sha256"] != sha256_file(DEFAULT_CONFIG_PATH):
        raise ValueError("frozen config mismatch")
    if output.exists():
        raise ValueError("output directory must be new")
    write_json(output / "protocol.json", {
        "purpose": "Dev structural coverage diagnosis, no Test filtering", "case_count": len(manifest["scenarios"]),
        "dataset_sha256": corpus["dataset_sha256"], "dev_manifest_sha256": sha256_file(root / "manifest.json"),
        "config_sha256": sha256_file(DEFAULT_CONFIG_PATH), "script_sha256": sha256_file(__file__),
        "fixed_feedback_policy": "uniform bisection on magnitude indices 1..6, floor midpoint, 0.25 MW step, at most 4 PF queries; stop on mixed violation/nonconvergence",
        "full_power_policy": "all 4 BESS +1.5 MW for under or -1.5 MW for over",
        "uniform_templates": "all 12 nonzero common signed levels in [-1.5,1.5]",
        "single_bess_templates": "one BESS at any of 12 nonzero levels; remaining BESS zero",
        "zero_full_templates": "all 3^4 combinations with each BESS in {-1.5,0,+1.5}",
        "ordering": "feedback policy runs before template enumeration; no template/witness lookahead",
        "interpretation": "template existence is an oracle coverage result, not a 4-query controller success rate; no witness used",
    })
    rows = []
    for entry in manifest["scenarios"]:
        sid = entry["scenario_id"]
        metadata = load_scenario_metadata(sid, root)
        specs = metadata["bess"]
        if len(specs) != 4 or any((s["p_min_mw"], s["p_max_mw"], s["step_mw"]) != (-1.5, 1.5, .25) for s in specs):
            raise ValueError("this diagnostic is restricted to the fixed 4-BESS benchmark")
        cache = {}
        def dispatch(values):
            return [{"bess_id": spec["bess_id"], "p_mw": float(value)} for spec, value in zip(specs, values)]
        def evaluate(values):
            key = tuple(values)
            if key not in cache:
                cache[key] = evaluate_voltage_dispatch(sid, dispatch(key), scenario_root=root)
            return cache[key]
        success, trace, reason = uniform_bisection(evaluate, entry["condition"])
        # Replay final policy action from a new frozen network, even on failure.
        replay = evaluate_voltage_dispatch(sid, dispatch(trace[-1]["values"]), scenario_root=root)
        assert bool(replay["success"]) == success
        sign = 1 if entry["condition"] == "UNDERVOLTAGE" else -1
        full_bound = bool(evaluate((sign*1.5,) * 4)["success"])
        levels = [i*.25 for i in range(-6,7) if i]
        uniform_n = sum(bool(evaluate((level,)*4)["success"]) for level in levels)
        single_n = 0
        for index in range(4):
            for level in levels:
                values = [0.0]*4; values[index] = level
                single_n += bool(evaluate(values)["success"])
        zero_full_n = sum(bool(evaluate(values)["success"]) for values in itertools.product((-1.5,0,1.5), repeat=4))
        row = {"scenario_id": sid, "condition": entry["condition"], "severity_bin": entry["difficulty"],
               "all_full_success": int(full_bound), "uniform_feasible_templates": uniform_n,
               "single_bess_feasible_templates": single_n, "zero_full_feasible_templates": zero_full_n,
               "bisection_success": int(success), "bisection_queries": len(trace), "bisection_stop": reason,
               "bisection_total_pf_with_final_replay": len(trace)+1,
               "structure_class": classify(full_bound, uniform_n, single_n, zero_full_n),
               "actual_study_pf_calls": sum(report["n_actual_power_flows"] for report in cache.values()) + replay["n_actual_power_flows"]}
        rows.append(row)
        write_json(output / "evaluator_private" / f"{sid}_policy_trace.json", trace)
        with (output / "coverage.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(row)); writer.writeheader(); writer.writerows(rows)
    summary = {"cases": len(rows), "structure_counts": dict(Counter(row["structure_class"] for row in rows)),
               "all_full_successes": sum(row["all_full_success"] for row in rows),
               "uniform_coverage": sum(row["uniform_feasible_templates"]>0 for row in rows),
               "single_bess_coverage": sum(row["single_bess_feasible_templates"]>0 for row in rows),
               "zero_full_coverage": sum(row["zero_full_feasible_templates"]>0 for row in rows),
               "bisection_successes": sum(row["bisection_success"] for row in rows),
               "bisection_query_count": sum(row["bisection_queries"] for row in rows),
               "actual_power_flows": sum(row["actual_study_pf_calls"] for row in rows),
               "note": "All Dev cases retained. Failure of tested templates does not prove intrinsic complexity. No model API calls."}
    write_json(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(study(args.scenario_root, args.output_dir), indent=2))


if __name__ == "__main__":
    main()
