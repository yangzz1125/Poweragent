# Pandapower API Reference

> Quick-reference for pandapower data structures, result tables, and key functions.
> Organized to mirror the SKILL.md progression: network data -> power flow -> creation -> advanced.

---

## Network Data Structure

A pandapower network (`pandapowerNet`) is a dictionary-like object containing pandas DataFrames for each element type.

### Element Tables at a Glance

| Table | Description |
|---|---|
| `net.bus` | Bus/node data |
| `net.line` | AC transmission/distribution lines |
| `net.trafo` | Two-winding transformers |
| `net.trafo3w` | Three-winding transformers |
| `net.load` | Loads (PQ) |
| `net.gen` | Generators (PV) |
| `net.sgen` | Static generators |
| `net.ext_grid` | External grid connections (slack) |
| `net.shunt` | Shunt elements |
| `net.switch` | Switches |
| `net.storage` | Energy storage |

---

## Element Table Columns

### Bus (`net.bus`)

| Column | Type | Unit | Description |
|---|---|---|---|
| `name` | str | - | Bus name |
| `vn_kv` | float | kV | Nominal voltage |
| `type` | str | - | Bus type: `'b'` (busbar), `'n'` (node) |
| `zone` | str | - | Zone identifier |
| `in_service` | bool | - | Service status |

### Line (`net.line`)

| Column | Type | Unit | Description |
|---|---|---|---|
| `name` | str | - | Line name |
| `from_bus` | int | - | From bus index |
| `to_bus` | int | - | To bus index |
| `length_km` | float | km | Line length |
| `r_ohm_per_km` | float | ohm/km | Resistance per km |
| `x_ohm_per_km` | float | ohm/km | Reactance per km |
| `c_nf_per_km` | float | nF/km | Capacitance per km |
| `max_i_ka` | float | kA | Maximum current rating |
| `std_type` | str | - | Standard type name |
| `in_service` | bool | - | Service status |

### Transformer (`net.trafo`)

| Column | Type | Unit | Description |
|---|---|---|---|
| `name` | str | - | Transformer name |
| `hv_bus` | int | - | High voltage bus index |
| `lv_bus` | int | - | Low voltage bus index |
| `sn_mva` | float | MVA | Rated apparent power |
| `vn_hv_kv` | float | kV | HV side nominal voltage |
| `vn_lv_kv` | float | kV | LV side nominal voltage |
| `vk_percent` | float | % | Short circuit voltage |
| `vkr_percent` | float | % | Real part of vk |
| `pfe_kw` | float | kW | Iron losses |
| `i0_percent` | float | % | No-load current |
| `tap_pos` | int | - | Current tap position |
| `in_service` | bool | - | Service status |

### Load (`net.load`)

| Column | Type | Unit | Description |
|---|---|---|---|
| `name` | str | - | Load name |
| `bus` | int | - | Bus index |
| `p_mw` | float | MW | Active power |
| `q_mvar` | float | Mvar | Reactive power |
| `scaling` | float | - | Scaling factor |
| `in_service` | bool | - | Service status |

### Generator (`net.gen`)

| Column | Type | Unit | Description |
|---|---|---|---|
| `name` | str | - | Generator name |
| `bus` | int | - | Bus index |
| `p_mw` | float | MW | Active power setpoint |
| `vm_pu` | float | p.u. | Voltage magnitude setpoint |
| `min_q_mvar` | float | Mvar | Minimum reactive power |
| `max_q_mvar` | float | Mvar | Maximum reactive power |
| `slack` | bool | - | Slack generator flag |
| `in_service` | bool | - | Service status |

### External Grid (`net.ext_grid`)

| Column | Type | Unit | Description |
|---|---|---|---|
| `name` | str | - | Name |
| `bus` | int | - | Bus index |
| `vm_pu` | float | p.u. | Voltage magnitude setpoint |
| `va_degree` | float | deg | Voltage angle setpoint |
| `in_service` | bool | - | Service status |

---

## Result Tables

After running `pp.runpp(net)`, results are stored in `res_*` DataFrames.

### Bus Results (`net.res_bus`)

| Column | Unit | Description |
|---|---|---|
| `vm_pu` | p.u. | Voltage magnitude |
| `va_degree` | deg | Voltage angle |
| `p_mw` | MW | Active power injection |
| `q_mvar` | Mvar | Reactive power injection |

### Line Results (`net.res_line`)

| Column | Unit | Description |
|---|---|---|
| `p_from_mw` | MW | Active power at from bus |
| `q_from_mvar` | Mvar | Reactive power at from bus |
| `p_to_mw` | MW | Active power at to bus |
| `q_to_mvar` | Mvar | Reactive power at to bus |
| `pl_mw` | MW | Active power losses |
| `ql_mvar` | Mvar | Reactive power losses |
| `i_from_ka` | kA | Current at from bus |
| `i_to_ka` | kA | Current at to bus |
| `i_ka` | kA | Maximum current |
| `loading_percent` | % | Line loading |

