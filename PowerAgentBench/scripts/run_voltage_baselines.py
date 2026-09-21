from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from poweragentbench.voltage_agentic import (
    NearestBESSGreedyAgent,
    NoActionVoltageAgent,
    VoltageSensitivityGreedyAgent,
    aggregate_voltage_metrics,
    score_voltage_output,
)
from poweragentbench.voltage_case import DEFAULT_SCENARIO_ROOT, scenario_ids


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    flat = [
        {
            key: value
            for key, value in row.items()
            if not isinstance(value, (dict, list))
        }
        for row in rows
    ]
    keys = list(dict.fromkeys(key for row in flat for key in row))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(flat)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run scripted voltage-control baselines."
    )
    parser.add_argument("--scenario-root", type=Path, default=DEFAULT_SCENARIO_ROOT)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("results/voltage_control")
    )
    args = parser.parse_args()
    agents = [
        NoActionVoltageAgent(),
        NearestBESSGreedyAgent(scenario_root=args.scenario_root),
        VoltageSensitivityGreedyAgent(scenario_root=args.scenario_root),
    ]
    rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    attempts_path = args.output_dir / "baseline_attempts.jsonl"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with attempts_path.open("w", encoding="utf-8") as attempts:
        for agent in agents:
            agent_rows = []
            for scenario_id in scenario_ids(args.scenario_root):
                output = agent.run(scenario_id)
                metrics = score_voltage_output(
                    scenario_id, output, scenario_root=args.scenario_root
                )
                agent_rows.append(metrics)
                rows.append(metrics)
                attempts.write(
                    json.dumps(
                        {
                            "agent": output.name,
                            "scenario_id": scenario_id,
                            "dispatch": output.dispatch,
                        }
                    )
                    + "\n"
                )
            summaries.append(aggregate_voltage_metrics(agent_rows))
    write_csv(args.output_dir / "baseline_per_case.csv", rows)
    write_csv(args.output_dir / "baseline_summary.csv", summaries)
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
