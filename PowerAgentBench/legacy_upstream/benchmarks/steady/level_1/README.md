# Level 1: IEEE 39-Bus Easy Steady-State Task

This folder defines a reproducible level-1 benchmark for steady-state power-system operations using the IEEE 39-bus test system in PyPSA. The task is intentionally small enough for rapid iteration, but it still requires an agent to:

1. run a base-case AC power flow,
2. run a curated N-1 contingency analysis,
3. identify overload and voltage violations,
4. apply a valid mitigation plan from a constrained action space, and
5. trade off residual violations against operational action cost.

The benchmark is built on top of `pandapower.networks.case39()` and converted into a PyPSA network through the PYPOWER-compatible import path. That keeps the source network standard while ensuring competitors operate on a PyPSA-native case during evaluation.

## Files

- `actionspace.json`
  - Published action contract: limits, step sizes, contingency list, and operating criteria.
- `actioncost.json`
  - Per-step action costs used by the evaluator.
- `baseline_summary.json`
  - Reference no-action evaluation output for the prepared scenario.
- `solution_template.json`
  - Minimal valid solution file competitors can copy and edit.

Case data lives in `cases/case39/` (PyPSA, MATPOWER, and PandaPower formats).
Shared code lives in `poweragentbench/benchmark_utils.py`.
Scripts live in `scripts/` (`build_case.py`, `evaluate_solution.py`, `convert_case.py`).

## Task Intent

The scenario is a stressed but still solvable operating point. The base case contains:

- line overloads in the southern corridor,
- an undervoltage pocket around buses 6-7,
- additional violations when selected N-1 outages are applied.

This is an "easy" task because:

- the contingency set is deliberately small and published,
- the action space is limited and discrete,
- only one prepared operating point is evaluated,
- the network is only 39 buses.

It is still nontrivial because a cheap voltage-only correction does not fully resolve the thermal issues, and a pure redispatch strategy is close to feasible but still leaves post-contingency stress unless the agent uses the action space carefully.

## Scenario Construction

`scripts/build_case.py` creates the task case by:

1. loading `pandapower.networks.case39()`,
2. running a source-side AC power flow,
3. converting the solved case to PYPOWER format,
4. importing that case into PyPSA,
5. applying the benchmark stress pattern:
   - selected loads `L10`, `L11`, `L12`, `L14`, `L15`, `L16`, `L17`, `L18`, and `L20` are scaled by `1.25`,
   - generation is shifted away from the southern area:
     - `G7` decreases by `20 MW`,
     - `G8` decreases by `100 MW`,
     - `G9` decreases by `180 MW`,
     - `G1` and `G2` each increase by `150 MW`,
   - AVR setpoints at `G6`, `G7`, `G8`, and `G9` are each lowered by `0.01 pu`.

Those changes create the target combination of:

- manageable base-case overloads,
- a weak voltage pocket,
- contingency responses that are still recoverable with a small number of constrained actions.

## Operating Criteria

The evaluator uses two sets of limits:

- Base case
  - line loading `<= 100%`
  - bus voltage in `[0.95, 1.06] pu`
- Selected N-1 contingencies
  - line loading `<= 110%`
  - bus voltage in `[0.94, 1.08] pu`

Only the published contingency set is scored for this level:

- `L7_outage`
- `L12_outage`
- `L20_outage`

These are stored in `actionspace.json` and consumed directly by the reference evaluator.

## Action Space Design

The action space is intentionally constrained. Agents cannot apply arbitrary dispatch or extreme curtailment. Every action has an explicit limit and step size.

Available action categories:

- Generator redispatch
  - `redispatch_G7_up`: `0` or `+20 MW`
  - `redispatch_G8_up`: `0` or `+50 MW`
  - `redispatch_G9_up`: `0`, `+50 MW`, or `+100 MW`
- Reactive/voltage support
  - `vm_support_south`: coordinated `+0.01 pu` increase for `G7`, `G8`, and `G9`
  - `switch_shunt_bus7`: switch in a `50 Mvar` capacitor bank at bus 7
- Transformer controls
  - `tap_T1_up`: raise transformer `T1` by one tap step
  - `phase_shift_T9`: change transformer `T9` phase shift by `-2`, `0`, or `+2` degrees
- Load curtailment
  - `shed_load_L20`: up to `5%` in `2.5%` steps
  - `shed_load_L10`: up to `5%` in `2.5%` steps

