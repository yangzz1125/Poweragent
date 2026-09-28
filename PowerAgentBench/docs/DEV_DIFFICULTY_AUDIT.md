# Dev-only difficulty audit: seed 2027

## Purpose and protocol

Diagnose the old generator's uniform-dispatch acceptance bias without accessing Test performance or changing its artifacts. Script: `scripts/audit_voltage_difficulty.py`; use an empty evaluator-only directory outside the workspace.

Before execution, the script writes `protocol.json` containing sampling ranges, seed, configuration hash, generator hash and pandapower version. All 40 candidates remain in manifest/CSV, including normal snapshots and unresolved searches. BESS positions, limits, steps and evaluator success criterion are unchanged.

Sampling: load scale [0.6,1.8], independent per-load P/Q multiplier [0.3,2.5], 0–4 PV units on sampled buses 5–32, each [0.3,3.5] MW. These are exploratory distribution choices, not a proposed frozen benchmark distribution. Uniform comparison exhausts 12 equal-power dispatches (all BESS ±0.25 through ±1.5 MW); this is simulator-guided, **not** a one-shot policy. The independent search reuses `VoltageSensitivityGreedyAgent(max_steps=48)` from zero, ignoring uniform outcomes. Every reported search success is independently replayed from disk. Search failure does not prove physical infeasibility; witness effort is not minimum required effort.

## Observed results

Command from `PowerAgentBench/`:

```powershell
.venv/Scripts/python.exe scripts/audit_voltage_difficulty.py --seed 2027 --num-candidates 40 --output-dir E:/work/voltage_difficulty_dev_2027
```

| Initial condition | Candidates | Uniform success | Search success |
|---|---:|---:|---:|
| Undervoltage | 30 | 19 | 25 |
| Overvoltage | 3 | 2 | 3 |
| Mixed (exploratory only) | 1 | 0 | 1 |
| Normal | 6 | not evaluated | not evaluated |

Of 34 converged violation cases, 21 had a uniform solution and 29 had a search witness. **Eight were solvable by nonuniform search but not by any of the twelve uniform trials** (six under, one over, one mixed). Five were unresolved by both methods. No candidate was deleted based on a baseline outcome.

This establishes that uniform-only filtering excludes some feasible tasks. It does not establish LLM difficulty, a desired baseline success rate, or exhaustive infeasibility of unresolved cases. The new sampling is strongly under-voltage skewed (30 vs 3) and is not ready for a balanced corpus. The one mixed case is not silently incorporated into the original under/over factorial experiment.

Artifacts: `E:/work/voltage_difficulty_dev_2027/` contains protocol, full/public snapshots, manifests, per-candidate CSV including separate uniform/search PF counts, summary and evaluator-only search witnesses. Not uploaded to GitHub. Existing `E:/work/voltage_corpus_v1` was not modified.

## Second Dev study: stratified sampling, seed 2028

Added `--profile stratified`: alternate 20 under-oriented and 20 over-oriented **generation** recipes, without guaranteeing outcome labels or resampling failures. Under: load [0.7,1.5], per-load multiplier [0.3,2.5], 0–2 PV [0.1,0.8] MW. Over: load [0.3,0.8], multiplier [0.5,1.5], 2–4 PV [1.2,3.5] MW at buses 10–32. BESS remains unchanged. Protocol is written before execution.

Added fixed one-shot ±0.5 MW per BESS (sign from measured under/over condition), separately counted as one PF. Record final witness voltage margin; this is not optimized control margin or minimum effort.

```powershell
.venv/Scripts/python.exe scripts/audit_voltage_difficulty.py --seed 2028 --num-candidates 40 --profile stratified --output-dir E:/work/voltage_difficulty_dev_2028_stratified
```

| Measured condition | Candidates | One-shot success | Uniform search success | Nonuniform search success |
|---|---:|---:|---:|---:|
| Under | 20 | 3 | 16 | 16 |
| Over | 17 | 5 | 8 | 12 |
| Normal | 3 | not evaluated | not evaluated | not evaluated |

37 violation candidates: one-shot 8/37, uniform 24/37, nonuniform search 28/37; four search witnesses absent from uniform trials, nine unresolved by either. Nonuniform search averaged 95.24 PF evaluations (including final replay), so its success rate cannot be compared to one-shot without showing cost. Overvoltage coverage improved to 17 cases, but these counts are **not** a balanced frozen dataset or an LLM result.

The command hit its 600-second execution timeout after 39 completed candidates. A0040 was completed from its already written snapshot using exactly the same 12 uniform trials and 48-step search, without resampling; summary records this recovery. The audit script itself still refuses nonempty output directories (no automatic resume).

The existing corpus generator now shuffles each severity stratum with a separate deterministic RNG before allocating Dev/Test; newly generated manifests include `split_policy=seeded-within-severity-stratum-v2` and the generator hash. **Existing v1 artifacts were not regenerated.** Its uniform-only witness filter still exists, so it must not be used to freeze the replacement corpus yet. A replacement generator must adopt the reviewed broader sampling and witness protocol first.

## Still required before a replacement corpus

- Predeclare sampling strata with adequate overvoltage coverage using Dev-only evidence.
- Review the added one-shot strategy and witness-margin diagnostics; compare costs rather than only success rates.
- Choose bounded broader witness search and record unresolved cases without calling them infeasible.
- Validate the new seeded within-stratum allocation on a replacement corpus; generate a **new version/directory**, preserve existing corpus and hashes.
- Reverify witness/hash completeness, balanced split, then run the new Dev Pilot before any freeze.

Regression: `tests/test_voltage_difficulty.py` checks candidate retention, PF trial counts, independent witness replay and overwrite refusal. No paid model API called during this study.
