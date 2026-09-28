"""Dev-only action-space study: no LLM, no corpus edits, no Test evaluation."""
from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import random
import statistics
from pathlib import Path

from poweragentbench.voltage_case import (DEFAULT_CONFIG_PATH, load_benchmark_config,
    load_scenario_metadata, load_scenario_network, read_json, sha256_file)
from poweragentbench.voltage_evaluator import (apply_bess_dispatch, evaluate_voltage_dispatch,
    run_locked_power_flow, state_metrics, validate_dispatch)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sample_grid(axes: list[list[float]], size: int, rng: random.Random) -> list[tuple]:
    total = math.prod(len(axis) for axis in axes)
    result = []
    for flat in rng.sample(range(total), min(size, total)):
        indices = []
        for axis in reversed(axes):
            indices.append(flat % len(axis))
            flat //= len(axis)
        result.append(tuple(axis[index] for axis, index in zip(axes, reversed(indices))))
    return result


def wilson(successes: int, n: int) -> tuple[float, float]:
    # Approximation for a uniform without-replacement sample; conservative vs
    # applying a finite-population correction, not a scenario-population CI.
    z = 1.96
    p = successes / n
    centre = (p + z*z/(2*n)) / (1 + z*z/n)
    width = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / (1 + z*z/n)
    return centre - width, centre + width