Operational realism built into the action space:

- Redispatch limits respect the actual headroom of the stressed units.
- Load shedding is capped at `5%`, not treated as unlimited emergency shedding.
- Load shedding preserves the original power factor by scaling both `P` and `Q`.
- Voltage support uses bounded AVR movements instead of arbitrary voltage targets.
- Transformer movement is discrete, not continuous.
- Switchable shunt action is limited to installed Mvar capacity.

## Cost Model

The benchmark reports two primary outcomes:

- `remaining_violation_score`
- `action_cost`

Ranking rule:

- Lower `remaining_violation_score` is always better.
- If two solutions have the same `remaining_violation_score`, lower `action_cost` wins.

The evaluator also emits a convenience `composite_score = 10000 * remaining_violation_score + action_cost`, but the benchmark contract is still the lexicographic rule above.

Action costs are per step and live in `actioncost.json`.

Design intent:

- Redispatch is moderately priced.
- Voltage support, tap moves, and shunt switching are cheap.
- Load shedding is expensive.

This forces competitors to prefer control actions over curtailment unless curtailment is necessary to eliminate the last residual violations.

## Violation Scoring

The evaluator computes a scalar violation score for each operating state:

- line overload penalty: sum of `(loading_pct - limit_pct) / 100` over violated lines
- low-voltage penalty: `10 * sum(v_min - v)` over violated buses
- high-voltage penalty: `10 * sum(v - v_max)` over violated buses

Total remaining violation score:

- base-case violation score
- plus the sum of all published contingency violation scores

A fully feasible solution has `remaining_violation_score = 0.0`.

## How To Rebuild the Benchmark Case

From the repository root:

```bash
python scripts/build_case.py
```

This will:

- rebuild `cases/case39/pypsa/case39.nc`
- recompute `benchmarks/steady/level_1/baseline_summary.json`

Use this if you modify `src/benchmark_utils.py` or want to regenerate the scenario from the original IEEE 39 source.

## How To Export to MATPOWER and PandaPower Formats

```bash
python scripts/convert_case.py
```

This creates `cases/case39/matpower/case39.m` and `cases/case39/pandapower/case39.json`.

## How To Evaluate a Solution

1. Create a solution JSON that follows `solution_template.json`.
2. Run:

```bash
python scripts/evaluate_solution.py --solution benchmarks/steady/level_1/solution_template.json
```

Example output fields:

- `base_case`
- `contingencies`
- `remaining_violation_score`
- `action_cost`
- `composite_score`
- `feasible`
- `applied_actions`

## Solution File Contract

Expected format:

```json
{
  "actions": [
    { "id": "redispatch_G8_up", "value": 50.0 },
    { "id": "redispatch_G9_up", "value": 100.0 },
    { "id": "shed_load_L20", "value": 5.0 }
  ]
}
```

Rules:

- Omitted actions default to zero.
- Values must match the step size in `actionspace.json`.
- Values outside the published min/max range are invalid.
- Duplicate action ids are invalid.

## Recommended Competitor Workflow

1. Load `cases/case39/pypsa/case39.nc` into PyPSA (or the PandaPower/MATPOWER equivalents).
2. Run the base AC power flow.
3. Identify:
   - overloaded lines,
   - low-voltage buses,
   - whether high-voltage buses exist.
4. Apply the listed N-1 outages from `actionspace.json`.
5. Summarize which violations persist across the contingency set.
6. Select actions from the published action space.
7. Re-run the base case and all contingencies after applying actions.
8. Minimize residual violations first, then action cost.

## Notes for Benchmark Authors and Extenders

- This level intentionally uses a curated contingency set instead of every line/transformer outage. That keeps the task stable and fast for entry-level benchmarking.
- The prepared case and the evaluator are both deterministic.
- The action space is discrete by design to keep search spaces interpretable and to simplify downstream evaluation.
- If you create harder levels later, the natural next extensions are:
  - larger contingency sets,
  - multiple prepared operating points,
  - more interacting reactive controls,
  - explicit topology switching.

## Dependencies

Reference environment used during benchmark creation:

- `pypsa 1.0.7`
- `pandapower`
- `numpy`
- `pandas`

Competitors only need PyPSA plus the dependencies required to load the prepared network and run the provided evaluator.
