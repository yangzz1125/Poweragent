# IEEE 33-bus BESS voltage-control research contract (draft; not frozen)

## Research questions

A 2×2×2 factorial comparison tests domain-specific interface (I), execution-grounded preview verification (V), and failure-aware resubmission (R). Conditions I0-V0-R0 through I1-V1-R1 use the same scenarios, model, temperature, evaluator and budgets. The domain interface *preprocesses* the raw observation; it is not claimed information-equivalent. Report success and absolute success-rate differences alongside costs and interactions.

## Task and evaluator

For each frozen IEEE 33-bus snapshot, choose a BESS active-power dispatch with 4 BESS at buses 8, 17, 24, 32; each is bounded at ±1.5 MW in 0.25 MW steps. Positive benchmark `p_mw` injects power, negative withdraws it (pandapower storage uses the opposite sign). A successful episode must converge under the locked solver and put **every** bus in [0.95, 1.05] pu. The independent evaluator reloads the frozen full snapshot, checks ID/bounds/steps, reapplies the action and reruns power flow. It never accepts an agent's claimed success or substitutes an earlier successful submission for a final failure. Thermal loading is diagnostic, not a success criterion.

Maximum 12 LLM turns, 4 preview calls (if V enabled), 3 formal submissions (if R enabled; otherwise stop at the first). The evaluator runs in all eight conditions. Count actual power flows separately from evaluator calls: invalid dispatches can be rejected before a power flow.

## Dataset and leakage

The original eight `ieee33` cases remain regression/sanity examples, not the main corpus. Generate 24 Dev and 96 Test with `scripts/generate_voltage_corpus.py`. Seeded load scaling, PV placement and PV injections vary; BESS and solver are fixed. Accept only converged snapshots with one type of initial voltage violation and an independently replayed legal feasible dispatch. Severity is the sum of voltage exceedances; within each under/over condition, select spread-out candidates by severity and label thirds easy/medium/hard. Dev has 4 and Test 16 per condition×difficulty. This is a severity-based stratification, **not** a proof of LLM difficulty.

Keep the corpus in an evaluator-only filesystem **outside any agent sandbox**; `--output-dir` refuses paths inside PowerAgentBench and refuses nonempty directories to avoid overwriting data. The generated split directories contain `full/`, `public/`, `manifest.json`; `evaluator_private/witnesses.json` is evaluator-only. Agents get only the public card and allowed tool replies, not filesystem access to the corpus, evaluator process, hidden manifest fields or code that can read evaluator-only paths. Merely placing private data outside the git checkout is **not** a security boundary when the agent has arbitrary shell/filesystem access: deploy a separate sandbox/container or an API boundary before testing coding agents. The existing tracked regression `ieee33/private/` is not a hidden test set.

Each split manifest hashes its public/full JSON and the benchmark configuration. The corpus manifest records seed, sizes, split-manifest hashes, witness hash and a canonical metadata digest (`dataset_sha256`). Do not expose evaluator-only manifest or witnesses to an agent. Hashes detect accidental mutation; they are not secrecy or tamper-proof signatures. Do not regenerate or tune on Test after freeze.

## Metrics and experiment sequence

Per episode: final success, valid action, first-submit success, recovered after initial failure, initial/final violation count and magnitude, action L1 MW, LLM turns, preview/submit/evaluator calls, actual power flows, input/output/total tokens and latency. Record provider/model, scenario/difficulty, condition, repeat, prompt/config/dataset hashes, commit, temperature and budgets. Pilot all 8 conditions on Dev first; repair any tooling issues **before** locking prompt, tools, dataset, evaluation and budgets and tagging `benchmark-v1.0`. Only then run 96 Test × 8 × 3 repeats with one primary model. Add cross-model checks, bootstrap 95% CIs, absolute effects, factorial interaction analysis, difficulty and reliability–cost breakdown, figures and tables. No pilot/main experiment or benchmark freeze is claimed in this draft.

## Corpus generation

From `PowerAgentBench/` (with its environment installed):

```bash
.venv/Scripts/python.exe scripts/generate_voltage_corpus.py --seed 2026 --num-candidates 600 --num-dev 24 --num-test 96 --output-dir E:/work/voltage_corpus_v1
.venv/Scripts/python.exe -m pytest tests/test_voltage_corpus.py
```

Choose an output directory inaccessible to the tested agent. A different environment or pandapower version may change power-flow results; record dependency versions before freeze. If not enough feasible candidates exist, increase `--num-candidates`, not the BESS bounds or success criterion.

## Current acceptance (pre-freeze)

