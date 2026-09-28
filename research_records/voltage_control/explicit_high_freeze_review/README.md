# Dev experiment records for independent analysis

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