### Transformer Results (`net.res_trafo`)

| Column | Unit | Description |
|---|---|---|
| `p_hv_mw` | MW | Active power at HV side |
| `q_hv_mvar` | Mvar | Reactive power at HV side |
| `p_lv_mw` | MW | Active power at LV side |
| `q_lv_mvar` | Mvar | Reactive power at LV side |
| `pl_mw` | MW | Active power losses |
| `ql_mvar` | Mvar | Reactive power losses |
| `i_hv_ka` | kA | Current at HV side |
| `i_lv_ka` | kA | Current at LV side |
| `loading_percent` | % | Transformer loading |

### Generator Results (`net.res_gen`)

| Column | Unit | Description |
|---|---|---|
| `p_mw` | MW | Active power output |
| `q_mvar` | Mvar | Reactive power output |
| `va_degree` | deg | Voltage angle |
| `vm_pu` | p.u. | Voltage magnitude |

### External Grid Results (`net.res_ext_grid`)

| Column | Unit | Description |
|---|---|---|
| `p_mw` | MW | Active power from grid |
| `q_mvar` | Mvar | Reactive power from grid |

---

## Key Functions

### File I/O

```python
net = pp.from_json(filename)        # load from JSON
pp.to_json(net, filename)           # save to JSON

net = pp.from_pickle(filename)      # load from pickle
pp.to_pickle(net, filename)         # save to pickle

net = pp.from_excel(filename)       # load from Excel
pp.to_excel(net, filename)          # save to Excel
```

### Network Creation

```python
pp.create_empty_network(name="", f_hz=50.0, sn_mva=1)
```

### Element Creation

```python
pp.create_bus(net, vn_kv, name=None, index=None, type='b', zone=None, in_service=True)

pp.create_line(net, from_bus, to_bus, length_km, std_type, name=None, index=None,
               df=1.0, parallel=1, in_service=True)

pp.create_line_from_parameters(net, from_bus, to_bus, length_km, r_ohm_per_km,
                                x_ohm_per_km, c_nf_per_km, max_i_ka, ...)

pp.create_transformer(net, hv_bus, lv_bus, std_type, name=None, tap_pos=None,
                       in_service=True, index=None)

pp.create_load(net, bus, p_mw, q_mvar=0, const_z_percent=0, const_i_percent=0,
               name=None, scaling=1.0, in_service=True)

pp.create_gen(net, bus, p_mw, vm_pu=1.0, name=None, min_q_mvar=None,
              max_q_mvar=None, scaling=1.0, slack=False, in_service=True)

pp.create_ext_grid(net, bus, vm_pu=1.0, va_degree=0, name=None, in_service=True)

pp.create_shunt(net, bus, q_mvar, p_mw=0, vn_kv=None, step=1, max_step=1,
                name=None, in_service=True)

pp.create_switch(net, bus, element, et, closed=True, type=None, name=None, z_ohm=0)
```

### Power Flow

```python
pp.runpp(net, algorithm='nr', calculate_voltage_angles=True, init='auto',
         max_iteration=10, tolerance_mva=1e-8, trafo_model='t',
         trafo_loading='current', enforce_q_lims=False, ...)
```

| Parameter | Options | Description |
|---|---|---|
| `algorithm` | `'nr'`, `'bfsw'`, `'gs'` | Newton-Raphson, backward/forward sweep, Gauss-Seidel |
| `init` | `'auto'`, `'flat'`, `'dc'`, `'results'` | Voltage initialization method |
| `trafo_model` | `'t'`, `'pi'` | T-equivalent or pi-equivalent model |
| `trafo_loading` | `'current'`, `'power'` | Loading calculation basis |

### DC Power Flow

```python
pp.rundcpp(net, trafo_model='t', trafo_loading='current', ...)
```

### Optimal Power Flow

```python
pp.runopp(net, verbose=False, calculate_voltage_angles=True, ...)
```

### Standard Test Networks

```python
pp.networks.case4gs()       pp.networks.case5()
pp.networks.case6ww()       pp.networks.case9()
pp.networks.case14()        pp.networks.case_ieee30()
pp.networks.case33bw()      pp.networks.case39()
pp.networks.case57()        pp.networks.case118()
pp.networks.case300()       pp.networks.GBnetwork()
pp.networks.iceland()
```

### Topology

```python
pp.topology.unsupplied_buses(net)          # buses with no supply path
pp.topology.connected_component(net, bus)  # component containing a bus
pp.topology.connected_components(net)      # all connected components
```

### Short Circuit

```python
pp.shortcircuit.calc_sc(net, bus=None, fault='3ph', case='max', ...)
```
