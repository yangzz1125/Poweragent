# Solvers and diagnostics

## Contents
- [Solver compatibility](#solver-compatibility)
- [Detecting availability](#detecting-availability)
- [Interpreting termination](#interpreting-termination)
- [Diagnosing infeasibility](#diagnosing-infeasibility-in-order)
- [Non-convergence and numerical trouble](#non-convergence-and-numerical-trouble)
- [Solver success with an invalid result](#solver-success-with-an-invalid-result)

## Solver compatibility
potpourri bundles no solvers. Match the solver to the problem class, not to
habit.

| Formulation | Class | Works | Does not work |
|---|---|---|---|
| `DCOPF`, linear costs | LP | GLPK, CBC, HiGHS, Gurobi, CPLEX | — |
| `DCOPF`, quadratic costs (`cp2 != 0`) | QP | Gurobi, CPLEX, IPOPT | GLPK, CBC (use `add_poly_cost_objective(..., allow_quadratic=False)` to fail loudly instead) |
| `ACOPF`, `ACOPF_multi_period` | nonconvex NLP | IPOPT | GLPK, CBC — they cannot represent the sin/cos power flow |
| discrete taps, `qu_deadband` | MINLP | `gurobi_direct_minlp`, MindtPy | IPOPT alone |
| `HC_ACOPF` | MINLP with binaries | `gurobi_direct_minlp` | plain `gurobi`/`gurobi_direct`/`gurobi_persistent` raise `DegreeError` on the AC power flow |

Notes that matter in practice:
- **`time_limit` is ignored by IPOPT, GLPK and CBC.** Only MindtPy and the
  `gurobi*` interfaces honour it. For IPOPT, bound the work with
  `max_iter` instead. Never promise a wall-clock bound you cannot enforce.
- **MindtPy is a driver, not a solver.** It needs an NLP sub-solver (IPOPT) and a
  MIP sub-solver (`mip_solver="glpk"|"cbc"|"gurobi"`). Its outer approximation is
  only globally valid for convex MINLP; on the nonconvex AC OPF it returns a
  local solution and often terminates `feasible` rather than `optimal`.
- **`gurobi_direct_minlp`** needs Pyomo ≥ 6.10 and gurobipy ≥ 12, and runs a
  global spatial branch-and-bound. On a continuous AC OPF it finds the same
  optimum as IPOPT but spends the remaining budget proving global optimality — so
  prefer IPOPT until integers appear.
- **NEOS** (`solver="neos"`, `neos_opt="ipopt"`) needs the `NEOS_EMAIL`
  environment variable and makes a network call. Do not use it in an automated or
  offline run.

## Detecting availability
Check before building the model. potpourri raises a bare
`RuntimeError("Attempting to use an unavailable solver")` from inside `solve()`,
after the whole Pyomo model has been constructed — an expensive way to learn that
GLPK is missing.

```python
import pyomo.environ as pyo
pyo.SolverFactory("ipopt").available(exception_flag=False)   # -> bool
```

Two practical wrinkles: the ASL-backed solvers (`bonmin`, `couenne`) print a
traceback to stderr even with `exception_flag=False`, so silence stderr when
probing or a routine check looks like a crash; and Pyomo finds solvers on `PATH`,
so a conda environment's solvers are invisible to a different interpreter unless
its `bin` directory is on `PATH`. `scripts/solve_opf.py --list-solvers` handles
both.

## Interpreting termination
Never infer success from the absence of an exception, and never read `net.res_*`
before checking termination — the constructor's `pp.runpp` already filled those
tables, so a failed solve leaves plausible-looking base-case numbers in place.

```python
import pyomo.environ as pyo
ok = pyo.check_optimal_termination(results)
results.solver.status                  # ok | warning | error | aborted
results.solver.termination_condition   # optimal | infeasible | maxIterations | other | ...
```

| Condition | What it means | What to say |
|---|---|---|
| `optimal` | KKT satisfied to tolerance | "locally optimal" for AC/NLP; "optimal" for LP |
| `infeasible` | no feasible point found | a **model** problem: constraints, bounds or data |
| `unbounded` | objective improves without limit | missing bound, usually on the slack or a controllable device |
| `maxIterations` | iteration cap hit | incumbent is not proven; may not even be feasible |
| `maxTimeLimit` | time cap hit | incumbent feasible but not proven optimal |
| `other` | solver-specific stop | IPOPT reports this for restoration failure and for contradictory bounds — treat as failure |
| `feasible` | MindtPy found a point | feasible, **not** optimal |

Two observed IPOPT behaviours on this package worth remembering: a genuinely
over-tight thermal limit yields `status=warning, termination_condition=infeasible`,
whereas a `min_vm_pu > max_vm_pu` contradiction yields
`status=warning, termination_condition=other`. So `other` does not exclude a
trivial data contradiction — check bounds before believing a numerical story.

**Optimality claims.** The AC OPF is nonconvex. IPOPT returning `optimal` means a
locally optimal point satisfying the KKT conditions, nothing more. Only a global
solver (`gurobi_direct_minlp`) reporting `optimal` — not `maxTimeLimit` —
justifies the word "global".

## Diagnosing infeasibility, in order
Work cheapest and most-likely-first. Do **not** start by deleting constraints:
removing the voltage band to "fix" an infeasible OPF converts a real operating
problem into a fictitious clean result.

1. **Topology and reference.** Run `scripts/inspect_case.py`. Unsupplied buses, no
   in-service `ext_grid` or slack `gen`, or several reference buses when you
   expected one. Without a reference bus the angle reference is undetermined.
2. **Contradictory bounds.** `min_vm_pu > max_vm_pu`, `min_p_mw > max_p_mw`,
   `min_q_mvar > max_q_mvar`. Cheap to test, common, and reported as `other`
   rather than `infeasible`. Also check that fixed setpoints lie inside their own
   bounds — a non-controllable sgen at `p_mw > max_p_mw` starts outside the
   feasible set.
3. **Load-generation balance.** Can the external grid actually supply or absorb
   the imbalance? `ext_grid.min_p_mw`/`max_p_mw` left at a narrow default is a
   frequent cause. Compare total load against total generation capability.
4. **Voltage bounds.** Tighten from wide to intended: solve at [0.90, 1.10], then
   [0.95, 1.05]. If only the tight band fails, the problem is physical, and that
   is a `voltage-violation-mitigation` finding rather than a modelling bug. Note
   that with `free_slack_vm=True` an *unreachable-looking* band may still be
   feasible because the slack lifts the whole network into it.
5. **Reactive capability.** Are `min_q_mvar`/`max_q_mvar` set on the external grid
   and generators? An AC OPF with no reactive headroom at the feed-in point is
   frequently infeasible for reasons that look like voltage problems. Check
   whether `inverter_s2`, `cos_phi_min`, or `fixed_cos_phi` is pinning Q harder
   than intended — `fixed_cos_phi` is an equality.
6. **Branch and transformer limits.** Compare the base-case loadings from
   `inspect_case.py` against the configured ratings: a rating below the existing
   base-case flow cannot be met by dispatch alone. Also check for lines with
   missing `max_i_ka` (unbounded) and transformers with zero `sn_mva` (limit 0).
7. **Storage boundary conditions.** Single-period: `soc_percent`, `max_e_mwh`,
   `efficiency_percent` present and sane; `STOR_dt` is 0.25 h. Multi-period: the
   first step is pinned to `BAT_SOC_init`, so an initial SOC outside
   `[soc_min, soc_max]` makes step 1 infeasible against later steps' bounds.
8. **Time-coupled constraints.** Ramp or tap-rate limits
   (`max_tap_change_per_step`) that cannot follow the profile; a horizon crossing
   a profile boundary; `toT` beyond the profile length.
9. **Discrete decisions.** If integers are present, relax them first
   (`add_tap_changer_linear` instead of `_discrete`, or drop `qu_deadband`). If
   the relaxation is feasible and the integer problem is not, the infeasibility is
   integrality, not physics. A `qu_deadband` whose characteristic leaves the Q(P)
   capability area is a known infeasibility source and potpourri warns about it
   (`QuCurveOutsidePqAreaWarning`) — read those warnings.
10. **Objective and scaling.** Confirm the objective is defined for the model
    (a DC model has no `v`), and that no term is astronomically larger than the
    rest. An unbounded direction shows up as `unbounded`, not `infeasible`.

Report which step resolved it. "Infeasible because transformer 0 is rated
0.16 MVA and the pinned PV export needs 0.36 MVA" is a finding; "infeasible" is
not.

## Non-convergence and numerical trouble
Distinguish "no feasible point exists" (steps 1-9 above) from "the solver could
not get there".

Symptoms of the second: `maxIterations`, `other` with a restoration-failure
message, wildly different answers from tiny input changes, or an objective that
plateaus far from any bound.

- **Initialisation.** potpourri warm-starts from the constructor's `pp.runpp`
  result, so a poor or non-converged base power flow poisons the OPF start. Fix
  the base case first — this is why `inspect_case.py` runs it.
- **Scaling.** Everything internal is p.u. on `net.sn_mva`. SimBench LV networks
  use `sn_mva = 1.0`, so a 6 kW battery is 0.006 p.u. and quantities of 1e-5 mix
  with limits of order 1. Widely separated magnitudes are what IPOPT struggles
  with; prefer a `sn_mva` of the same order as the network's real ratings.
- **Near-zero impedances.** A line with `r + x ≈ 0` behaves as a short and makes
  the AC Jacobian ill-conditioned. Model it as a bus-bus switch — potpourri
  merges closed zero-impedance switches for exactly this reason.
- **Degenerate bounds.** `sPGmin == sPGmax` is handled with an epsilon-padded
  bound rather than a hard fix, deliberately: fixing the variable makes Pyomo's NL
  writer eliminate it and can drive IPOPT into `TOO_FEW_DEGREES_OF_FREEDOM`.
  Avoid pinning variables by hand for the same reason.
- **Iteration cap.** Raise it with `max_iter=...` (mapped to IPOPT's `max_iter`).
  If more iterations help, it was conditioning; if not, revisit the constraints.
- **Multi-period size.** If a 96-step model stalls, reproduce on 4-8 steps. A
  setup error appears at 4 steps; a genuine scaling limit does not.

## Solver success with an invalid result
The most dangerous outcome: `termination_condition=optimal` and a physically
wrong answer. Always run the checks in `VALIDATION_GUIDE.md`. The recurring causes
in potpourri specifically:

- Reading `net.res_*` after a non-optimal solve and getting the **base case**.
- Reading `net.res_*` after a **multi-period** solve, which never writes them.
- Reading `net.res_bus.vm_pu` after a **DC** solve and getting a flat 1.0.
- Treating multi-period battery SOC as an economic dispatch when the model has no
  round-trip loss and no terminal-SOC condition.
- Accepting a voltage-deviation optimum that quietly curtailed all renewable
  generation.
- Believing a thermal result on a line whose `max_i_ka` is missing, where the
  constraint was never enforced.
