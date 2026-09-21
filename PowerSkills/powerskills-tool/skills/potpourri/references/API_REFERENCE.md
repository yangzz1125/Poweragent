# potpourri API reference

Verified against `opf-potpourri` 0.4.x source. Every name below exists; nothing
here is inferred from the README, which is wrong in a few places (see
[Documentation traps](#documentation-traps)).

## Contents
- [Import paths](#import-paths)
- [Single-period models](#single-period-models)
- [`ACOPF.add_OPF` options](#acopfadd_opf-options)
- [Objectives](#objectives)
- [Multi-period models](#multi-period-models)
- [Flexible devices](#flexible-devices)
- [Solving](#solving)
- [Reading results](#reading-results)
- [Network preparation and controllability](#network-preparation-and-controllability)
- [Not supported](#not-supported)
- [Documentation traps](#documentation-traps)

## Import paths
There is no flat public namespace: `potpourri` itself exports only
`__version__`. Import from the module that defines the class.

```python
from potpourri.models.ACOPF_base import ACOPF
from potpourri.models.DCOPF import DCOPF
from potpourri.models.HC_ACOPF import HC_ACOPF
from potpourri.models.cost_objective import add_poly_cost_objective
from potpourri.models_multi_period.ACOPF_multi_period import ACOPF_multi_period
from potpourri.models_multi_period.DCOPF_multi_period import DCOPF_multi_period
from potpourri.models_multi_period.pyo_to_net_multi_period import (
    pyo_sol_to_net_res,
)
from potpourri.technologies.battery import Battery_multi_period
from potpourri.benchmarks.pglib import load_pglib_case
```

`potpourri.__version__` reads `0.3.0` even in the 0.4.x releases — it is stale.
Use `importlib.metadata.version("opf-potpourri")` if the version matters.

## Single-period models
| Class | Formulation | Notes |
|---|---|---|
| `ACOPF(net)` | `AC` + `OPF` | full polar AC power flow, voltages and reactive power |
| `DCOPF(net)` | `DC` + `OPF` | linearised, lossless, no voltage magnitude |
| `HC_ACOPF(net)` | `ACOPF` + binaries | hosting capacity; MINLP, needs a global or decomposition solver |

The constructor does real work and mutates nothing you own: it deep-copies the
network, merges closed zero-impedance bus-bus switches, **reindexes buses from
0**, and runs `pp.runpp`. So `opf.net` is not your `net`, and model bus numbers
are ppc bus numbers, not necessarily your `net.bus` indices.

Standard sequence — the order matters, `add_OPF()` is what unfixes the
controllable variables and installs the limits:

```python
opf = ACOPF(net)
opf.add_OPF(thermal_limit="current")
opf.add_voltage_deviation_objective()
results = opf.solve(solver="ipopt", print_solver_output=False)
```

## `ACOPF.add_OPF` options
All keyword-only in practice; every one verified in the signature.

| Option | Default | Meaning |
|---|---|---|
| `thermal_limit` | `"current"` | `"current"`: `|S|² ≤ SLmax²·v²` (physical for distribution conductors). `"mva"`: `|S|² ≤ SLmax²` (MATPOWER/PGLib convention). Changes results — state which you used. |
| `free_slack_vm` | `True` | Slack voltage **magnitude** floats within `[Vmin, Vmax]`; the reference angle stays fixed. Set `False` to pin it to the base case. |
| `fix_hv_buses` | `False` | Pin `vm` on every bus at `hv_bus_kv`. |
| `hv_bus_kv` | `110.0` | Level used by `fix_hv_buses`. |
| `angle_limits` | `False` | Enforce `angmin_degree`/`angmax_degree` branch angle limits. |
| `pv_q_control` | `None` | VDE-AR-N Q-control for PV-type sgens with `var_q` set: `"qp"`, `"qu"`, `"both"`/`True`. |
| `inverter_s2` | `False` | Adds `psG² + qsG² ≤ S_inv²` for controllable sgens with finite `sn_mva`. |
| `cos_phi_min` | `None` | Power-factor cone `|qsG| ≤ psG·tan(acos(cos_phi_min))`. Only active with `inverter_s2=True`. |
| `pu_curtail` | `False` | P(U) active-power curtailment above a voltage threshold. |
| `fixed_cos_phi` | `None` | Power-factor **equality**. |
| `cos_phi_p_profile` | `False` | cos(φ)(P) profile as a quadratic equality; needs an NLP solver. |
| `grid_code` | `None` (→ 4120) | `"4105"`, `"4110"`, `"4120"`, or a `GridCode`. `var_q` must index a variant the code defines (4105 has 2, 4110 has 1, 4120 has 3). |
| `qu_deadband` | `None` | Replaces the Q(U) *area* with a dead-band *characteristic*. **Non-convex → builds integer blocks → IPOPT alone cannot solve it.** |
| `sgen_types` / `wind_sgen_types` | see source | Exact-match `type` lists selecting PV / wind sgens. |

`DCOPF.add_OPF(angle_limits=False, **kwargs)` accepts only `angle_limits` plus
whatever `OPF.add_OPF` forwards to `_calc_opf_parameters`; it has no
`thermal_limit`, since the DC branch limit is a bound on active flow.

## Objectives
Attach exactly one. Each creates a differently named Pyomo component, so read
back the one you attached.

| Call | Model | Component | Minimises |
|---|---|---|---|
| `add_voltage_deviation_objective()` | ACOPF, ACOPF_multi_period | `obj_v_deviation` | `Σ(v−1)²` off-slack, `Σ(v−v_b0)²` at slack |
| `add_reactive_power_flow_objective()` | ACOPF only | `obj_reactive` | `Σ qsG²` over static generators |
| `add_active_change_objective()` | ACOPF only | `obj_loading` | squared deviation from the reference dispatch, plus soft-balance and small Q/storage penalties. Redispatch framing: it refixes `gG` and frees `eG`. |
| `add_generation_objective()` | ACOPF_multi_period only | `obj` | `Σ pG²` over generators and time |
| `add_weighted_generation_objective()` | ACOPF_multi_period only | `obj` | `4·Σ pG + 1·Σ psG`. **The weights are hard-coded and have no economic meaning.** |
| `add_minimize_power_objective()` | ACOPF_multi_period only | `Objective` | `Σ pD` — minimises *served demand*; almost never what you want |
| `add_poly_cost_objective(opf, allow_quadratic=True)` | single-period | `obj_poly_cost` | `Σ c2·P² + c1·P + c0` from `net.poly_cost`, in EUR/h |
| `add_loss_obj()` | HC_ACOPF | — | hosting-capacity wind-loss objective |

`add_poly_cost_objective` raises `ValueError` if `net.pwl_cost` has rows
(piecewise-linear costs are unsupported), and with `allow_quadratic=False` if any
`cp2 != 0` — use that for an LP DC OPF on GLPK/CBC.

DC OPF has **no built-in objective**. Either use `add_poly_cost_objective` or
attach your own, which is the documented pattern from `objective_tradeoff_demo.py`
in the upstream potpourri repository (not bundled here):

```python
# minimise external-grid import
model.obj_import = pyo.Objective(
    expr=sum(model.pG[g] for g in model.eG), sense=pyo.minimize
)
# minimise AC branch losses (both branch-end injections sum to the loss)
model.obj_losses = pyo.Objective(
    expr=sum(model.pLfrom[l] + model.pLto[l] for l in model.L)
    + sum(model.pThv[t] + model.pTlv[t] for t in model.TRANSF),
    sense=pyo.minimize,
)
```

SimBench networks carry **no** `poly_cost`, so cost minimisation needs cost data
you supply, or a PGLib case via `load_pglib_case`.

## Multi-period models
```python
opf = ACOPF_multi_period(net, toT=96, fromT=0)   # time set is [fromT, toT)
```
- **Requires `net.profiles`** and raises `ValueError` without it. In practice
  that means a SimBench network; a plain pandapower JSON will not work.
- `T = toT - fromT if fromT else toT`, and `toT` must not exceed the profile
  length.
- `deltaT` is **hard-coded to 0.25 h** (15 min). There is no option to change it,
  so a 96-step horizon is exactly one day and energy is always `Σ P · 0.25`.
- `ACOPF_multi_period.add_OPF(grid_code=None, qu_deadband=None)` — a **narrower**
  surface than single-period: `_calc_opf_parameters()` takes no keyword
  arguments, so `thermal_limit` and `angle_limits` raise `TypeError` rather than
  being ignored. The multi-period AC model always uses the current-limit form.
- The multi-period AC model **pins the slack voltage magnitude** at every step
  (`AC_multi_period` fixes `v[b0, t] = v_b0[b0]`). There is no `free_slack_vm`.
  The same network therefore gives a different voltage profile single-period
  (slack free) than multi-period (slack pinned).
- Controllable sgens get `sPGmax = PsG[g,t]` (the profile value) and
  **`sPGmin = 0` hard-coded** — `net.sgen.min_p_mw` is ignored, so curtailment to
  zero is always allowed and cannot be blocked.
- Available vs dispatched power per step is `model.PsG[g,t]` vs `model.psG[g,t]`,
  both p.u. on `baseMVA`. Use these for curtailment, not `net.sgen.max_p_mw`.

## Flexible devices
Devices are composed, not inherited: construct one, then attach it to the
model **before** `add_OPF()`.

```python
opf = ACOPF_multi_period(net, toT=96)
battery = Battery_multi_period(opf.net, T=96, scenario=1)  # note opf.net
battery.get_all(opf.model)
opf.add_OPF()
opf.add_voltage_deviation_objective()
```

Available: `Battery_multi_period`, `PV_multi_period`, `Heatpump_multi_period`
(lower-case `p`), `Windpower_multi_period`, `Demand_multi_period`,
`Sgens_multi_period`, `Generator_multi_period`, `Shunts_multi_period`. The last
four are attached automatically by the multi-period base model.

`Battery_multi_period(net, T=None, scenario=None, *, penetration=None,
power_pu=0.006, soc_max=1.0, soc_min=0.2, capacity_pu_h=0.015, efficiency=0.9,
initial_soc_fraction=0.5)`. Give either `scenario` (0–3 → 1.0/7.9/9.9/10.6 % of
non-slack buses) or `penetration`. All powers/energies are p.u. on `net.sn_mva`.

**Battery placement is random** (`np.random.choice` over non-slack buses), so
seed NumPy before constructing it or results are not reproducible.

Battery model, exactly as implemented:
- One signed variable `BAT_P[b,t]` (positive = charging), bounded
  `±power_pu`. No separate charge/discharge legs, so simultaneous
  charge and discharge is structurally impossible.
- `BAT_SOC[b,t] = BAT_SOC[b,t-1] + deltaT · BAT_P[b,t] · eff / cap`.
- `BAT_SOC` at the first step is pinned to `BAT_SOC_init`; on later steps it is
  bounded by `[soc_min, soc_max]`.
- **No terminal-SOC constraint** — the battery may end the horizon at any SOC.
- Because a single signed power is multiplied by `eff`, a charge/discharge cycle
  returns exactly to its starting SOC: **round-trip efficiency is effectively
  100 % whatever `efficiency` is set to**. `efficiency` only scales the
  power-to-SOC ratio. Do not present multi-period battery results as an economic
  storage dispatch.

The **single-period** storage block is different and physically correct:
`net.storage` rows produce `STOR_Pchg`/`STOR_Pdis` with
`η·Pchg − Pdis/η`, an inverter circle `pSTOR² + qSTOR² ≤ Pmax²`, and the
complementarity relaxed to `Pchg + Pdis ≤ Pmax` — so a small simultaneous
charge/discharge overlap is possible and worth checking. `STOR_dt` is 0.25 h.

## Solving
```python
results = opf.solve(
    solver="ipopt",            # 'glpk', 'cbc', 'gurobi_direct_minlp', 'mindtpy', 'neos'
    print_solver_output=False,
    to_net=True,
    time_limit=600,            # honoured only by mindtpy and gurobi*
    max_iter=None,             # -> IPOPT max_iter, or Gurobi IterationLimit
    mip_solver="gurobi",       # mindtpy sub-solver
    init_strategy="rNLP",      # mindtpy
    neos_opt="ipopt",          # single-period default; multi-period default is 'bonmin'
)
```
An unavailable solver raises `RuntimeError` from inside `solve()`, after the
whole model has been built. Probe first with
`pyo.SolverFactory(name).available(exception_flag=False)`.

## Reading results
```python
import pyomo.environ as pyo
if pyo.check_optimal_termination(results):
    ...   # only now are net.res_* the optimisation result
print(results.solver.status, results.solver.termination_condition)
print(pyo.value(opf.model.obj_v_deviation))
```

Three extraction traps, all verified:
1. `net.res_*` is populated by the constructor's `pp.runpp`, so it is **never
   empty**. On a non-optimal solve potpourri skips the mapping and those tables
   still hold the base case.
2. **Multi-period `solve(to_net=True)` never writes `net.res_*`** — it logs
   "Solution mapped to net.res_*" without calling the mapper. Do it yourself per
   step: `pyo_sol_to_net_res(opf.net, opf.model, t)`. Each call overwrites
   `net.res_*`, so read what you need before advancing `t`.
3. After a DC OPF, `net.res_bus.vm_pu` is a flat 1.0 placeholder.
   `net.res_line.loading_percent` *is* meaningful (from active flow).

## Network preparation and controllability
`add_OPF()` reads these pandapower columns, so set them **before** building:

| Column | Effect |
|---|---|
| `bus.min_vm_pu` / `max_vm_pu` | AC voltage bounds (`Vmin`/`Vmax`, mutable Params) |
| `line.max_loading_percent` | `SLmax = pct/100 · max_i_ka · df · parallel · √3·vn_kv / baseMVA` |
| `trafo.max_loading_percent` | `SLmaxT = pct/100 · sn_mva · df · parallel / baseMVA` |
| `sgen.controllable` | membership of `model.sGc`; only these are optimised |
| `sgen.min_p_mw` / `max_p_mw` | `sPGmin`/`sPGmax` (single-period only) |
| `sgen.sn_mva`, `converter_sizing_pu` | inverter circle when `inverter_s2=True` |
| `sgen.var_q`, `type` | Q-control selection |
| `ext_grid.min/max_p_mw`, `min/max_q_mvar` | `PGmin`/`PGmax` and Q bounds |
| `load.controllable`, `min/max_p_mw` | controllable demand (`model.Dc`) |
| `poly_cost` | cost objective |

A line with missing or zero `max_i_ka` gets an effectively unbounded thermal
limit, so congestion on it silently disappears. `net.impedance` rows are modelled
as extra lines at synthetic indices `≥ len(net.line)`; unrated ones
(`sn_mva == 0`) get a 1e6 MVA limit.

Helpers in `potpourri.net_augmentation.prepare_net`:
`apply_loadcase_to_sb_net(net, case)`, `add_regulatory_q_control_to_wind(net,
variant)`, `upgrade_pandapower_net(old_net)`.

## Not supported
Do not offer these — they do not exist:
- **No EV module.** The README lists EVs among the flexible resources; there is
  no `ev.py` and no EV class. Only the devices listed above exist.
- No piecewise-linear cost curves (`net.pwl_cost` raises).
- No independent charge/discharge efficiencies anywhere.
- No terminal-SOC or cyclic-SOC constraint on the multi-period battery.
- No configurable multi-period time step (`deltaT` is fixed at 0.25 h).
- No `thermal_limit` or `angle_limits` on multi-period models.
- No N-1 / contingency analysis — use the pandapower skill for that.
- No PowerMCP server, so no MCP tool names to call.

## Documentation traps
- `README.md` writes `HeatPump_multi_period`; the class is
  `Heatpump_multi_period`.
- `README.md` and `CLAUDE.md` claim EV support; there is none.
- `CLAUDE.md` shows `Battery_multi_period(mpopf)`; the signature is
  `(net, T, scenario, ...)`.
- `docs/user-guide/solvers.md` says every model populates `net.res_*` after a
  successful solve; multi-period does not.
- Installing `opf-potpourri` alone pulls pandapower ≥ 3.5, where
  `pp.create_continuous_bus_index` no longer exists at the top level and every
  constructor raises `AttributeError`. Pin `pandapower<3.5`.
