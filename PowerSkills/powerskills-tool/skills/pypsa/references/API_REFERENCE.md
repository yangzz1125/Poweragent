# PyPSA API Reference

> Quick-reference for PyPSA data structures, component types, and key methods.
> Organized to mirror the SKILL.md progression: network data → power flow → optimization → creation → expansion.

---

## Network Object

A PyPSA `Network` is the central object containing all component DataFrames and methods.

```python
import pypsa
network = pypsa.Network()
```

### Key Attributes

| Attribute | Type | Description |
|---|---|---|
| `network.snapshots` | DatetimeIndex | Time steps for optimization/simulation |
| `network.buses` | DataFrame | Bus/node data |
| `network.generators` | DataFrame | Generator data |
| `network.loads` | DataFrame | Load data |
| `network.lines` | DataFrame | AC transmission lines |
| `network.transformers` | DataFrame | Transformers |
| `network.links` | DataFrame | Generic links (DC lines, sector coupling) |
| `network.storage_units` | DataFrame | Storage units |
| `network.stores` | DataFrame | Energy stores |

---

## Component Types

### Bus

| Column | Type | Unit | Description |
|---|---|---|---|
| `v_nom` | float | kV | Nominal voltage |
| `v_mag_pu_set` | float | p.u. | Voltage magnitude setpoint |
| `v_mag_pu_min` | float | p.u. | Minimum voltage magnitude |
| `v_mag_pu_max` | float | p.u. | Maximum voltage magnitude |
| `x` | float | deg | Longitude (for plotting) |
| `y` | float | deg | Latitude (for plotting) |
| `carrier` | str | - | Energy carrier |

**Result columns** (after power flow):
- `v_mag_pu` -- voltage magnitude (p.u.)
- `v_ang` -- voltage angle (rad)
- `marginal_price` -- locational marginal price (currency/MWh)

### Generator

| Column | Type | Unit | Description |
|---|---|---|---|
| `bus` | str | - | Bus name |
| `carrier` | str | - | Energy carrier/technology |
| `p_nom` | float | MW | Nominal power capacity |
| `p_nom_extendable` | bool | - | Can capacity be expanded? |
| `p_nom_min` | float | MW | Minimum capacity (if extendable) |
| `p_nom_max` | float | MW | Maximum capacity (if extendable) |
| `capital_cost` | float | currency/MW | Annualized investment cost |
| `marginal_cost` | float | currency/MWh | Variable generation cost |
| `efficiency` | float | p.u. | Conversion efficiency |
| `committable` | bool | - | Unit commitment constraints? |
| `p_min_pu` | float | p.u. | Minimum stable generation |
| `p_max_pu` | float/series | p.u. | Maximum available power (time series for renewables) |

**Result columns** (after optimization):
- `p` -- active power dispatch (MW)
- `p_nom_opt` -- optimal capacity (MW, if extendable)

### Load

| Column | Type | Unit | Description |
|---|---|---|---|
| `bus` | str | - | Bus name |
| `p_set` | float/series | MW | Active power demand (time series) |
| `q_set` | float/series | Mvar | Reactive power demand |

### Line

| Column | Type | Unit | Description |
|---|---|---|---|
| `bus0` | str | - | From bus |
| `bus1` | str | - | To bus |
| `x` | float | ohm | Series reactance |
| `r` | float | ohm | Series resistance |
| `b` | float | S | Shunt susceptance |
| `s_nom` | float | MVA | Thermal rating |
| `s_nom_extendable` | bool | - | Can capacity be expanded? |
| `capital_cost` | float | currency/MVA | Investment cost |
| `length` | float | km | Line length |

**Result columns**:
- `p0`, `p1` -- active power at bus0/bus1 (MW)
- `q0`, `q1` -- reactive power at bus0/bus1 (Mvar)
- `s_nom_opt` -- optimal capacity (MVA, if extendable)
- `mu_lower`, `mu_upper` -- shadow prices (congestion pricing)

### Link

Generic point-to-point connection (DC lines, sector coupling, power-to-X).

| Column | Type | Unit | Description |
|---|---|---|---|
| `bus0` | str | - | From bus |
| `bus1` | str | - | To bus |
| `efficiency` | float | p.u. | Conversion efficiency |
| `p_nom` | float | MW | Nominal capacity |
| `p_nom_extendable` | bool | - | Can capacity be expanded? |
| `capital_cost` | float | currency/MW | Investment cost |
| `marginal_cost` | float | currency/MWh | Variable cost |
| `p_min_pu` | float | p.u. | Minimum operation |
| `p_max_pu` | float | p.u. | Maximum operation |

**Result columns**:
- `p0` -- power at bus0 (MW, positive = flowing into link)
- `p1` -- power at bus1 (MW, = -efficiency * p0)
- `p_nom_opt` -- optimal capacity (MW, if extendable)

### StorageUnit

Storage with separate power and energy ratings (e.g., battery, pumped hydro).

