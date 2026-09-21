# Surge Solver Guide

Every OPF, SCOPF, and dispatch tool accepts `lp_solver` / `nlp_solver`
strings. Solvers are detected at runtime.

## Default (auto-detect)

Pass `"default"` or omit the argument:

| Role | Priority order |
| --- | --- |
| LP / MIP | Gurobi → COPT → CPLEX → HiGHS |
| NLP (AC-OPF / SCOPF) | COPT (if shim built) → Ipopt |

HiGHS (LP) and Ipopt (NLP) are the baseline fallback.

## Explicit selection

Pass `lp_solver="highs"` when:

- Open-source deployment (no commercial license).
- Reproducible / controlled baselines.
- LP-only problems (DC-OPF, SCED) or small MIPs (≤ 10 k integer vars).

Avoid forcing HiGHS on:

- Large SCUC MIPs — Gurobi's presolve typically wins 2–10×.
- Branch-switching / topology MIPs with hundreds of binaries, unless
  the user explicitly wants an open-source run.

Pass `nlp_solver="ipopt"` for reproducibility or open-source AC-OPF
runs. Ipopt is the default when no shimmed commercial NLP is available.

Pass `lp_solver="gurobi"` for large SCUC / OTS MIPs or timed benchmark
runs. COPT and CPLEX are runtime plugins picked up automatically by
the default path; force them only for benchmark isolation.

## Decision tree

```
User specified a solver?
├── yes → pass it through
└── no
    ├── LP / small MIP  → lp_solver="default"
    ├── large SCUC / OTS MIP → lp_solver="default"  (prefers Gurobi)
    └── NLP → nlp_solver="default"  (Ipopt fallback)
```

## Install

| Variable | Purpose |
| --- | --- |
| `HIGHS_LIB_DIR` | Path to `libhighs.{so,dylib}` if not on system path. |
| `IPOPT_LIB_DIR` | Path to `libipopt.{so,dylib}` (macOS Homebrew requires this). |
| `GUROBI_HOME` | Gurobi install root. |
| `COPT_HOME` | COPT install root. |
| `CPLEX_HOME` | CPLEX install root. |

Open-source install: `brew install highs ipopt` or `apt install
libhighs-dev coinor-libipopt-dev`. Verify this before debugging
commercial-solver errors.

## Summary

- When in doubt, omit `lp_solver` / `nlp_solver`.
- User says "HiGHS" → `lp_solver="highs"`.
- User says "I have Gurobi" → `lp_solver="gurobi"` for MIPs.
- Missing solver is a deployment issue, not a Surge capability issue.
