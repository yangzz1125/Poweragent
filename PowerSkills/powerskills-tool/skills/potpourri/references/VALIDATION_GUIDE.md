# Validating and reporting a potpourri result

A solver returning `optimal` says the KKT conditions hold for the model you
built. It says nothing about whether that model was the one you meant. Run these
checks before presenting any number.

## 0. Confirm you are looking at the solution
This is the first check because it is the one that silently fails.

```python
import pyomo.environ as pyo
assert pyo.check_optimal_termination(results)      # else net.res_* is the BASE CASE
```

`net.res_*` is populated by the model constructor's `pp.runpp`, so it is never
empty. When a solve is not optimal, potpourri skips its mapping and leaves those
base-case values in place — plausible numbers that are not your answer.

For **multi-period** models `solve(to_net=True)` never writes `net.res_*` at all,
so the values there are always the constructor's base case unless you map
explicitly:

```python
from potpourri.models_multi_period.pyo_to_net_multi_period import pyo_sol_to_net_res
for t in opf.model.T:
    pyo_sol_to_net_res(opf.net, opf.model, t)
    ...   # read what you need now; the next call overwrites net.res_*
```

A quick way to prove you are reading the solution: compare `net.res_bus.vm_pu`
against `pyo.value(opf.model.v[b, t])` for a couple of buses. They must match to
solver tolerance.

## 1. Power balance
Generation minus load minus losses must close.

```python
gen = res_ext_grid.p_mw.sum() + res_gen.p_mw.sum() + res_sgen.p_mw.sum()
load = res_load.p_mw.sum() + res_storage.p_mw.sum()
losses = res_line.pl_mw.sum() + res_trafo.pl_mw.sum()
residual = gen - load - losses          # expect |residual| / throughput < 1e-3
```

Expect near machine precision on a converged AC solve (observed ~1e-17 MW on the
bundled LV feeder). For DC, exclude losses — the formulation is lossless, and
including them produces a fake residual equal to the losses.

A residual that does not close after an `optimal` termination usually means the
extraction is wrong, not the solve: the wrong time step, a stale mapping, or
double-counting storage as both generation and load.

## 2. Voltage constraints (AC only)
Compare solved `vm_pu` against the band you configured, not a remembered default.

- Report the extrema **with their bus indices**: `min 0.9975 pu at bus 14`.
- A value sitting exactly on `min_vm_pu` or `max_vm_pu` is a **binding**
  constraint, not a violation — say which it is.
- A value outside the band after `optimal` termination means the constraint was
  not applied to that bus. potpourri applies voltage bounds over `model.Bpd`, the
  ppc buses that a pandapower bus maps onto; auxiliary buses inserted by
  switch handling have no user limits and their voltage follows from the
  equations.
- Never quote a voltage from a DC run: `vm_pu` is a flat 1.0 placeholder.

## 3. Thermal constraints
Compare `res_line.loading_percent` and `res_trafo.loading_percent` against the
`max_loading_percent` you set, and name the element.

Verify the limit actually exists before concluding "no congestion": a line with
missing or zero `max_i_ka` receives an effectively unbounded limit, and unrated
`net.impedance` branches get 1e6 MVA. Congestion cannot appear on an unconstrained
branch. `scripts/inspect_case.py` flags both.

Remember which branch-limit form you used. `thermal_limit="current"` enforces
`|S|² ≤ SLmax²·v²`, so the admissible apparent power falls with voltage;
`"mva"` enforces a constant-MVA limit. The two give different results and
`loading_percent` is computed by pandapower's own convention, not by the model's.

## 4. Active and reactive power limits
- Controllable sgens must satisfy `min_p_mw ≤ p_mw ≤ max_p_mw` — but note that in
  a **multi-period** model `min_p_mw` is ignored and the effective lower bound is
  0.
- External-grid P and Q must lie inside `min/max_p_mw` and `min/max_q_mvar`. If
  you left these at a wide default (1e4), the OPF had effectively unlimited
  support at the feed-in point, which makes almost anything feasible. Say so.
- Where `inverter_s2=True`, check `p² + q² ≤ sn_mva²` per sgen.
- Where `cos_phi_min` or `fixed_cos_phi` is set, check the achieved power factor.
  `fixed_cos_phi` is an equality, so an exact match is expected, not a bound.

## 5. Curtailment
Curtailment is the difference between what was available and what was dispatched,
and the reference differs by model kind:

