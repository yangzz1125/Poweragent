# Choosing a potpourri formulation

The formulation decides which physics exists in the model. Picking it is an
engineering judgement, not a performance tweak: a DC model cannot answer a
voltage question at any solver cost, and an AC multi-period model can cost
hundreds of times more than the question is worth.

## Power flow or optimal power flow?
potpourri exposes both, and they answer different questions.

- **Power flow** (`AC(net)`, `DC(net)`, or `pp.runpp`) — "given this dispatch,
  what is the operating point?" No decision variables are freed; there is no
  objective. Use it to establish and validate a base case.
- **OPF** (`ACOPF`, `DCOPF`, and the multi-period variants) — "what is the best
  dispatch subject to limits?" `add_OPF()` is the step that unfixes the
  controllable variables and installs the bounds. Without it you have a power
  flow with an objective bolted on, and nothing to optimise.

If nobody asked for a *decision*, a power flow is the right tool and the
pandapower skill is the cheaper route.

## AC or DC?
| | DC (`DCOPF`) | AC (`ACOPF`) |
|---|---|---|
| Voltage magnitude | absent (`model.v` does not exist) | full, bounded by `Vmin`/`Vmax` |
| Reactive power | absent | full, with generator and inverter limits |
| Losses | zero by construction | modelled |
| Branch limit | bound on active flow `|pLfrom| ≤ SLmax` | `|S|² ≤ SLmax²·v²` or `≤ SLmax²` |
| Problem class | LP (QP with quadratic costs) | nonconvex NLP |
| Typical solve on a 15-bus LV feeder | ~0.04 s (GLPK) | ~3-5 s (IPOPT) |

**Use DC when** the question is about active-power routing: congestion
screening, headroom, import/export volumes, a fast first pass over many
snapshots or scenarios, or a sanity check that a network is roughly balanceable.

**Use AC when** anything below matters, which in distribution networks is almost
always: bus voltages, reactive power or power factor, inverter capability, losses,
tap positions, Q(U)/Q(P) grid-code behaviour, or hosting capacity.

**DC feasibility does not establish AC feasibility.** In an LV or MV feeder the
binding constraint is usually voltage rise or reactive capability, neither of
which exists in the DC model. A DC OPF that reports comfortable line loadings can
sit on an AC-infeasible point. Always confirm a DC-derived decision with an AC
solve before presenting it as an operating recommendation.

The reverse asymmetry is worth stating too: DC and AC active-power results
usually agree closely (on the bundled LV feeder, external-grid exchange of
−0.0694 MW DC vs −0.0689 MW AC), because the difference is essentially the
losses. Agreement on active power is therefore weak evidence — it does not tell
you the AC voltage constraints are satisfied.

## Snapshot or multi-period?
A single period is the default. Escalate to multi-period only when the question
is genuinely time-coupled.

**Single period** (optionally repeated over independent snapshots) answers:
worst-case voltage, congestion at peak load or peak PV, curtailment needed now,
reactive dispatch. Independent snapshots are usually the right way to cover a
day: they parallelise, they are individually diagnosable, and each solve is small.

**Multi-period** is required only when a constraint links time steps:
- storage state of charge,
- any energy budget over the horizon,
- ramp limits or tap-change-rate limits
  (`add_tap_changer_linear(max_tap_change_per_step=...)`),
- heat-pump thermal storage (`Heatpump_multi_period`).

Without such coupling, a multi-period model returns exactly the concatenation of
the snapshots at many times the cost.

Cost is less of an obstacle than it looks, at least at distribution scale.
Measured on the SimBench `1-LV-rural1--0-sw` feeder (15 buses) with IPOPT,
minimising voltage deviation:

| Steps | Variables | Constraints | Solve time |
|---|---|---|---|
| 3 | 369 | 429 | 48 s |
| 16 | 1 968 | 2 288 | 43 s |
| 96 | 11 808 | 13 728 | 54 s |

The model grows linearly in steps, but wall time on a network this small is
dominated by a fixed overhead rather than by the horizon — a full 96-step day is
about as expensive as three steps. Do not extrapolate that to a large MV or HV
network, where the per-step nonlinear solve is itself substantial; and still
prototype the *setup* on 3-8 steps, because a configuration error costs the same
50 s either way and is far easier to read at 3 steps.

### Multi-period constraints you must know before proposing one
- It **requires SimBench profiles** (`net.profiles`) and raises `ValueError`
  without them. A plain pandapower JSON cannot be run multi-period.
