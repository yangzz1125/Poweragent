"""Export an immutable, Dev-only analysis snapshot without credentials or hidden cases."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path

from poweragentbench.voltage_costs import read_events, ledger_totals


def export_run(run_dir: Path, campaign_dir: Path, target: Path) -> dict:
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    if run.get("split") != "dev":
        raise ValueError("only Dev runs may be published by this exporter")
    if target.exists():
        raise ValueError("snapshot target must not exist")
    # Explicit allowlist: never copy .env, checkpoint messages, raw API payloads,
    # full scenarios or evaluator_private witnesses.
    rows = list(csv.DictReader((run_dir / "episodes.csv").open(encoding="utf-8")))
    events = read_events(run_dir / "events.jsonl")
    requests = read_events(campaign_dir / "requests.jsonl")
    # The campaign spans several Dev runs. Publish its sanitized usage ledger
    # intact so reservations and the cumulative budget remain reconstructible.
    dev_runs = {run["run_id"]}
    for path in run_dir.parent.glob("*/run.json"):
        metadata = json.loads(path.read_text(encoding="utf-8"))
        if metadata.get("split") == "dev":
            dev_runs.add(metadata["run_id"])
    public_requests = []
    for event in requests:
        if event.get("context", {}).get("run_id") not in dev_runs:
            raise ValueError("campaign includes unverified/non-Dev requests; publication refused")
        public_requests.append({k: v for k, v in event.items() if k not in ("visible_text",)})
    totals = ledger_totals(campaign_dir / "requests.jsonl")
    artifact = {
        "run.json": json.dumps(run, indent=2),
        "episodes.csv": (run_dir / "episodes.csv").read_text(encoding="utf-8"),
        "events.jsonl": "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events),
        "requests.jsonl": "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in public_requests),
        "campaign.json": (campaign_dir / "campaign.json").read_text(encoding="utf-8"),
        "pricing_snapshot.json": (campaign_dir / "pricing_snapshot.json").read_text(encoding="utf-8"),
    }
    for name in ("reservations.jsonl", "reservation_policy.json"):
        if (campaign_dir / name).exists():
            artifact[name] = (campaign_dir / name).read_text(encoding="utf-8")
    if (run_dir / "metadata_migrations.jsonl").exists():
        artifact["metadata_migrations.jsonl"] = (run_dir / "metadata_migrations.jsonl").read_text(encoding="utf-8")
    complete = [row for row in rows if row["status"] == "complete"]
    summary = {"split": "dev", "run_id": run["run_id"], "planned": len(run["planned_tasks"]),
               "complete": len(complete), "success": sum(float(row["success"]) == 1 for row in complete),
               "paused": sum(row["status"] == "paused" for row in rows), "errors": sum(row["status"] == "error" for row in rows),
               "not_started": len(run["planned_tasks"]) - len(rows), "campaign": totals,
               "scope": "Dev diagnostic snapshot; not frozen Test or paper results. Unknown charges are not zero."}
    artifact["summary.json"] = json.dumps(summary, indent=2)
    artifact["README.md"] = """# Dev experiment records for independent analysis

This immutable snapshot is exported from the local run. Read `summary.json` first.
`run.json` contains the full planned task set; `episodes.csv` is the active episode
summary. `events.jsonl` contains model-visible commands/tool feedback (no hidden
reasoning); `requests.jsonl` contains sanitized per-request usage and timing for the entire
shared Dev campaign (possibly multiple run IDs), so the campaign budget and
reserves can be reconstructed. Filter its context.run_id for this run's costs.

Missing/paused episodes are not physical failures. Do not select only successful
rows or treat conditions with different completion counts as a controlled result.
`source_sha256` may differ between pre/post approved accounting-only migrations;
see `metadata_migrations.jsonl`. Old rows were not retrospectively relabeled.

CNY amounts are usage-based estimates or conservative bounds, NOT invoices.
`reservations.jsonl` preserves explicitly authorized unknown-charge reserves;
reserves consume the campaign budget but are not claimed to be actual charges.
Only Dev results are exported. No `.env`, auth headers, raw provider payloads,
checkpoint files, hidden Test scenarios, or feasibility witnesses are included.

For analysis (from the PowerAgentBench directory):

```bash
python -m scripts.analyze_voltage_trajectories --run-dir SNAPSHOT_DIR --campaign-dir SNAPSHOT_DIR --output-dir LOCAL_ANALYSIS_DIR
```

Run main aggregate analysis only when the planned task set is complete, or use
`--allow-incomplete` and label it exploratory. Report scenario-cluster uncertainty,
first-submit failure denominators and all missing/censored outcomes. A Dev Pilot
cannot be used as a frozen Test claim. Do not feed these records to evaluated agents.
"""
    secret = os.environ.get("POWERAGENTBENCH_OPENAI_API_KEY")
    for name, text in artifact.items():
        if secret and secret in text:
            raise ValueError(f"secret detected in {name}; export aborted")
        if '"Authorization"' in text or '"api_key"' in text or '"full_path"' in text:
            raise ValueError(f"sensitive field detected in {name}; export aborted")
    target.mkdir(parents=True)
    for name, text in artifact.items():
        (target / name).write_text(text, encoding="utf-8", newline="\n")
    hashes = {name: hashlib.sha256((target / name).read_bytes()).hexdigest() for name in artifact}
    (target / "SHA256.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8", newline="\n")
    return summary


def main():
    from scripts.run_voltage_agent_eval import load_env_file
    load_env_file(Path(".env"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export_run(args.run_dir, args.campaign_dir, args.output_dir), indent=2))


if __name__ == "__main__":
    main()
