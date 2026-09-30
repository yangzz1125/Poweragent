# Operating protocol — IEEE 39-Bus Agent KPI Benchmark

This file tells an LLM agent how to run one benchmark trial. Read
[README.md](README.md) first for what the benchmark measures and how the
severity score is defined.

The benchmark asks one question: **given only simulations of faults at other
durations, how well can you predict the severity of an unseen fault?**

---

## The rule that makes this a benchmark

> **Commit your prediction with `save_predictions` before you run the
> simulation. Never revise it afterwards.**

Everything else is procedure; this is the actual experiment. If you simulate
first and predict second, the trial is void — say so rather than reporting a
score.

Two supporting rules:

- **Test scenarios are unseen.** `get_training_history` returns only durations
  from the training split. Do not call `lookup_scenarios` or
  `query_semantic_memory` on the test CSV you are about to predict — that would
  hand you the answer. Querying *other* locations and durations is the whole
  point and is encouraged.
- **State your uncertainty.** A confident wrong number and a hedged wrong
  number score the same, but only one of them is honest reporting.

---

## The five steps

### 1. Pick a test scenario

```
read_memory_split(split="test")     → list of held-out scenario paths
```

Paths look like `Bus 12\16.csv` — location folder plus fault duration in
"cycles", where 1 cycle = 10 ms. So `Bus 12\16.csv` is a 160 ms fault at Bus 12,
with the fault window running 1.00 s → 1.16 s.

### 2. Study the training history

```
get_training_history(location="Bus 12", fault_type="Bus")
```

Returns every training entry for that location, ordered by duration, each with
its full KPI dict. This is your primary evidence. Look for:

- the **trend** of `severity_score` as duration grows — is it linear, or does it
  bend sharply upward near a threshold?
- the **first duration where `stable` flips to 0** — beyond it, severity is
  pinned at 1.0 by definition, so extrapolation is trivial.
- which buses recur in `buses_vlo_aft_names` / `buses_vhi_aft_names`, and the
  `vmin_aft_bus` / `vmax_aft_bus` extremes.

Useful supplements:

- `get_location_history` — all entries for a location, any split.
- `query_semantic_memory("...")` — find electrically similar situations at
  *other* locations. Needs `sentence-transformers` installed; if it errors with
  a missing module, fall back to the structured tools.
- `lookup_scenarios([...])` — exact entries for specific training paths.

### 3. Commit the prediction

```
save_predictions([{
  "scenario_path":  "Bus 12\\16.csv",   # must match step 1 exactly
  "severity_score": 0.42,               # 0–1; 1.0 means you predict instability
  "stable":         true,
  "vmin_aft":       0.78,               # pu, post-fault minimum
  "vmax_aft":       1.12,               # pu, post-fault maximum
  "bus_vmax":       "Bus 29",           # which bus you expect to hold the max
  "bus_vmin":       "Bus 12"            # which bus you expect to hold the min
}])
```

Keep `severity_score` and `stable` consistent: predicting `stable: false` while
giving a severity well below 1.0 is contradictory, because the scorer forces
1.0 whenever a generator loses synchronism.

Before moving on, write down your reasoning — the trend you extrapolated and how
confident you are. That reasoning is what the trial is really evaluating.

### 4. Generate the ground truth

If the CSV already exists in the dataset, skip to step 5 and use its path.

Otherwise run the simulation (requires PowerFactory running):

```
ping                                    → check the session first
run_custom_case(...)                    → one-off case, returns the CSV path
run_simulation()                        → or the full pipeline from simulation_config.json
read_results_csv(as_path=True)          → locate the newest *_RMS.csv
```

The fault must match the scenario: same element, fault applied at t = 1.0 s and
cleared at 1.0 + cycles/100 s. A mismatch invalidates the comparison.

### 5. Evaluate

```
evaluate_predictions(csv_path="<absolute path to the *_RMS.csv>",
                     scenario_path="Bus 12\\16.csv")
```

Returns `actual`, `predicted` and a `comparison` block with `abs_error` and
`rel_error_pct` on severity, a `correct` flag on stability, absolute pu errors
on the voltages, and — for `bus_vmax` / `bus_vmin` — the actual bus list plus
whether your pick was in it.

Report the result **as returned**, including misses. A trial where the agent was
wrong is a valid data point; a trial where the agent quietly adjusted its
prediction is not.

---

## Tool selection quick reference

| You want to… | Use |
|---|---|
| know which scenarios are held out | `read_memory_split` |
| see a location's KPI trend vs. duration | `get_training_history` |
| find similar situations elsewhere | `query_semantic_memory` |
| get exact entries for known paths | `lookup_scenarios` |
| compute KPIs for any CSV | `run_kpis` |
| commit a prediction | `save_predictions` |
| score it | `evaluate_predictions` |
| run a new simulation | `run_custom_case` / `run_simulation` |

---

## Gotchas

- **Path separators.** Scenario paths use Windows backslashes and must match
  `memory_split.txt` exactly. Forward slashes are accepted by the tools, but
  `save_predictions` and `evaluate_predictions` must use the *same* spelling.
- **`run_kpis` is not comparable to the memory.** It defaults to
  `after_extra=0.02`, while the memory and `evaluate_predictions` use `0.1`.
  Pass `after_extra=0.1` if you want to compare like with like.
- **PowerFactory must already be running** before any PF tool is called;
  `import_project` cannot start the application itself.
- **Severity is capped in a specific way.** Loss of synchronism (any generator
  above 1.05 pu) forces the score to exactly 1.0, so severity above 1.0 is never
  produced — do not predict values greater than 1.0.
- **Rebuilding the memory invalidates prior results.** Do not run
  `semantic_memory.py build` mid-benchmark.
