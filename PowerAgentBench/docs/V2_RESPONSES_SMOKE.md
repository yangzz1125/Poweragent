# v2 Responses Dev smoke: 8 conditions, not a full Pilot

Model: DeepSeek official `deepseek-flash`, Responses. Corpus SHA: `8642cae21141b22af062eb47d6c4fc8b9aeec9a981246678e1be3e05148545c3`. Scenario D0005, medium-severity Dev case. Same 12-turn / 4-preview / 3-submission budgets across conditions (disabled tools/recovery terminate as specified). Local results: `results/voltage_control/v2_responses_compact_smoke/`.

| Condition | Final success | First-submit success | Recovered | Turns | Preview | Submit | Actual PF | Total tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| I0-V0-R0 | 0 | 0 | 0 | 4 | 0 | 1 | 2 | 12459 |
| I0-V0-R1 | 1 | 0 | 1 | 5 | 0 | 2 | 3 | 18461 |
| I0-V1-R0 | 1 | 1 | 0 | 6 | 2 | 1 | 4 | 19078 |
| I0-V1-R1 | 1 | 1 | 0 | 6 | 2 | 1 | 4 | 19813 |
| I1-V0-R0 | 0 | 0 | 0 | 4 | 0 | 1 | 2 | 10575 |
| I1-V0-R1 | 1 | 0 | 1 | 5 | 0 | 2 | 3 | 14599 |
| I1-V1-R0 | 1 | 1 | 0 | 6 | 2 | 1 | 4 | 18641 |
| I1-V1-R1 | 1 | 1 | 0 | 7 | 3 | 1 | 5 | 51335 |

8 episodes, 6 final successes, 0 logged API errors, no parse_error in their saved tool traces. Completed-episode usage totals **164961 tokens**; last condition alone used 51335. Aggregate recorded episode elapsed time ~107.20 seconds, excluding time paused or interrupted in-flight requests.

The first continuation stopped at the 100000-token episode-boundary soft gate (113626 reported). With user authorization to continue, the cap was raised to 150000 and exactly one final episode completed, overshooting the soft gate to 164961. No further API calls were made. Prior interrupted/in-flight requests may have unreported provider charges. This completes one eight-condition smoke, not the 192-episode Pilot or an exact invoice. No Test scenario was used.

## Interpretation

On this single case, recovery repaired initial failures and preview preceded successful first submissions. This validates those control paths only; it is not evidence of statistically significant I/V/R effects or model superiority. No pooled 5/7 success-rate claim belongs in a paper. Conditions were split across sessions/provider time slots; latency comparisons would be confounded. Old corpus/old observation smoke is not an appropriate matched token comparison.

## Confirmed pre-freeze gaps

1. Generator uses coordinate-search witnesses; sensitivity baseline shares that search family. Its 24/24 Dev success is not independent coverage evidence. Severity strata are not validated control-difficulty strata.
2. Runner commit is obtained inside the nested PowerAgentBench repository: this run records `e6ecb37118195f536d09ea6ef308516ac6e2c05b`, not root workspace commit `71be47e25d1bd47f3f693cf84f49972c6aea49a7`. Dirty source files also lack a source-bundle hash. Keep this smoke as debug; fix provenance before any official run, not by silently rewriting old records.
3. `ordered_tasks` shuffles cases but keeps conditions in fixed order. Predeclare seeded condition randomization/counterbalancing before Pilot; prices, caching and load can affect cost/latency comparisons. Requests may be repeated at temperature 0.
4. Partial-failure episodes do not retain preceding successful turns' usage, and current cost gate accounts completed episodes. Improve failure accounting, unknown usage handling and per-request audit before claiming exact costs.
5. Analysis completeness is inferred from observed CSV cases/repeats. Entire missing cases can go unnoticed. Validate against planned task manifest, fix the error/missing-episode denominator policy, and obtain scenario-cluster uncertainty for interactions before paper-level claims. Current logit coefficients have no clustered intervals.
6. Freeze gate checks dataset/prompt/config but not the full tool/evaluator source, dependency environment or model settings. Complete a frozen identity contract before Test.

After the smoke, code fixes addressed #2 for **new runs** (root-workspace commit plus source-file SHA including dirty Python/configuration source), randomized the per-case condition order reproducibly (#3), and stored the full planned task list so analysis detects entire missing cases (#5 coverage). Resume rejects changed source; existing smoke metadata is preserved, not retroactively altered. Six targeted runner/analysis tests passed. Failure-cost accounting, complete freeze validation and clustered interaction uncertainty are still pending. Existing smoke must not be resumed under the changed runner; use a new output directory for future Pilot.

The 2×2×2 design and independent replay success criterion remain appropriate. These gaps block freezing, not further bounded Dev diagnostics. Next: finish failure-cost accounting and freeze checks, then 24×8 Dev Pilot under a separate explicit limit, with no Test-driven tuning.