| Column | Type | Unit | Description |
|---|---|---|---|
| `bus` | str | - | Bus name |
| `carrier` | str | - | Energy carrier |
| `p_nom` | float | MW | Power capacity |
| `p_nom_extendable` | bool | - | Can capacity be expanded? |
| `max_hours` | float | h | Energy capacity (MWh/MW ratio) |
| `efficiency_store` | float | p.u. | Charging efficiency |
| `efficiency_dispatch` | float | p.u. | Discharging efficiency |
| `standing_loss` | float | 1/h | Self-discharge rate |
| `capital_cost` | float | currency/MW | Investment cost |
| `marginal_cost` | float | currency/MWh | Variable cost |

**Result columns**:
- `p` -- power (MW, positive = discharge, negative = charge)
- `state_of_charge` -- energy stored (MWh)
- `p_nom_opt` -- optimal capacity (MW, if extendable)

### Store

Pure energy storage (e.g., hydrogen tank, thermal storage).

| Column | Type | Unit | Description |
|---|---|---|---|
| `bus` | str | - | Bus name |
| `carrier` | str | - | Energy carrier |
| `e_nom` | float | MWh | Energy capacity |
| `e_nom_extendable` | bool | - | Can capacity be expanded? |
| `e_min_pu` | float | p.u. | Minimum state of charge |
| `e_max_pu` | float | p.u. | Maximum state of charge |
| `e_initial` | float | MWh | Initial energy level |
| `e_cyclic` | bool | - | Cyclic constraint (end = start)? |
| `capital_cost` | float | currency/MWh | Investment cost |
| `standing_loss` | float | 1/h | Self-discharge rate |

**Result columns**:
- `e` -- energy stored (MWh)
- `e_nom_opt` -- optimal capacity (MWh, if extendable)
- `p` -- power flow (MW, via connected links)

---

## Key Network Methods

### File I/O

```python
# Import from CSV folder
network.import_from_csv_folder("folder_path/")

# Export to CSV folder
network.export_to_csv_folder("folder_path/")

# Load from NetCDF (recommended for large networks)
network = pypsa.Network("network.nc")

# Save to NetCDF
network.export_to_netcdf("network.nc")
```

### Network Creation

```python
# Create empty network
network = pypsa.Network()

# Set time snapshots
import pandas as pd
network.set_snapshots(pd.date_range('2023-01-01', periods=8760, freq='h'))

# Add components
network.add("Bus", name, **kwargs)
network.add("Generator", name, bus=bus_name, **kwargs)
network.add("Load", name, bus=bus_name, p_set=time_series)
network.add("Line", name, bus0=bus0, bus1=bus1, **kwargs)
network.add("Link", name, bus0=bus0, bus1=bus1, **kwargs)
network.add("StorageUnit", name, bus=bus_name, **kwargs)
network.add("Store", name, bus=bus_name, **kwargs)
```

### Power Flow Simulation

```python
# Linear (DC) power flow
network.lpf()

# Nonlinear (AC) power flow (Newton-Raphson)
network.pf()

# Access results
network.buses_t.v_mag_pu   # voltage magnitudes
network.buses_t.v_ang      # voltage angles
network.lines_t.p0         # line power flows
```

### Optimization

```python
# Basic optimization
network.optimize()

# With solver options
network.optimize(
    solver_name='gurobi',     # 'gurobi', 'cplex', 'highs', 'glpk'
    solver_options={'LogToConsole': 0}
)

# For specific snapshots
network.optimize(snapshots=network.snapshots[:24])

# Access results
network.objective                    # total cost
network.generators_t.p              # generator dispatch
network.buses_t.marginal_price      # nodal prices
network.status                      # optimization status
```

### Capacity Expansion

```python
# Set components as extendable
network.generators.loc['wind', 'p_nom_extendable'] = True
network.generators.loc['wind', 'capital_cost'] = 1000  # €/MW/year

network.lines.loc['line0-1', 's_nom_extendable'] = True
network.lines.loc['line0-1', 'capital_cost'] = 400

# Optimize
network.optimize()

# Check optimal capacities
network.generators.p_nom_opt
network.lines.s_nom_opt
```

### Multi-Period Planning

```python
# Set investment periods
network.set_investment_periods(periods=[2025, 2030, 2035, 2040])

# Time-varying parameters
network.generators_t.capital_cost  # different costs per period

# Optimize pathway
network.optimize()
```

### Built-in Examples

```python
import pypsa

network = pypsa.examples.ac_dc_meshed()
network = pypsa.examples.storage_hvdc()
network = pypsa.examples.scigrid_de()
```

---

## Time Series Data

Components can have time-varying parameters stored in `component_t` attributes:

```python
# Time series for loads
network.loads_t.p_set[load_name]

# Time series for renewable availability
network.generators_t.p_max_pu[gen_name]

# Time series results after optimization
network.generators_t.p[gen_name]        # dispatch
network.buses_t.marginal_price[bus_name]  # LMPs
network.storage_units_t.state_of_charge[storage_name]
```

---

## Useful Functions

```python
# Check network consistency
network.consistency_check()

# Calculate total load/generation
network.loads_t.p_set.sum(axis=1)  # total load per snapshot
network.generators_t.p.sum(axis=1)  # total generation per snapshot

# Group by carrier
network.generators.groupby('carrier')['p_nom'].sum()

# Calculate emissions (if co2_emissions defined)
(network.generators_t.p * network.generators.co2_emissions).sum().sum()
```