- `deltaT` is fixed at **0.25 h**, so 96 steps is exactly one day and there is no
  hourly mode.
- The slack **voltage magnitude is pinned** at every step; single-period AC lets
  it float by default. Do not compare the two voltage profiles without saying so.
- `thermal_limit` and `angle_limits` are **not accepted** and raise `TypeError`.
- Curtailment to zero is **always allowed** (`sPGmin = 0` hard-coded), so "PV must
  stay at its available output" is not expressible.
- The battery model has no terminal-SOC constraint and no genuine round-trip
  loss. See `API_REFERENCE.md`; treat storage results as flexibility studies, not
  economic dispatch.

## Continuous or mixed-integer?
| Question | Model | Class | Solver |
|---|---|---|---|
| dispatch, curtailment, reactive support | `ACOPF` | NLP | IPOPT |
| active-power routing, congestion | `DCOPF` | LP/QP | GLPK, CBC, HiGHS |
| discrete transformer taps | `add_tap_changer_discrete()` | MINLP | `gurobi_direct_minlp`, or MindtPy |
| Q(U) with a dead band (`qu_deadband=`) | integer piecewise blocks | MINLP | as above; **IPOPT alone cannot** |
| hosting capacity with binary siting | `HC_ACOPF` | MINLP | `gurobi_direct_minlp` preferred |

Reach for integers only when the decision really is discrete. `add_tap_changer_linear()`
treats the tap as continuous and is usually the better screening choice: it tells
you whether tap action helps at all, for a fraction of the cost. Only then pay
for the discrete version to get a settable position.

Integrality changes what the answer means. A continuous relaxation gives a bound,
not a realisable setting; a MINLP on nonconvex AC physics gives a locally
feasible incumbent unless a global solver proves otherwise.

## Operations, planning, or feasibility restoration?
These are different problems and choosing the wrong objective silently answers
the wrong one.

- **Operational dispatch** — what to do now, within existing assets.
  `add_voltage_deviation_objective`, `add_reactive_power_flow_objective`, a loss
  or import objective, or `add_poly_cost_objective` where cost data exists.
- **Redispatch from a reference** — how little must change to fix a problem.
  `add_active_change_objective()` penalises deviation from the current dispatch
  and frees the slack, which is the right framing for "least intrusive fix".
- **Hosting capacity / planning** — how much more DER fits. `HC_ACOPF` with
  binary siting, or a parametric sweep of installed capacity across single-period
  solves.
- **Feasibility restoration** — is there *any* admissible point? Drop the economic
  objective, minimise a physically meaningless but well-scaled quantity such as
  voltage deviation, and reintroduce constraint groups one at a time. Do not
  attempt to read economics off such a run.

## Objective side effects worth stating out loud
Every objective here is a proxy, and each has a failure mode a reviewer will
notice before you do:

- **Voltage deviation** puts no value on energy. Where curtailment is free, the
  flattest voltage profile is usually *zero* renewable injection — on the bundled
  LV feeder it curtails 100 % of available PV. Always report curtailment
  alongside it, and pin `min_p_mw = max_p_mw` (single-period only) if you mean
  "keep the PV".
- **Reactive power** minimisation drives Q to zero, which can push voltages
  toward their limits; it makes sense as a second stage at fixed active dispatch.
- **Losses** minimisation drives voltage to its **upper** limit, because at
  constant power a higher voltage means less current and losses go as `I²`. On
  the bundled LV feeder it parks buses at 1.0499 pu against a 1.05 pu ceiling —
  a technically optimal answer that leaves no headroom for a voltage excursion.
  Compare it against a voltage-deviation run before recommending it: on the same
  snapshot that objective holds 0.9975-1.0027 pu instead.
- **Weighted generation** uses hard-coded weights 4 and 1 with no units — a
  ranking score, never a cost.
- **Minimise served demand** (`add_minimize_power_objective`) minimises load
  served. It is a curtailment-of-demand study, not a dispatch objective.
- **Polynomial cost** is the only objective with a real economic interpretation,
  and SimBench networks have no cost data.

Multi-objective work is not built in. Weighted sums must be scaled by hand — the
squared-voltage term is dimensionless and typically 1e-4, while a p.u. power term
is 1e-2, so an unscaled sum is dominated by whichever happens to be larger.
Disclose the weights and the scaling whenever you combine terms;
`custom_objective_weighted_voltage.py` in the upstream potpourri repository (not
bundled here) shows the pattern.
