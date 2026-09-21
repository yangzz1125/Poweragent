from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from poweragentbench.voltage_agentic import VoltageSensitivityGreedyAgent
from poweragentbench.voltage_case import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_SCENARIO_ROOT,
    build_ieee33_network,
    load_benchmark_config,
    sha256_file,
    write_pandapower_json,
)
from poweragentbench.voltage_evaluator import (
    evaluate_voltage_dispatch,
    run_locked_power_flow,
    state_metrics,
)

RECIPES = (
    {"scenario_id": "V0001", "load_scale": 0.70, "pv": []},
    {"scenario_id": "V0002", "load_scale": 0.85, "pv": []},
    {"scenario_id": "V0003", "load_scale": 1.00, "pv": []},
    {"scenario_id": "V0004", "load_scale": 1.15, "pv": []},
    {"scenario_id": "V0005", "load_scale": 0.40, "pv": [(17, 1.5), (32, 1.5)]},
    {"scenario_id": "V0006", "load_scale": 0.50, "pv": [(17, 2.0), (32, 2.0)]},
    {"scenario_id": "V0007", "load_scale": 0.60, "pv": [(17, 2.5), (32, 2.5)]},
    {
        "scenario_id": "V0008",
        "load_scale": 0.70,
        "pv": [(17, 2.0), (32, 2.0), (24, 0.75)],
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build and verify frozen IEEE 33-bus voltage scenarios."
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_SCENARIO_ROOT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    return parser.parse_args()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> None:
    args = parse_args()
    config = load_benchmark_config(args.config)
    root = args.output_dir
    (root / "full").mkdir(parents=True, exist_ok=True)
    (root / "public").mkdir(parents=True, exist_ok=True)
    (root / "private").mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []

    for recipe in RECIPES:
        scenario_id = recipe["scenario_id"]
        net = build_ieee33_network(
            load_scale=recipe["load_scale"],
            pv_injections=recipe["pv"],
            bess_specs=config["bess"],
        )
        converged, error = run_locked_power_flow(net, config["solver"])
        metadata_stub = {
            "voltage_limits_pu": config["voltage_limits_pu"],
            "line_loading_percent_max": config["line_loading_percent_max"],
        }
        initial = state_metrics(net, metadata_stub, converged=converged, error=error)
        if not converged or initial["voltage_violation_count"] == 0:
            raise RuntimeError(
                f"{scenario_id} is not a converged voltage-violation case"
            )
        condition = "UNDERVOLTAGE" if initial["undervoltage_buses"] else "OVERVOLTAGE"
        initial["condition"] = condition
        full_path = root / "full" / f"{scenario_id}.json"
        public_path = root / "public" / f"{scenario_id}.json"
        write_pandapower_json(net, full_path)
        branches = [
            {
                "line_id": int(index),
                "from_bus": int(row.from_bus),
                "to_bus": int(row.to_bus),
                "in_service": bool(row.in_service),
            }
            for index, row in net.line.iterrows()
        ]
        loads = [
            {
                "load_id": int(index),
                "bus": int(row.bus),
                "p_mw": float(row.p_mw),
                "q_mvar": float(row.q_mvar),
            }
            for index, row in net.load.iterrows()
        ]
        public = {
            "scenario_id": scenario_id,
            "network": {
                "name": "IEEE 33-bus distribution feeder",
                "n_bus": len(net.bus),
                "n_line": len(net.line),
                "branches": branches,
                "loads": loads,
            },
            "voltage_limits_pu": config["voltage_limits_pu"],
            "line_loading_percent_max": config["line_loading_percent_max"],
            "bess": config["bess"],
            "initial_state": initial,
        }
        write_json(public_path, public)
        entries.append(
            {
                "scenario_id": scenario_id,
                "condition": condition,
                "full_path": f"full/{scenario_id}.json",
                "public_path": f"public/{scenario_id}.json",
                "full_sha256": sha256_file(full_path),
                "public_sha256": sha256_file(public_path),
            }
        )

    manifest = {
        "dataset_version": config["dataset_version"],
        "benchmark_config_sha256": sha256_file(args.config),
        "scenarios": entries,
    }
    write_json(root / "manifest.json", manifest)

    witness_agent = VoltageSensitivityGreedyAgent(
        max_steps=48, scenario_root=root, config_path=args.config
    )
    witnesses = []
    for entry in entries:
        output = witness_agent.run(entry["scenario_id"])
        report = evaluate_voltage_dispatch(
            entry["scenario_id"],
            output.dispatch,
            scenario_root=root,
            config_path=args.config,
        )
        if report["success"] != 1.0:
            raise RuntimeError(
                f"no valid witness found for {entry['scenario_id']}: {report}"
            )
        witnesses.append(
            {"scenario_id": entry["scenario_id"], "dispatch": output.dispatch}
        )
    write_json(root / "private" / "witnesses.json", witnesses)
    manifest["witnesses_sha256"] = sha256_file(root / "private" / "witnesses.json")
    write_json(root / "manifest.json", manifest)
    print(
        json.dumps({"scenario_count": len(entries), "output_dir": str(root)}, indent=2)
    )


if __name__ == "__main__":
    main()
