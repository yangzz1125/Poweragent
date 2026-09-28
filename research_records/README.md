# Published research records

These are explicitly authorized **Dev-only** snapshots for independent/cloud-agent analysis.
They are not frozen Test data and must not be fed to evaluated agents.

## Current snapshot

- [`voltage_control/cny_pilot_066/`](voltage_control/cny_pilot_066/README.md): 66/192 completed Dev episodes, 61 successful, 1 paused, 125 not started.
- Known usage-based cost: CNY 0.81203662; two unknown-charge reserves total CNY 0.40; campaign budget consumed CNY 1.21203662 of the approved CNY 10.
- Reserves are precautionary, **not confirmed provider charges**. Errors and missing outcomes are retained.

Read `summary.json`, `run.json`, `episodes.csv`, `events.jsonl`, `requests.jsonl`, `reservations.jsonl`, and `metadata_migrations.jsonl` together. `SHA256.json` identifies exported file bytes. Later snapshots supersede progress counts but do not erase earlier evidence.

No API keys, environment files, checkpoints, hidden full/Test cases, or reference witnesses are included. Model commands and tool observations for Dev are intentionally published. Keep analysis outputs separate from original snapshots.

The local runner is supervised under per-episode CNY 0.20 and campaign CNY 10 limits, off-peak only. Connection resets caused earlier manual pauses; the user subsequently authorized CNY 0.20 reserves for unknown charges and continued bounded retry under the same total cap. This is an accounting-policy change during development, not a frozen benchmark protocol.
