"""Dev-only spatial candidate study; does not read, select or overwrite Test cases."""
from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

from poweragentbench.voltage_storage import evaluator_output_root
from poweragentbench.voltage_agentic import VoltageSensitivityGreedyAgent
from poweragentbench.voltage_case import (
    DEFAULT_CONFIG_PATH, REPO_ROOT, build_ieee33_network, load_benchmark_config,
    sha256_file, write_pandapower_json,
)
from poweragentbench.voltage_evaluator import evaluate_voltage_dispatch, run_locked_power_flow, state_metrics


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def audit(root: Path, seed: int = 2027, count: int = 40, profile: str = "exploratory") -> dict:
    root = evaluator_output_root(root)
    if profile not in ("exploratory", "stratified"):
        raise ValueError("unknown sampling profile")
    if count < 1 or (root.exists() and any(root.iterdir())):
        raise ValueError("positive candidate count and empty output directory required")
    config = load_benchmark_config()
    rng = random.Random(seed)
    config_hash = sha256_file(DEFAULT_CONFIG_PATH)
    # Publish the sampling contract before running candidates. No success-based
    # quotas or filtering: all candidates, including search failures, are retained.
    write_json(root / "protocol.json", {
        "purpose": "development-only difficulty audit, not a dataset freeze",
        "seed": seed, "candidates": count, "profile": profile,
        "sampling": {
            "exploratory": {"load": [0.6, 1.8], "load_multiplier": [0.3, 2.5], "pv_count": [0, 4], "pv_bus": [5, 32], "pv_mw": [0.3, 3.5]},
            "stratified_under": {"load": [0.7, 1.5], "load_multiplier": [0.3, 2.5], "pv_count": [0, 2], "pv_bus": [5, 32], "pv_mw": [0.1, 0.8]},
            "stratified_over": {"load": [0.3, 0.8], "load_multiplier": [0.5, 1.5], "pv_count": [2, 4], "pv_bus": [10, 32], "pv_mw": [1.2, 3.5]},
        },
        "allocation": "alternating under/over generation profiles; actual condition determined by power flow; no resampling to fill success quotas",
        "one_shot": "all four BESS +0.5 MW for under, -0.5 MW for over; mixed excluded; one independent PF",
        "margin": "min(final min voltage - 0.95, 1.05 - final max voltage) for search witness; not optimal margin",
        "uniform_trials": "all four BESS equal: +/-0.25 through +/-1.5 MW, 12 evaluations",
        "witness_search": "existing VoltageSensitivityGreedyAgent, max_steps=48, starts at zero independently of uniform trials",
        "search_failure_semantics": "no witness found; NOT proven infeasible",
        "benchmark_config_sha256": config_hash,
        "generator_sha256": sha256_file(__file__),
        "pandapower_version": __import__("pandapower").__version__,
    })
    entries, rows = [], []
    for index in range(count):
        scenario_id = f"A{index+1:04d}"
        target = "exploratory" if profile == "exploratory" else ("under" if index % 2 == 0 else "over")
        ranges = {
            "exploratory": ((0.6, 1.8), (0.3, 2.5), (0, 4), (0.3, 3.5), 5),
            "under": ((0.7, 1.5), (0.3, 2.5), (0, 2), (0.1, 0.8), 5),
            "over": ((0.3, 0.8), (0.5, 1.5), (2, 4), (1.2, 3.5), 10),
        }
        load_range, factor_range, count_range, pv_range, first_bus = ranges[target]
        load_scale = round(rng.uniform(*load_range), 4)
        pv = [(bus, round(rng.uniform(*pv_range), 4)) for bus in rng.sample(range(first_bus, 33), rng.randint(*count_range))]
        net = build_ieee33_network(load_scale=load_scale, pv_injections=pv, bess_specs=config["bess"])
        factors = [round(rng.uniform(*factor_range), 4) for _ in net.load.index]
        net.load.loc[:, "p_mw"] *= factors
        net.load.loc[:, "q_mvar"] *= factors
        ok, error = run_locked_power_flow(net, config["solver"])
        state = state_metrics(net, config, converged=ok, error=error)
        condition = "NONCONVERGENT" if not ok else (
            "MIXED" if state["undervoltage_buses"] and state["overvoltage_buses"] else
            "UNDERVOLTAGE" if state["undervoltage_buses"] else
            "OVERVOLTAGE" if state["overvoltage_buses"] else "NORMAL")
        state["condition"] = condition
        full, public = root / "full" / f"{scenario_id}.json", root / "public" / f"{scenario_id}.json"
        write_pandapower_json(net, full)
        write_json(public, {"scenario_id": scenario_id, "network": {"name": "IEEE33 Dev audit", "n_bus": len(net.bus), "n_line": len(net.line)},
                            "bess": config["bess"], "voltage_limits_pu": config["voltage_limits_pu"], "initial_state": state})
        entries.append({"scenario_id": scenario_id, "condition": condition, "load_scale": load_scale,
                        "per_load_multipliers": factors, "pv": pv, "full_path": f"full/{scenario_id}.json",
                        "public_path": f"public/{scenario_id}.json", "full_sha256": sha256_file(full), "public_sha256": sha256_file(public)})
        write_json(root / "manifest.json", {"dataset_version": config["dataset_version"], "benchmark_config_sha256": config_hash, "scenarios": entries})
        row = {"scenario_id": scenario_id, "generation_stratum": target, "condition": condition, "severity": state["voltage_violation_magnitude"],
               "status": "not_a_converged_violation", "uniform_success": None, "uniform_feasible_count": None,
               "uniform_pf_calls": 0, "search_success": None, "search_pf_calls": 0, "search_action_l1_mw": None,
               "one_shot_success": None, "one_shot_pf_calls": 0, "witness_margin_pu": None}
        if ok and state["voltage_violation_count"]:
            if condition in ("UNDERVOLTAGE", "OVERVOLTAGE"):
                power = .5 if condition == "UNDERVOLTAGE" else -.5
                dispatch = [{"bess_id": spec["bess_id"], "p_mw": power} for spec in config["bess"]]
                report = evaluate_voltage_dispatch(scenario_id, dispatch, scenario_root=root)
                row.update(one_shot_success=int(report["success"]), one_shot_pf_calls=report["n_actual_power_flows"])
            feasible = 0
            for step in (*range(-6, 0), *range(1, 7)):
                dispatch = [{"bess_id": spec["bess_id"], "p_mw": step * .25} for spec in config["bess"]]
                report = evaluate_voltage_dispatch(scenario_id, dispatch, scenario_root=root)
                feasible += int(report["success"])
                row["uniform_pf_calls"] += report["n_actual_power_flows"]
            output = VoltageSensitivityGreedyAgent(max_steps=48, scenario_root=root).run(scenario_id)
            report = evaluate_voltage_dispatch(scenario_id, output.dispatch, scenario_root=root)
            row.update(status="evaluated", uniform_success=int(feasible > 0), uniform_feasible_count=feasible,
                       search_success=int(report["success"]), search_pf_calls=int(output.power_flow_calls) + report["n_actual_power_flows"],
                       search_action_l1_mw=report.get("action_l1_mw"))
            if report["success"]:
                limits = config["voltage_limits_pu"]
                row["witness_margin_pu"] = min(report["final_min_vm_pu"] - limits["min"], limits["max"] - report["final_max_vm_pu"])
                write_json(root / "evaluator_private" / f"{scenario_id}_witness.json", output.dispatch)
        rows.append(row)
        with (root / "candidates.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(row))
            writer.writeheader(); writer.writerows(rows)
    evaluated = [row for row in rows if row["status"] == "evaluated"]
    summary = {"candidate_count": count, "profile": profile, "converged_violation_count": len(evaluated),
               "one_shot_eligible": sum(row["one_shot_success"] is not None for row in evaluated),
               "one_shot_successes": sum(row["one_shot_success"] or 0 for row in evaluated),
               "uniform_successes": sum(row["uniform_success"] for row in evaluated),
               "search_successes": sum(row["search_success"] for row in evaluated),
               "search_success_uniform_failure": sum(row["search_success"] and not row["uniform_success"] for row in evaluated),
               "unresolved_by_both": sum(not row["search_success"] and not row["uniform_success"] for row in evaluated),
               "note": "Dev study only; unresolved is not infeasible; mixed cases are exploratory, not added to the under/over benchmark"}
    write_json(root / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=2027)
    parser.add_argument("--num-candidates", type=int, default=40)
    parser.add_argument("--profile", choices=["exploratory", "stratified"], default="exploratory")
    args = parser.parse_args()
    print(json.dumps(audit(args.output_dir, args.seed, args.num_candidates, args.profile), indent=2))


if __name__ == "__main__":
    main()
