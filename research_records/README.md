# Published research records

These are explicitly authorized **Dev-only** snapshots for independent/cloud-agent analysis.
They are not frozen Test data and must not be fed to evaluated agents.

## Current snapshot

**Cloud review entry point:** [项目进度与审阅问题](../PowerAgentBench/docs/CLOUD_REVIEW_HANDOFF_ZH.md). Read this before comparing snapshots: the original Pilot and later explicit-high/16384 diagnostics use different request settings. Main is not authorized; no new experiments are requested by this handoff.

- Latest structural audit: [`voltage_control/dev_structural_coverage/`](voltage_control/dev_structural_coverage/README.md). All 24 Dev cases have a feasible {-1.5,0,+1.5} MW combination; 19 are solved by a fixed uniform bisection policy with at most 3 observed PF queries, 4 additional cases have single-BESS solutions, and 1 requires a multi-BESS coarse template among these tested families. Template existence is an exhaustive oracle coverage result, NOT a fair 4-query controller score. 3168 local PF calls, zero API cost, no Test changes.

- New physical difficulty study: [`voltage_control/dev_action_landscape_2030/`](voltage_control/dev_action_landscape_2030/README.md). 24 Dev cases, 19838 local PF evaluations, no model API calls. Median sampled feasible fraction: full grid 3.71%, correct-sign grid 21.88%. Exact correct-sign enumeration for three sparse cases finds 9/2401, 1/2401 and 51/2401 feasible actions, yet all three admit the obvious all-BESS-full-discharge solution and were solved by both no-feedback LLM conditions. This distinguishes physical tightness from reasoning difficulty. Only per-case summaries/protocols are published, not private sampled dispatches or witnesses.

- Latest engineering check: [`voltage_control/explicit_high_freeze_review/`](voltage_control/explicit_high_freeze_review/README.md): explicit high/16384 Dev diagnosis succeeded, CNY 0.01251810; includes the model-settings/environment identity and scenario-paired absolute interaction contrasts from the existing Pilot. Formal freeze/tag/Main remain unapproved. Campaign known estimates + reserves now total CNY 3.69531226/10.

- New focused check: [`voltage_control/output_limit_16384_diagnostic/`](voltage_control/output_limit_16384_diagnostic/README.md), D0015/I1-V0-R1 only, successful with 5 turns and 2 submits; CNY 0.01200310. All provider statuses completed; largest output 987 tokens, so this does **not** prove that raising the cap caused the improvement. This row is not merged into the 192-episode Pilot. The sanitized requests ledger covers the shared Dev campaign for budget reconciliation.

- **Latest: [`voltage_control/cny_pilot_192/`](voltage_control/cny_pilot_192/README.md)**: all 192/192 Dev episodes complete, 170 successful, 22 task failures; no missing/paused episodes. Includes `analysis/` CSVs and figures plus `environment.txt`.
- Known usage-based cost: **CNY 2.67079106**; five unknown-charge reserves total **CNY 1.00**; campaign budget consumed **CNY 3.67079106** of the approved CNY 10. All 985 HTTP attempts were off-peak; 5 ConnectionResetErrors were retained and resumed/retried.
- Earlier snapshot: [`voltage_control/cny_pilot_066/`](voltage_control/cny_pilot_066/README.md), retained as progress evidence.
- Reserves are precautionary, **not confirmed provider charges**. Errors and missing outcomes are retained.

Read `summary.json`, `run.json`, `episodes.csv`, `events.jsonl`, `requests.jsonl`, `reservations.jsonl`, and `metadata_migrations.jsonl` together. `SHA256.json` identifies exported file bytes. Later snapshots supersede progress counts but do not erase earlier evidence.

No API keys, environment files, checkpoints, hidden full/Test cases, or reference witnesses are included. Model commands and tool observations for Dev are intentionally published. Keep analysis outputs separate from original snapshots.

Per-condition success (24 cases each): I0-V0-R0 14; I0-V0-R1 24; I0-V1-R0 24; I0-V1-R1 24; I1-V0-R0 13; I1-V0-R1 23; I1-V1-R0 24; I1-V1-R1 24. These are **Dev-only, one repeat** diagnostics, not frozen Test claims. Several cells are separated (all-success), so logistic coefficients are not estimable; do not fabricate p-values. The 22 R1 first-submit failures include 21 recovered episodes, a selected descriptive denominator, not a causal recovery effect.

The local runner is supervised under per-episode CNY 0.20 and campaign CNY 10 limits, off-peak only. Connection resets caused earlier manual pauses; the user subsequently authorized CNY 0.20 reserves for unknown charges and continued bounded retry under the same total cap. This is an accounting-policy change during development, not a frozen benchmark protocol.