- P0: research contract recorded here; **draft**, not frozen.
- P1/P2: seed 2026, 600 candidates generated 24 Dev + 96 Test at `E:/work/voltage_corpus_v1`; Test contains exactly 16 per condition×difficulty, Dev exactly 4; every selected witness independently replayed and succeeded. Corpus metadata digest: `c2e21bc02c58ef09f9dfda7db1f0bc7307481691b185f7b91fe0dc1790bd3335`.
- Regression: `python -m pytest -q tests/test_voltage_corpus.py tests/test_voltage_agentic.py tests/test_voltage_evaluator.py tests/test_voltage_tools.py` passed (13 tests).
- P3 (hosted LLM only): verified across all eight conditions that outgoing model messages/tool replies contain no full-case paths, witness references or hidden generation metadata; tool exceptions fail closed rather than being echoed to the model, and malformed JSON gets a generic error. Run the **model API runner only**, with no agent-executable shell, Python, file-read or arbitrary tool. The runner/evaluator process holds the full cases; only the JSON prompt and explicitly allowed tool replies go to the model. This is a message-boundary check, not an OS security boundary.
- P3 (Coding Agent): **not accepted**. `E:/work/voltage_corpus_v1` is readable by any agent with host filesystem access. Deploy the coding agent in a distinct container/VM with no mounts to the corpus, evaluator code, regression witnesses or host credentials; expose only a narrow, authenticated case-summary/inspect/preview/submit service running in the evaluator environment. The agent must not choose `scenario_root` or read evaluator logs. Verify from inside the sandbox that full/test/witness files cannot be opened before scoring. Docker is installed locally but its daemon was unavailable when checked, so no filesystem isolation claim is made.
- P4 client (offline): OpenAI-compatible Chat Completions client added alongside Responses; API refuses unsupported temperature instead of silently changing it. LLM turns sum per-call reported token usage and record elapsed time; missing usage stays NULL. Mock client checks pass. No live endpoint tested yet.
- P4 call ledger (offline): preview requests, budgeted preview, submit and evaluator calls, and actual locked PF runs now counted separately; invalid dispatch counts no PF. Final independent replay is included. No-submit is not a valid submitted action. Telemetry regression passes; no live usage validation yet.
- P5 offline: 8-condition Dev/Test dry-runs report 192/2304 planned episodes; mock runner validates unique keys, fixed CSV schema and explicit error retry. Dev scripted baselines (24 cases): no-action 0/24, nearest-BESS greedy 24/24, sensitivity-greedy 24/24. **Ceiling-effect warning:** Dev is easy for scripted greedy. Before freeze, evaluate this as a limitation using Dev pilot; do not adjust Test based on its results or claim strong difficulty merely from severity bins.
- Offline P10/P11 preparation: `scripts/analyze_voltage_experiments.py` generates scenario-cluster bootstrap CIs, paired factor differences, factorial logit (or separation warning), Figures 1–6 and Tables 1–4. Mock-data test only; no real analysis claims. Full offline suite previously passed (24 tests including 8-condition × 2-repeat mock execution).
- P6 **Responses smoke only**, not pilot: user supplied DeepSeek official API `.env`; default API mode changed to `responses` for all conditions. On one Dev D0005, I0-V0-R0, max 6 turns: success=1, 5 LLM turns, 1 submit, 2 actual PF, input/output tokens=21093/6328, total=27421, latency=35.7 s; tool sequence included one parse error. No 8-condition smoke or full Dev pilot yet. Results at git-ignored `results/voltage_control/responses_smoke/`; no Test used. Protocol choice alone does not prove Responses is more reliable than Chat. P7–P12 pending.

## Latest: explicit model settings and freeze-contract checks

DeepSeek Responses now sends explicit reasoning.effort=high (the documented provider default) with max_output_tokens=16384. Thinking ignores requested temperature=0; the runner records that limitation. A separate one-case Dev check succeeded for ¥0.01251810; it does not replace the original Pilot. Full contract validation now covers source/environment/model/pricing/analysis/planned tasks, requires explicit approval and a matching clean tag before Test, and can emit only an unapproved candidate offline. Absolute factorial interaction contrasts now have scenario-paired bootstrap CIs. **92 offline tests passed.** See [engineering acceptance](EXPLICIT_REASONING_AND_FREEZE.md). Formal tag/Main approval remain separate; provider alias drift and witness-search selection bias remain acknowledged limitations.

## Earlier: CNY Dev Pilot complete, freeze not approved

Full v2 Dev Pilot completed: **192/192**, 170 successes, 22 task failures, no missing episodes. All 985 HTTP attempts were off-peak. Known estimated fees ¥2.67079106 plus five user-approved unknown-charge reserves ¥1.00 consumed ¥3.67079106 of ¥10. Completed ledger totals reconcile. Full offline suite: **61 passed**. Public snapshot: `research_records/voltage_control/cny_pilot_192/` (Dev-only; no hidden Test/witnesses).

See [Pilot progress](CNY_PILOT_PROGRESS.md) and [pre-freeze review](PILOT_PREFREEZE_REVIEW.md). One R1 failure repeatedly emitted empty visible text with output_tokens=4096; output-cap truncation must be investigated on Dev, not simply classified as inability to format JSON. Model settings, full freeze gate and interaction uncertainty remain pending. No benchmark tag/Main authorization implied. Earlier sections below preserve historical acceptance stages.

## CNY campaign implementation (new protocol)

