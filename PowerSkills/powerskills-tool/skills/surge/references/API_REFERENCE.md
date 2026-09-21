# Surge MCP Tool Reference

44-tool catalog for `PowerMCP/surge/surge_mcp.py`. Every tool returns
`{"status": "success"|"error", "message": str, "results"?: dict}`.
Payloads are JSON-serializable via surge-py's `.to_dict()` helpers.

## Case I/O

### `load_network(file_path, format=None)`
Load a network from disk. Auto-detects from the file extension; the
`format` argument overrides detection when needed.

Supported formats (by name): `matpower`, `psse`, `rawx`, `xiidm`,
`ucte`, `surge-json`, `surge-bin`, `dss`, `epc`.

Returns: a `get_network_info`-style summary of the loaded case.

### `save_network(file_path)`
Persist the currently loaded network. Format is detected from the
extension.

### `load_builtin_case(name)`
Load an embedded benchmark case. Available names:
`case9`, `case14`, `case30`, `market30`, `case57`, `case118`, `case300`.

Returns: `{available: [...], summary: {...}}`.

### `get_network_info()`
Comprehensive network summary — a single call that replaces ten
getter probes. Fields:

- Counts: `n_buses`, `n_branches`, `n_branches_in_service`,
  `n_generators`, `n_generators_in_service`, `n_loads`,
  `n_loads_in_service`, `n_fixed_shunts`, `n_hvdc_links`,
  `n_hvdc_dc_grids`, `n_areas`, `n_zones`.
- Totals: `total_generation_mw`, `total_generation_capacity_mw`,
  `total_load_mw`, `total_load_mvar`, `base_mva`, `freq_hz`.
- Sets: `areas`, `zones`, `voltage_levels_kv`.
- Metadata: `name`.

## Power flow

### `run_ac_power_flow(flat_start=False, enforce_q_limits=False, max_iterations=30, tolerance=1e-8)`
Newton-Raphson AC power flow. Return fields include `converged`,
`iterations`, `max_mismatch`, `solve_time_secs`, `vm`, `va_rad`,
`va_deg`, `bus_numbers`.

### `run_dc_power_flow(headroom_slack=False)`
Lossless linearized DC power flow. Set `headroom_slack=True` to
distribute slack across all online generators weighted by headroom.

### `run_fast_decoupled_pf(variant="xb")`
Fast-decoupled AC. `variant="xb"` is Stott & Alsac's original;
`"bx"` is the Van Amerongen variant that handles high-R/X lines
better.

## DC sensitivities

All three tools support `format="summary" | "sparse" | "full"`.
`summary` is the default and is safe for networks of any size.

### `compute_ptdf(monitored_branches=None, format="summary", top_k_per_branch=10)`
Power Transfer Distribution Factors. Returns the distribution factor
matrix in the chosen format plus `bus_numbers` and
`monitored_branch_keys`.

### `compute_lodf(outage_branches=None, monitored_branches=None, format="summary", top_k_per_branch=10)`
Line Outage Distribution Factors. Omit both branch-set arguments to
get the full rectangular result.

### `compute_otdf(outage_branches, monitored_branches, format="summary", top_k_per_pair=10)`
Outage Transfer Distribution Factors — 3-D tensor
`(n_monitored, n_outages, n_buses)`. `"full"` is refused because the
dense tensor is almost always impractical; use `"summary"` for a
bounded top-k-per-pair drill-down or `"sparse"` for a coordinate
list of non-zero entries.

## OPF

Each OPF tool accepts a solver-selection string. `"default"` lets
surge auto-detect the best available backend.

### `run_dc_opf(lp_solver="default")`
DC optimal power flow. `lp_solver` options: `"default"`, `"highs"`,
`"gurobi"`, `"copt"`, `"cplex"`.

### `run_ac_opf(nlp_solver="default")`
AC optimal power flow. `nlp_solver` options: `"default"`, `"ipopt"`,
`"copt"`, `"gurobi"`.

### `run_scopf(lp_solver="default", nlp_solver="default")`
Security-constrained OPF with N-1 contingency screening. Both solver
backends configurable independently.

## Contingency

### `run_n1_branch_contingency(monitored_branches=None)`
Standard N-1 branch outage sweep. Returns `n_contingencies`,
`n_converged`, `n_with_violations`, `n_violations`, plus per-case
`results` and a flat `violations` list.

### `run_n1_generator_contingency()`
N-1 generator outage sweep.

### `run_n2_branch_contingency()`
All-pairs N-2 branch contingency.

Violation shapes in the `violations` list include: `ThermalOverload`,
`VoltageLow`, `VoltageHigh`, `NonConvergent`, `Islanding`,
`FlowgateOverload:<name>`, `InterfaceOverload:<name>`.

## Transfer capability

### `compute_nerc_atc(source_buses, sink_buses, name="atc", trm_fraction=0.05, cbm_mw=0.0, etc_mw=0.0)`
NERC MOD-029 / MOD-030 Available Transfer Capability. Returns
`atc_mw`, `ttc_mw`, `trm_mw`, `cbm_mw`, `etc_mw`, `limit_cause`,
`binding_branch`, `binding_contingency`, `monitored_branches`,
`reactive_margin_warning`, `transfer_ptdf`.

