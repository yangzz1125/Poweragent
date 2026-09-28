# Spatial corpus v2 candidate: acceptance record

Status: generated and independently verified; **not frozen**, not official Test results.

## Reproduce

From `PowerAgentBench/`, choose a new, empty evaluator-only directory outside the workspace:

```powershell
.venv/Scripts/python.exe scripts/generate_voltage_corpus.py --seed 2029 --num-candidates 300 --num-dev 24 --num-test 96 --output-dir E:/work/voltage_corpus_v2_candidate
```

`generator_version=spatial-coordinate-v2`. `dataset_version=ieee33-bess-voltage-v1` remains the existing loader/physical schema identifier, not the corpus revision. Dataset identity is the corpus SHA plus generator version, not that schema label alone.

Corpus SHA: `8642cae21141b22af062eb47d6c4fc8b9aeec9a981246678e1be3e05148545c3`.

The old `E:/work/voltage_corpus_v1` was not modified. Hidden artifacts remain outside Git; an arbitrary filesystem-enabled agent still requires separate OS isolation.

## Changes and limits

- Alternate under/over sampling profiles from the Dev study, including per-load spatial multipliers and varied PV buses/powers. BESS bounds, steps and success criterion unchanged.
- Replace the six-uniform-action feasibility filter with bounded coordinate search from zero, considering each BESS independently in both directions, up to 48 improving steps. It may miss feasible joint moves; no witness found is **not** an infeasibility proof.
- Search uses in-memory copies for speed, with the same locked PF and dispatch validation. Selected witnesses are then **independently replayed from serialized frozen snapshots** through the evaluator.
- Preserve candidate outcome audit (including unresolved cases), protocol/config/generator hashes and per-witness search PF counts. Do not exclude cases based on baseline failures/success rates.
- Each under/over pool is severity-stratified and assigned to Dev/Test using a separate seeded shuffle within each stratum. No low-severity-prefix Dev assignment.

## Acceptance

300 candidates: 203 found witnesses, 79 search-unresolved, 18 rejected initial states. Selected 120 scenarios; all selected witnesses independently replayed successfully.

- Dev: 4 per under/over × easy/medium/hard cell = 24.
- Test candidate: 16 per cell = 96.
- `python -m pytest -q tests`: **30 passed**, including nonuniform-action search, manifest/witness checks, split metadata, and existing tool/API regression.

Dev scripted baseline results (not LLM and not Test):

| Baseline | Success | Mean PF calls including final replay (`n_power_flows`) |
|---|---:|---:|
| No-action | 0/24 | 1.00 |
| Nearest-BESS greedy | 22/24 | 17.08 |
| Voltage-sensitivity greedy | 24/24 | 78.67 |

Results at `PowerAgentBench/results/voltage_control/dev_baselines_v2/` (git-ignored).

**Remaining search-method bias:** coordinate witness search and sensitivity baseline both perform local voltage-violation descent. Therefore sensitivity 100% is not independent evidence of broad benchmark coverage. The result establishes feasibility of selected tasks, not minimum effort or optimality, and not LLM difficulty. Severity bins are physical exceedance bins only. Do not tune sampling to force sensitivity failures.

## Next gate

Run bounded Dev LLM diagnostics on a new output directory and the v2 Dev root; establish whether I/V/R yields meaningful differences, validate compact observations, costs and parse errors. Keep Test outcomes unseen. Complete protocol/metric/runner review before freezing; do not create `benchmark-v1.0` yet.
