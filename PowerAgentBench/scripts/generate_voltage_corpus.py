"""Generate a reproducible, evaluator-only IEEE 33-bus Dev/Test corpus.

Keep --output-dir outside any agent-visible workspace. Give agents only the public
cards (through the tool server); the full snapshots and witnesses stay here.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
from pathlib import Path

from poweragentbench.voltage_case import (
    DEFAULT_CONFIG_PATH,
    REPO_ROOT,
    build_ieee33_network,
    load_benchmark_config,
    sha256_file,
    write_pandapower_json,
)
from poweragentbench.voltage_evaluator import (
    apply_bess_dispatch,
    evaluate_voltage_dispatch,
    run_locked_power_flow,
    state_metrics,
    validate_dispatch,
)

PV_BUSES = (10, 14, 17, 21, 24, 28, 32)


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def candidate(rng: random.Random, config: dict, index: int) -> dict | None:
    kind = "UNDERVOLTAGE" if index % 2 == 0 else "OVERVOLTAGE"
    load_scale = round(rng.uniform(0.7, 1.35) if kind == "UNDERVOLTAGE" else rng.uniform(0.4, 0.8), 4)
    buses = rng.sample(PV_BUSES, rng.randint(2, 3)) if kind == "OVERVOLTAGE" else []
    pv = [(bus, round(rng.uniform(0.8, 3.0), 4)) for bus in buses]
    net = build_ieee33_network(load_scale=load_scale, pv_injections=pv, bess_specs=config["bess"])
    converged, error = run_locked_power_flow(net, config["solver"])
    metadata = {"voltage_limits_pu": config["voltage_limits_pu"], "line_loading_percent_max": config["line_loading_percent_max"], "bess": config["bess"]}
    initial = state_metrics(net, metadata, converged=converged, error=error)
    if not converged or initial["voltage_violation_count"] == 0 or not 0 < initial["voltage_violation_magnitude"] < 10:
        return None
    if bool(initial["undervoltage_buses"]) == bool(initial["overvoltage_buses"]):
        return None
    actual = "UNDERVOLTAGE" if initial["undervoltage_buses"] else "OVERVOLTAGE"
    if actual != kind:
        return None
    initial["condition"] = actual
    # Try a simple uniform dispatch first. Every candidate witness is validated
    # against the same locked power flow and step/bounds as a real submission.
    sign = 1 if kind == "UNDERVOLTAGE" else -1
    witness = None
    for step in range(1, 7):
        dispatch = [{"bess_id": spec["bess_id"], "p_mw": sign * step * 0.25} for spec in config["bess"]]
        validate_dispatch(dispatch, metadata)
        trial = copy.deepcopy(net)
        apply_bess_dispatch(trial, dispatch, metadata)
        ok, failure = run_locked_power_flow(trial, config["solver"])
        final = state_metrics(trial, metadata, converged=ok, error=failure)
        if ok and final["voltage_violation_count"] == 0:
            witness = dispatch
            break
    if witness is None:
        return None
    return {"index": index, "load_scale": load_scale, "pv": pv, "initial": initial, "witness": witness}


def generate(seed: int, num_candidates: int, num_dev: int, num_test: int, root: Path, config_path: Path) -> dict:
    root = root.resolve()
    # A directory name 'private' in a public checkout is not an access boundary.
    if root == REPO_ROOT or REPO_ROOT in root.parents:
        raise ValueError("output-dir must be outside PowerAgentBench (agent-visible checkout)")
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"output-dir must be empty: {root}")
    if num_candidates <= 0 or num_test <= 0 or num_dev < 0 or num_test % 6 or num_dev % 6:
        raise ValueError("candidate count must be positive; test/dev sizes must be multiples of six")
    config = load_benchmark_config(config_path)
    rng = random.Random(seed)
    pools = {"UNDERVOLTAGE": [], "OVERVOLTAGE": []}
    for index in range(num_candidates):
        item = candidate(rng, config, index)
        if item:
            pools[item["initial"]["condition"]].append(item)
    per_bin_dev, per_bin_test = num_dev // 6, num_test // 6
    chosen = {"dev": [], "test": []}
    for kind, pool in pools.items():
        pool.sort(key=lambda c: (c["initial"]["voltage_violation_magnitude"], c["index"]))
        needed = 3 * (per_bin_dev + per_bin_test)
        if len(pool) < needed:
            raise ValueError(f"only {len(pool)} feasible {kind} candidates; need {needed}; increase --num-candidates")
        # Spread the selected examples across the measured severity range, rather
        # than classifying difficulty from the load/PV generation parameters.
        selected = [pool[(i * len(pool) + len(pool) // 2) // needed] for i in range(needed)]
        for level, segment in zip(("easy", "medium", "hard"), (selected[i:i + needed // 3] for i in range(0, needed, needed // 3))):
            for offset, item in enumerate(segment):
                chosen["dev" if offset < per_bin_dev else "test"].append((kind, level, item))
    config_hash = sha256_file(config_path)
    manifests = {}
    witnesses = []
    for split in ("dev", "test"):
        entries = []
        for number, (kind, level, item) in enumerate(chosen[split], 1):
            scenario_id = f"{split[0].upper()}{number:04d}"
            net = build_ieee33_network(load_scale=item["load_scale"], pv_injections=item["pv"], bess_specs=config["bess"])
            full = root / split / "full" / f"{scenario_id}.json"
            public = root / split / "public" / f"{scenario_id}.json"
            write_pandapower_json(net, full)
            write_json(public, {
                "scenario_id": scenario_id,
                "network": {
                    "name": "IEEE 33-bus distribution feeder", "n_bus": len(net.bus), "n_line": len(net.line),
                    "branches": [{"line_id": int(i), "from_bus": int(row.from_bus), "to_bus": int(row.to_bus), "in_service": bool(row.in_service)} for i, row in net.line.iterrows()],
                    "loads": [{"load_id": int(i), "bus": int(row.bus), "p_mw": float(row.p_mw), "q_mvar": float(row.q_mvar)} for i, row in net.load.iterrows()],
                },
                "voltage_limits_pu": config["voltage_limits_pu"], "line_loading_percent_max": config["line_loading_percent_max"],
                "bess": config["bess"], "initial_state": item["initial"],
            })
            entry = {
                "scenario_id": scenario_id, "condition": kind, "difficulty": level,
                "generation_seed": seed, "candidate_index": item["index"],
                "load_scale": item["load_scale"], "pv_injections": item["pv"],
                "severity": item["initial"]["voltage_violation_magnitude"],
                "voltage_violation_count": item["initial"]["voltage_violation_count"],
                "full_path": f"full/{scenario_id}.json", "public_path": f"public/{scenario_id}.json",
                "full_sha256": sha256_file(full), "public_sha256": sha256_file(public),
                "benchmark_config_sha256": config_hash, "dataset_version": config["dataset_version"],
            }
            entries.append(entry)
            witnesses.append({"split": split, "scenario_id": scenario_id, "dispatch": item["witness"]})
        manifest = {"dataset_version": config["dataset_version"], "benchmark_config_sha256": config_hash, "scenarios": entries}
        write_json(root / split / "manifest.json", manifest)
        manifests[split] = sha256_file(root / split / "manifest.json")
    # Independent replay from disk catches serialization / sign mistakes.
    for row in witnesses:
        result = evaluate_voltage_dispatch(row["scenario_id"], row["dispatch"], scenario_root=root / row["split"], config_path=config_path)
        if result["success"] != 1.0:
            raise RuntimeError(f"witness replay failed: {row['scenario_id']}: {result}")
    write_json(root / "evaluator_private" / "witnesses.json", witnesses)
    corpus = {"dataset_version": config["dataset_version"], "seed": seed, "num_candidates": num_candidates, "num_dev": num_dev, "num_test": num_test, "benchmark_config_sha256": config_hash, "split_manifest_sha256": manifests, "witnesses_sha256": sha256_file(root / "evaluator_private" / "witnesses.json")}
    corpus["dataset_sha256"] = hashlib.sha256(json.dumps(corpus, sort_keys=True).encode()).hexdigest()
    write_json(root / "corpus_manifest.json", corpus)
    return corpus


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--num-candidates", type=int, default=600)
    parser.add_argument("--num-dev", type=int, default=24)
    parser.add_argument("--num-test", type=int, default=96)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args()
    print(json.dumps(generate(args.seed, args.num_candidates, args.num_dev, args.num_test, args.output_dir, args.config.resolve()), indent=2))


if __name__ == "__main__":
    main()