- **Single period**: available is `net.sgen.max_p_mw` (which you set from the
  snapshot's `p_mw`), dispatched is `net.res_sgen.p_mw`.
- **Multi-period**: available is `model.PsG[g, t]` (the profile value) and
  dispatched is `model.psG[g, t]`, both p.u. on `baseMVA`. `net.sgen.max_p_mw`
  holds only the static snapshot and is the wrong reference here.

Always report it next to the objective value. A voltage-deviation or
reactive-power objective assigns no value to energy, so 100 % curtailment can be
"optimal" — on the bundled LV feeder at a high-PV snapshot it is. Curtailment
above ~5 % of available energy is an `operations-planning-mitigation` finding.

## 6. Storage
**Single period** (`net.storage` → `STOR_*`): check `SOC` inside
`[STOR_SOCmin, STOR_SOCmax]`, the inverter circle `pSTOR² + qSTOR² ≤ Pmax²`, and
explicitly check for **simultaneous charge and discharge**. The true
complementarity `Pchg · Pdis = 0` is relaxed to `Pchg + Pdis ≤ Pmax`, so the
optimiser can split a little power between both legs to skim the round-trip loss.
Both being non-zero is a modelling artefact, not a dispatch instruction.

**Multi-period** (`Battery_multi_period` → `BAT_*`): one signed `BAT_P`, so
simultaneous charge/discharge is impossible by construction. Check:
- `BAT_SOC` within `[soc_min, soc_max]` on every step after the first;
- the first step equals `BAT_SOC_init` (it is pinned, and is *not* bounded by the
  SOC window, so an out-of-window initial SOC is a setup error);
- the terminal SOC, which is **unconstrained** — a battery that ends empty has
  exported stored energy for free over the horizon. If the study is economic, that
  invalidates it; add your own terminal constraint or interpret accordingly;
- that you are not claiming losses: because a single signed power is multiplied by
  the efficiency, a charge/discharge cycle returns exactly to its starting SOC, so
  the effective round-trip efficiency is 100 % regardless of `efficiency`.

Energy over the horizon is `Σ P · deltaT` with `deltaT` fixed at 0.25 h.

## 7. Binding constraints
Identify which limits the solution sits on, at an explicit tolerance (1e-4 pu for
voltage, ~0.5 % for loading). Binding constraints are the engineering content of
an OPF result: they name the physical bottleneck and tell you what to relieve.

Distinguish clearly:
- **binding** — at the limit; the limit is shaping the answer;
- **violated** — beyond the limit; either the constraint was not applied, or you
  are reading a non-optimal or base-case result;
- **slack** — away from the limit; that constraint is not the bottleneck.

If nothing binds, the objective was limited by something other than network
limits — often the controllable range itself, or nothing at all, in which case
question whether the study was posed correctly.

## 8. Cross-validation against pandapower
For an AC OPF, the model's own physics can be checked independently:

1. Take the OPF dispatch (`res_sgen.p_mw`/`q_mvar`, `res_gen`, storage).
2. Write it into a fresh copy of the network as fixed setpoints.
3. Run `pp.runpp`.
4. Compare bus voltages and branch loadings against the OPF result.

Agreement to a few 1e-4 pu confirms the Pyomo AC formulation and the extraction
are consistent with pandapower's Newton-Raphson. Disagreement means one of the
two is wrong — usually a units or per-unit error in the extraction. In the
upstream potpourri repository (not bundled here),
`validate_ac_model_against_pandapower.py` does this across six SimBench networks
and `pglib_benchmark.py` validates objectives against the PGLib-OPF published
reference values.

For a DC OPF, compare against `pp.rundcpp`, and expect the active-power flows to
agree while nothing about voltage does.

Beware the weak-evidence trap: DC and AC active-power results usually agree
closely because the gap is essentially the losses. That agreement does not
validate any AC voltage or reactive conclusion.

## 9. Reporting checklist
State each of these, with units, or say why it does not apply:

- [ ] Network source, size (buses/lines/trafos/sgens/loads), and `baseMVA`.
- [ ] Study type and formulation (AC or DC, single or multi-period).
- [ ] Horizon and resolution (steps × 0.25 h) for multi-period.
- [ ] Active constraint groups and the limits configured (voltage band, ratings,
      controllability, whether curtailment was permitted).
- [ ] Objective, and what its value means in units — including "no economic
      interpretation" where that is the truth.
- [ ] Solver used, which solvers were available, and the solver's own
      `status` / `termination_condition`.
- [ ] "Locally optimal" for any AC/NLP result; "optimal" only for an LP or a
      global solver that proved it.
- [ ] Power-balance residual.
- [ ] Voltage extrema with bus indices (AC only), and the configured band.
- [ ] Worst line and transformer loading with element indices, against their
      configured ratings.
- [ ] Dispatch by group: external grid P/Q, gen, sgen, load, storage.
- [ ] Curtailment in MW or MWh and as a percentage of available.
- [ ] Storage power and SOC extrema, plus the modelling caveats above.
- [ ] Binding constraints, separated from violations.
- [ ] Cross-validation performed, or an explicit note that it was not.
- [ ] Limitations: DC assumptions, local optimality, unenforced limits, storage
      caveats, ignored `min_p_mw` in multi-period.
- [ ] Escalation with the numbers behind it, or an explicit "none triggered".

Distinguish input limits from solved values throughout. "Bus 14 at 0.9975 pu
against a configured 0.95 pu minimum" is reportable; "voltage is fine" is not.