### `compute_ac_atc(source_buses, sink_buses, name="ac-atc", v_min=0.95, v_max=1.05)`
AC-aware ATC with reactive-margin limits. Returns `atc_mw`,
`thermal_limit_mw`, `voltage_limit_mw`, `limiting_bus`,
`binding_branch`, `limiting_constraint`.

## Dispatch

### `run_sced(request=None, lp_solver="default")`
Single-period SCED. When `request=None`, a default DC SCED with all
generators committed is run.

### `run_scuc(request=None, lp_solver="default")`
Multi-period unit commitment. A dispatch request describing the time
horizon and commitment decisions is required for a real SCUC problem;
`request=None` falls back to a single-period LP with all generators
committed.

## Inspection

### `list_buses(limit=None, sort_by=None, ascending=True)`
Enumerate bus rows as records. Typical `sort_by` values: `base_kv`,
`vm_pu`, `pd_mw`, `area`. Use `limit` to cap agent-visible volume.

### `list_branches(limit=None, sort_by=None, ascending=True)`
Enumerate branch rows. Typical `sort_by` values: `rate_a_mva`, `x`,
`from_bus`. Combine with `limit=20` and `sort_by="rate_a_mva"` /
`ascending=False` to surface the highest-rated branches first.

## Export & graph analytics

### `export_tables(output_dir)`
Write per-element CSVs (`buses.csv`, `branches.csv`, `generators.csv`,
`loads.csv`, `shunts.csv`) to `output_dir`. Creates the directory if
missing. Returns `{files: [...], rows: {csvname: int, ...}}`.

### `get_topology(as_networkx=False, in_service_only=True)`
Return `{nodes, edges}`. `edges` entries have `from`, `to`, `circuit`,
`is_transformer`, `in_service`. With `as_networkx=True` also includes
`networkx_repr` (adjacency dict for `networkx.from_dict_of_lists`).

### `find_path(from_bus, to_bus, in_service_only=True)`
BFS shortest path by branch count. Returns
`{path: [...] | None, length: int, connected: bool}`. Use
`compute_ptdf` for electrical distance.

### `get_islands()`
Return `{n_islands: int, islands: [[bus, ...], ...]}`, largest first.

### `get_dispatch_request_schema()`
JSON schema for the `run_sced` / `run_scuc` `request` argument. Emitted
from Rust `surge_dispatch::DispatchRequest` via `schemars`. Also
bundled at `surge/references/DISPATCH_REQUEST_SCHEMA.json`.

## Network construction & editing

Re-solve `run_ac_power_flow` after any material edit before reporting
downstream results.

### `create_empty_network(name="", base_mva=100.0, freq_hz=60.0)`
Create a new empty network and make it active.

### `add_bus(number, bus_type, base_kv, name="", pd_mw=0.0, qd_mvar=0.0, vm_pu=1.0, va_deg=0.0)`
Add a bus. `bus_type` is one of `"PQ"`, `"PV"`, `"Slack"`, `"Isolated"`.

### `add_generator(bus, p_mw, pmax_mw, pmin_mw=0.0, vs_pu=1.0, qmax_mvar=9999.0, qmin_mvar=-9999.0, machine_id="1", id=None)`
Add a generator at a bus. Auto-assigns an `id` like `gen_{bus}_{n}` when
omitted. Returns `{id: "<canonical id>"}`.

### `add_load(bus, pd_mw, qd_mvar, load_id="1", conforming=True)`
Add a discrete load record. Multiple loads per bus are distinguished by
`load_id`.

### `add_line(from_bus, to_bus, r_ohm_per_km, x_ohm_per_km, b_us_per_km, length_km, base_kv, rate_a_mva=0.0, circuit=1)`
Add a transmission line from physical conductor parameters. Surge does
the per-unit conversion internally (`z_base = base_kv² / base_mva`).

### `add_transformer(from_bus, to_bus, mva_rating, v1_kv, v2_kv, z_percent, r_percent=0.5, tap_pu=1.0, shift_deg=0.0, rate_a_mva=0.0, circuit=1)`
Add a transformer from nameplate data. Percent impedance on the
transformer's own MVA base is converted to p.u. on the system base.

### `add_storage(bus, charge_mw_max, discharge_mw_max, energy_capacity_mwh, efficiency=0.9, soc_initial_mwh=None, machine_id="1", id=None)`
Add a BESS / pumped-hydro resource as a bidirectional generator with
`StorageParams`. `pmin = -charge_mw_max`, `pmax = discharge_mw_max`.

### `remove_bus(number)` / `remove_branch(from_bus, to_bus, circuit=1)` / `remove_generator(id)` / `remove_load(bus, load_id="1")`
Delete an element. `remove_bus` also deletes branches, generators, and
loads anchored there.

### `set_branch_rating(from_bus, to_bus, rate_a_mva, circuit=1)`
Adjust a branch's long-term thermal rating.

### `set_branch_in_service(from_bus, to_bus, in_service, circuit=1)`
Open / close a branch — the primary outage-simulation primitive.

### `set_generator_limits(id, pmax_mw, pmin_mw)` / `set_generator_in_service(id, in_service)`
Change a generator's MW limits or availability.

### `scale_loads(factor, area=None)` / `scale_generators(factor, area=None)`
Bulk scale. Use for forecast uplift / downrate scenarios. `area` scopes
the scaling to a single area number.

## Return conventions

- Success: `{"status": "success", "message": str, "results": {...}}`
- Error:   `{"status": "error", "message": str}`

Always branch on `status` before reading `results`.