def study(root: Path, output: Path, samples=256, seed=2030, case_limit=None, case_ids=None, directional_samples=None):
    corpus = read_json(root.parent / "corpus_manifest.json")
    if sha256_file(root / "manifest.json") != corpus["split_manifest_sha256"]["dev"]:
        raise ValueError("only the verified Dev manifest is allowed")
    if samples < 1 or (directional_samples is not None and directional_samples < 1) or (case_limit is not None and case_limit < 1):
        raise ValueError("sample counts must be positive")
    if output.exists():
        raise ValueError("output directory must be new")
    manifest = read_json(root / "manifest.json")
    config = load_benchmark_config()
    if manifest["benchmark_config_sha256"] != sha256_file(DEFAULT_CONFIG_PATH):
        raise ValueError("benchmark config differs from corpus")
    entries = manifest["scenarios"][:case_limit]
    if case_ids:
        if set(case_ids) - {entry["scenario_id"] for entry in entries}:
            raise ValueError("unknown selected Dev scenario")
        entries = [entry for entry in entries if entry["scenario_id"] in case_ids]
    protocol = {"purpose": "Dev-only physical difficulty diagnosis; not a Test filter", "seed": seed,
                "full_samples": samples, "directional_samples": directional_samples or samples,
                "case_count": len(entries), "case_ids": [entry["scenario_id"] for entry in entries],
                "dataset_sha256": corpus["dataset_sha256"], "dev_manifest_sha256": sha256_file(root / "manifest.json"),
                "benchmark_config_sha256": sha256_file(DEFAULT_CONFIG_PATH), "script_sha256": sha256_file(__file__),
                "sampling": "uniform without replacement over full legal grid and separately over correct-sign grid including zero",
                "uniform_strategy": "all BESS at correct-sign 0.25, 0.50, ... 1.50 MW; predetermined ascending order",
                "local_test": "each legal +/- one-step neighbor of the existing Dev witness; not optimized robustness",
                "selection": "all Dev cases retained; no baseline-success filtering",
                "interval": "per-case Wilson approximation for samples; census has exact fraction; neither is LLM success probability"}
    write_json(output / "protocol.json", protocol)
    witnesses = read_json(root.parent / "evaluator_private" / "witnesses.json")
    witnesses = {row["scenario_id"]: row["dispatch"] for row in witnesses if row["split"] == "dev"}
    summaries = []
    for entry in entries:
        sid = entry["scenario_id"]
        metadata = load_scenario_metadata(sid, root)
        net = load_scenario_network(sid, root)
        specs = metadata["bess"]
        axes = [[round(spec["p_min_mw"] + i*spec["step_mw"], 10)
                 for i in range(round((spec["p_max_mw"]-spec["p_min_mw"])/spec["step_mw"]) + 1)] for spec in specs]
        sign = 1 if entry["condition"] == "UNDERVOLTAGE" else -1
        directed = [[value for value in axis if value*sign >= 0] for axis in axes]
        cache = {}
        def evaluate(values):
            values = tuple(values)
            if values not in cache:
                dispatch = [{"bess_id": spec["bess_id"], "p_mw": value} for spec, value in zip(specs, values)]
                validate_dispatch(dispatch, metadata)
                trial = copy.deepcopy(net)
                apply_bess_dispatch(trial, dispatch, metadata)
                ok, error = run_locked_power_flow(trial, config["solver"])
                state = state_metrics(trial, metadata, converged=ok, error=error)
                limits = config["voltage_limits_pu"]
                cache[values] = {"success": bool(ok and state["voltage_violation_count"] == 0), "converged": ok,
                                 "under": bool(state["undervoltage_buses"]), "over": bool(state["overvoltage_buses"]),
                                 "magnitude": state["voltage_violation_magnitude"],
                                 "margin": min(state["min_vm_pu"]-limits["min"], limits["max"]-state["max_vm_pu"]) if ok else None}
            return cache[values]
        row = {"scenario_id": sid, "condition": entry["condition"], "severity_bin": entry["difficulty"],
               "initial_severity": entry["severity"], "full_grid_size": math.prod(map(len, axes)),
               "directional_grid_size": math.prod(map(len, directed))}
        sample_results = []
        for label, grid in (("full", axes), ("directional", directed)):
            sample_count = directional_samples if label == "directional" and directional_samples is not None else samples
            actions = sample_grid(grid, sample_count, random.Random(f"{seed}:{sid}:{label}"))
            results = [evaluate(action) for action in actions]
            successes = sum(result["success"] for result in results)
            row.update({f"{label}_sample_n": len(results), f"{label}_feasible_n": successes,
                        f"{label}_feasible_fraction": successes/len(results),
                        f"{label}_nonconverged_n": sum(not result["converged"] for result in results),
                        f"{label}_mixed_violation_n": sum(result["under"] and result["over"] for result in results)})
            exhaustive = len(results) == math.prod(map(len, grid))
            row[f"{label}_exhaustive"] = exhaustive
            row[f"{label}_ci_low"], row[f"{label}_ci_high"] = (successes/len(results),)*2 if exhaustive else wilson(successes, len(results))
            for action, result in zip(actions, results):
                sample_results.append({"space": label, "action": list(action), **result})
        # Fixed one-shot and fixed-order uniform search, not chosen from random samples.
        uniform = [evaluate([sign*step*.25]*len(specs)) for step in range(1, 7)]
        row["one_shot_025_success"] = int(uniform[0]["success"])
        row["one_shot_050_success"] = int(uniform[1]["success"])
        row["one_shot_100_success"] = int(uniform[3]["success"])
        row["uniform_successful_levels"] = sum(r["success"] for r in uniform)
        row["uniform_first_success_trial"] = next((i+1 for i,r in enumerate(uniform) if r["success"]), None)
        row["uniform_within_2_success"] = int(any(r["success"] for r in uniform[:2]))
        row["uniform_within_4_success"] = int(any(r["success"] for r in uniform[:4]))
        witness = validate_dispatch(witnesses[sid], metadata)
        replay = evaluate_voltage_dispatch(sid, witness, scenario_root=root)
        if not replay["success"]:
            raise ValueError(f"Dev witness replay failed: {sid}")
        witness_map = {item["bess_id"]: item["p_mw"] for item in witness}
        values = tuple(witness_map.get(spec["bess_id"], 0.0) for spec in specs)
        row["witness_margin_pu"] = evaluate(values)["margin"]
        neighbors = []
        for i, spec in enumerate(specs):
            for direction in (-1,1):
                candidate = list(values); candidate[i] += direction*spec["step_mw"]
                if candidate[i] in axes[i]:
                    neighbors.append(evaluate(candidate))
        row.update(neighbor_count=len(neighbors), feasible_neighbors=sum(r["success"] for r in neighbors),
                   neighbor_success_fraction=sum(r["success"] for r in neighbors)/len(neighbors),
                   neighbor_mixed_violations=sum(r["under"] and r["over"] for r in neighbors),
                   n_actual_power_flows=len(cache)+1)
        # Independent replay of one sampled action checks the fast in-memory path.
        first = sample_results[0]
        dispatch = [{"bess_id": spec["bess_id"], "p_mw": value} for spec,value in zip(specs, first["action"])]
        check = evaluate_voltage_dispatch(sid, dispatch, scenario_root=root)
        assert bool(check["success"]) == first["success"]
        row["n_actual_power_flows"] += check["n_actual_power_flows"]
        write_json(output / "evaluator_private" / f"{sid}_samples.json", sample_results)
        summaries.append(row)
        with (output / "landscape.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(row)); writer.writeheader(); writer.writerows(summaries)
    summary = {"cases": len(summaries), "actual_power_flows": sum(r["n_actual_power_flows"] for r in summaries),
               "full_density_median": statistics.median(r["full_feasible_fraction"] for r in summaries),
               "directional_density_median": statistics.median(r["directional_feasible_fraction"] for r in summaries),
               "one_shot_025_successes": sum(r["one_shot_025_success"] for r in summaries),
               "one_shot_050_successes": sum(r["one_shot_050_success"] for r in summaries),
               "one_shot_100_successes": sum(r["one_shot_100_success"] for r in summaries),
               "uniform_within_2_successes": sum(r["uniform_within_2_success"] for r in summaries),
               "uniform_within_4_successes": sum(r["uniform_within_4_success"] for r in summaries),
               "uniform_any_successes": sum(r["uniform_successful_levels"]>0 for r in summaries),
               "neighbor_success_fraction_median": statistics.median(r["neighbor_success_fraction"] for r in summaries),
               "note": "Check *_exhaustive columns for directional census; full-space sample zeros do not prove infeasibility. Neighborhood only around construction witnesses. No LLM calls."}
    write_json(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=256)
    parser.add_argument("--seed", type=int, default=2030)
    parser.add_argument("--case-limit", type=int)
    parser.add_argument("--scenario-id", action="append")
    parser.add_argument("--directional-samples", type=int)
    args = parser.parse_args()
    print(json.dumps(study(args.scenario_root, args.output_dir, args.samples, args.seed, args.case_limit, args.scenario_id, args.directional_samples), indent=2))


if __name__ == "__main__":
    main()