Approved limits: ¥0.20 per episode, ¥10 across all development calls/Pilot, smoke stage ¥1 included. Request-level Decimal/cache accounting, off-peak checks on retries, shared durable campaign ledger, paid-response/checkpoint recovery and behavioral analysis are implemented. **59 offline tests passed.** See [measurement contract](RMB_MEASUREMENT_SPEC.md) and [behavior analysis](RMB_BEHAVIOR_ANALYSIS.md). At the 2026-09-28 afternoon preflight the real runner paused before any HTTP call: ¥0, 0 requests, next window 18:00 UTC+8. New-schema paid smoke/Pilot are not yet complete; no scheduled wake is installed.

## v2 live Dev smoke update

Responses on v2 D0005 has completed 8/8 conditions (6 final successes), with preview and recovery paths exercised. Recorded total usage 164961 tokens; the last episode completed after an authorized continuation with a 150000-token episode-boundary soft gate. This is 8/192 planned Dev episodes, not a complete Pilot. New-run provenance (root commit/source SHA), seeded condition ordering and planned-task coverage checks have since been added; do not mix old smoke with the new runner. See [`V2_RESPONSES_SMOKE.md`](V2_RESPONSES_SMOKE.md) for raw summary and confirmed pre-freeze gaps (nested-repo commit, dirty-source identity, fixed condition order, incomplete failure usage, analysis coverage and freeze checks). No Test run performed.

## v2 candidate update (not frozen)

The generator now uses spatial load/PV sampling and bounded nonuniform coordinate search, with seeded within-stratum splitting. A separate 24/96 candidate corpus was generated and every witness independently replayed. New Dev baselines: nearest 22/24, sensitivity 24/24. See [`CORPUS_V2_CANDIDATE.md`](CORPUS_V2_CANDIDATE.md) for hashes, counts, search limits and reproduction. Existing v1 data untouched. The following review describes the **old v1** filter; broader search still introduces search-method selection bias, not a completeness guarantee.

## Historical v1 corpus review (freeze remains pending)

Dev greedy success alone does not establish LLM difficulty. More importantly, `generate_voltage_corpus.py::candidate` only retains cases solvable by one of six uniform same-direction BESS dispatches: this is explicit selection bias. Current 24/96 data is a **development candidate corpus**, not validated paper Test. Severity thirds describe voltage exceedance, not control difficulty. Within each bin the current split also assigns the low-severity prefix to Dev; a revised generator should use a seeded within-stratum split instead.

Do not overwrite the current corpus or select Test cases for low baseline success. Before any freeze, use Dev-only studies to define broader spatial load/PV sampling and discrete witness search independent of the uniform heuristic, document search failures/budgets, compare fixed one-shot and simulator-guided strategies with their PF costs, then generate a separate version under a predeclared protocol. This methodological work is **pending**, not fixed by relabeling existing cases.

Dev-only follow-up: [`DEV_DIFFICULTY_AUDIT.md`](DEV_DIFFICULTY_AUDIT.md) reports a separate 40-candidate spatial-load/PV study: 34 converged violations, 21 uniform successes, 29 independent greedy witnesses; 8 search successes had no uniform solution. Existing corpus untouched. This demonstrates the selection bias but does not complete a balanced replacement corpus or establish LLM difficulty.

## Compact observation change (pre-freeze)

`inspect_voltage_state` no longer embeds the static network or BESS capability table. Those remain available through `case_summary` and `get_bess_capabilities` in every condition. No voltage values, constraints or evaluator verdicts change. For V0001, serialized inspection observation shrank from 6551 to 1044 bytes (generic) and 6144 to 637 bytes (domain). These are JSON byte counts, not measured API-token savings. Full stateless conversation history is still sent. Use a new output directory for the changed tool interface; do not merge old smoke episodes with new Pilot data. Full voltage test directory: **27 passed** after the change.

## Next gate: Dev difficulty review and hosted API Pilot

Copy `PowerAgentBench/.env.example` to `PowerAgentBench/.env` (git-ignored) and replace `YOUR_DEEPSEEK_API_KEY`. The template uses DeepSeek's official base URL (`https://api.deepseek.com`) and `deepseek-flash` model ID. The runner appends `/responses` for the selected `responses` mode (or `/chat/completions` for `chat`). This project's Dev pilot uses Responses for every condition; keep that mode fixed at freeze and during Test. Do not paste keys into chat or commit them. Before paid Pilot runs, provide an explicit token/price limit or permission. From `PowerAgentBench/`, verify the task count *without* an API call:

```bash
.venv/Scripts/python.exe -m scripts.run_voltage_experiment_matrix --split dev --scenario-root E:/work/voltage_corpus_v1/dev --dry-run
```

After authorization, run a bounded `--max-episodes 8` smoke, then full Dev pilot. The runner resumes with the same output directory, but failure episodes require explicit `--retry-errors`. Token/cost gates are soft at the episode boundary and may overshoot by one episode. Paid Test is blocked until Pilot, freeze and budget checks succeed.
