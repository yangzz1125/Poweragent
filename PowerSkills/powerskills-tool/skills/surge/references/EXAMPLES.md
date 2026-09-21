# Surge Workflows

Multi-tool recipes against the Surge MCP server. Each example follows
the ladder from `SKILL.md`.

## 1. Base-case AC solve on a built-in case

```
load_builtin_case(name="case118")
→ get_network_info()
→ run_ac_power_flow()
```

Verify `converged=True` and `max_mismatch < 1e-5` before proceeding.

**Deliver:** case loaded, converged status, iterations.

## 2. N-1 screening workflow

```
load_builtin_case(name="case118")
→ run_ac_power_flow()                    # confirm base case
→ run_n1_branch_contingency()            # sweep
→ (inspect results.violations, summarize by violation_type)
→ hand off to contingency-mitigation
```

The `violations` list is already flattened and filtered to only
post-contingency violations. Use `n_with_violations /
n_contingencies` to frame severity.

**Deliver:** total contingencies, how many had violations, top 5
violations by `loading_pct` or `vm_pu` deviation.

## 3. DC-OPF on the open-source path

```
load_builtin_case(name="case300")
→ get_network_info()
→ run_dc_power_flow()                    # feasibility check
→ run_dc_opf(lp_solver="highs")          # explicit HiGHS
```

Report `total_cost`, `feasible`, and the top 3 congested branches by
`branch_loading_pct`.

**Deliver:** cost, feasibility, any binding constraints.

## 4. SCOPF with both open-source solvers

```
load_builtin_case(name="case118")
→ run_ac_power_flow()
→ run_scopf(lp_solver="highs", nlp_solver="ipopt")
```

`screening_stats` reports how many contingency constraints were
added. `binding_contingencies` is the final set that bound the
solution. If `converged=False`, do not report the dispatch as
valid.

**Deliver:** converged flag, iterations, binding contingencies.

## 5. PTDF drill-down

```
load_builtin_case(name="case118")
→ run_dc_power_flow()
→ compute_ptdf(format="summary", top_k_per_branch=5)
```

Follow-up for a specific branch:

```
compute_ptdf(
    monitored_branches=[(from_bus, to_bus, circuit)],
    format="full"
)
```

Do not request `format="full"` on unfiltered large networks — a dense
30K-bus matrix exceeds practical response sizes.

**Deliver:** matrix shape, sparsity, top-k most sensitive buses per
monitored branch.

## 6. NERC ATC between two areas

```
load_builtin_case(name="case118")
→ get_network_info()                     # inspect areas
→ list_buses(sort_by="area", limit=None)
→ compute_nerc_atc(
      source_buses=[buses in area A],
      sink_buses=[buses in area B],
      name="A-to-B",
      trm_fraction=0.05
  )
```

Watch for `limit_cause="unconstrained"` or `atc_mw=inf` — these
indicate the path has no real binding constraint in the current
case (often because the chosen bus sets are too small or too close
together). Pick a longer path.

**Deliver:** ATC (MW), TTC (MW), limit cause, binding branch or
contingency.

## 7. SCUC dispatch (HiGHS MIP)

```
load_builtin_case(name="market30")
→ get_network_info()
→ get_dispatch_request_schema()                 # inspect request shape
→ run_scuc(request=<DispatchRequest dict>, lp_solver="highs")
```

`request` is the `DispatchRequest` TypedDict; use `request=None` for a
single-period LP with all generators committed.

**Deliver:** objective cost, per-period commitment decisions, any
period-level convergence issues.

## 8. Mixed-format case load

When the user has a PSS/E RAW file with an unusual extension:

```
load_network(file_path="./my_case.dat", format="psse")
```

## 9. Exploring an unknown case

```
load_network(file_path="./unknown.m")
→ get_network_info()                                              # counts, areas, voltage levels
→ list_buses(limit=20, sort_by="pd_mw", ascending=False)          # biggest loads
→ list_branches(limit=20, sort_by="rate_a_mva", ascending=False)  # largest paths
→ run_ac_power_flow()
```

## 10. Stop-and-escalate conditions

Do not continue to downstream studies when:

- `run_ac_power_flow` returns `converged=False` or `max_mismatch > 1e-3`
  → model data problem; report to user.
- `run_scopf` `converged=False` → escalate to `operations-planning-mitigation`.
- `compute_nerc_atc` returns `limit_cause="fail_closed_outage"` →
  escalate to `contingency-mitigation`.
- Thermal or voltage violations in N-1 results → escalate to
  `thermal-overload-mitigation` or `voltage-violation-mitigation`.
