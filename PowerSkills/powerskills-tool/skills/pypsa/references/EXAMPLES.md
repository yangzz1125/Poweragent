# PyPSA Examples

> Worked examples organized from basic to advanced.
> Each example is self-contained and can be run independently.

---

## Network Inspection

### Example 1: Load and Inspect a Network

```python
import pypsa

# Load a built-in example network
network = pypsa.examples.ac_dc_meshed()

# Network overview
print(f"Network name: {network.name}")
print(f"Snapshots: {len(network.snapshots)}")
print(f"Buses: {len(network.buses)}")
print(f"Generators: {len(network.generators)}")
print(f"Loads: {len(network.loads)}")
print(f"Lines: {len(network.lines)}")
print(f"Links: {len(network.links)}")

# Capacity by carrier
capacity_by_carrier = network.generators.groupby('carrier')['p_nom'].sum()
print("\nInstalled capacity by carrier:")
print(capacity_by_carrier)

# Total load
total_load = network.loads_t.p_set.sum().sum()
print(f"\nTotal load: {total_load:.1f} MWh")
```

### Example 2: Save and Load a Network

```python
import pypsa

# Create and modify a network
network = pypsa.examples.ac_dc_meshed()
network.add("Generator", "new_solar",
            bus="Manchester",
            carrier="solar",
            p_nom=100,
            marginal_cost=0)

# Save to NetCDF (recommended)
network.export_to_netcdf("my_network.nc")
print("Network saved to my_network.nc")

# Load from file
loaded_network = pypsa.Network("my_network.nc")
print(f"Loaded network has {len(loaded_network.generators)} generators")
```

---

## Power Flow Simulation

### Example 3: Run Linear Power Flow

```python
import pypsa

network = pypsa.examples.ac_dc_meshed()

# Run linear (DC) power flow
network.lpf()

print("Linear power flow completed")
print("\n=== Bus Voltage Angles ===")
print(network.buses_t.v_ang)

print("\n=== Line Power Flows ===")
print(network.lines_t.p0)
```

### Example 4: Run Nonlinear Power Flow

```python
import pypsa

network = pypsa.examples.ac_dc_meshed()

# Run AC power flow
network.pf()

print("AC power flow completed")
print("\n=== Bus Voltage Magnitudes ===")
print(network.buses_t.v_mag_pu)

print("\n=== Line Active Power Flows ===")
print(network.lines_t.p0)

print("\n=== Line Reactive Power Flows ===")
print(network.lines_t.q0)
```

---

## Optimization

### Example 5: Basic Dispatch Optimization

```python
import pypsa

network = pypsa.examples.ac_dc_meshed()

# Run optimal power flow
network.optimize()

print(f"Optimization status: {network.status['status']}")
print(f"Total cost: €{network.objective:,.0f}")

print("\n=== Generation by Carrier ===")
gen_by_carrier = {}
for gen in network.generators.index:
    carrier = network.generators.at[gen, 'carrier']
    generation = network.generators_t.p[gen].sum()
    gen_by_carrier[carrier] = gen_by_carrier.get(carrier, 0) + generation

for carrier, gen in sorted(gen_by_carrier.items(), key=lambda x: x[1], reverse=True):
    print(f"{carrier:15s}: {gen:>10.1f} MWh")

print("\n=== Locational Marginal Prices ===")
print(network.buses_t.marginal_price)
```

### Example 6: Identify Line Congestion

```python
import pypsa

network = pypsa.examples.ac_dc_meshed()
network.optimize()

print("=== Congested Lines ===")

for line in network.lines.index:
    # Line power flow
    p_flow = network.lines_t.p0[line].abs()
    s_nom = network.lines.at[line, 's_nom']
    
    # Calculate loading
    loading = (p_flow / s_nom * 100)
    max_loading = loading.max()
    
    # Check for congestion (loading > 95%)
    congested_hours = (loading > 95).sum()
    
    if congested_hours > 0:
        print(f"\n{line}:")
        print(f"  Max loading: {max_loading:.1f}%")
        print(f"  Congested hours: {congested_hours}")
        
        # Check shadow price (congestion price)
        if line in network.lines_t.mu_lower.columns:
            mu = network.lines_t.mu_lower[line]
            if mu.abs().max() > 0.01:
                print(f"  Max shadow price: €{mu.abs().max():.2f}/MWh")
```

### Example 7: Calculate Renewable Curtailment

```python
import pypsa

network = pypsa.examples.ac_dc_meshed()
network.optimize()

print("=== Renewable Curtailment ===\n")

total_available = 0
total_used = 0

for gen in network.generators.index:
    # Check if generator has availability profile
    if gen not in network.generators_t.p_max_pu.columns:
        continue
    
    p_nom = network.generators.at[gen, 'p_nom']
    carrier = network.generators.at[gen, 'carrier']
    
    # Available generation
    available = (network.generators_t.p_max_pu[gen] * p_nom).sum()
    
    # Actual generation
    used = network.generators_t.p[gen].sum()
    
    # Curtailment
    curtailed = available - used
    curtailment_rate = curtailed / available if available > 0 else 0
    
    if curtailment_rate > 0.01:  # Show if > 1%
        print(f"{gen} ({carrier}):")
        print(f"  Available:  {available:.1f} MWh")
        print(f"  Used:       {used:.1f} MWh")
        print(f"  Curtailed:  {curtailed:.1f} MWh ({curtailment_rate*100:.1f}%)\n")
        
        total_available += available
        total_used += used

total_curtailed = total_available - total_used
total_rate = total_curtailed / total_available if total_available > 0 else 0
print(f"Total curtailment: {total_curtailed:.1f} MWh ({total_rate*100:.1f}%)")
```

---

## Network Creation

### Example 8: Build a 3-Node Network

```python
import pypsa
import pandas as pd

# Create empty network
network = pypsa.Network()

# Set time snapshots (24 hours)
network.set_snapshots(pd.date_range('2023-01-01', periods=24, freq='h'))

# Add buses
network.add("Bus", "bus0", v_nom=380, x=0, y=0)
network.add("Bus", "bus1", v_nom=380, x=1, y=0)
network.add("Bus", "bus2", v_nom=380, x=0.5, y=1)

# Add generators
network.add("Generator", "coal", bus="bus0", carrier="coal",
            p_nom=400, marginal_cost=30)

network.add("Generator", "gas", bus="bus1", carrier="gas",
            p_nom=300, marginal_cost=50)

# Wind with availability profile
wind_profile = pd.Series([0.2, 0.3, 0.5, 0.7, 0.8, 0.9, 0.95, 0.9,
                          0.8, 0.7, 0.5, 0.3, 0.2, 0.1, 0.05, 0.1,
                          0.2, 0.3, 0.4, 0.5, 0.6, 0.5, 0.4, 0.3],
                         index=network.snapshots)

network.add("Generator", "wind", bus="bus2", carrier="wind",
            p_nom=200, marginal_cost=0,
            p_max_pu=wind_profile)

# Add loads
load_profile = pd.Series([300, 280, 270, 260, 250, 260, 280, 320,
                          380, 420, 450, 460, 450, 440, 430, 420,
                          440, 480, 500, 490, 460, 420, 380, 340],
                         index=network.snapshots)

network.add("Load", "load0", bus="bus0", p_set=load_profile * 0.3)
network.add("Load", "load1", bus="bus1", p_set=load_profile * 0.3)
network.add("Load", "load2", bus="bus2", p_set=load_profile * 0.4)

# Add transmission lines
network.add("Line", "line0-1", bus0="bus0", bus1="bus1",
            x=0.1, s_nom=300)
network.add("Line", "line0-2", bus0="bus0", bus1="bus2",
            x=0.15, s_nom=250)
network.add("Line", "line1-2", bus0="bus1", bus1="bus2",
            x=0.12, s_nom=250)

# Optimize and display results
network.optimize()
print(f"Optimization status: {network.status['status']}")
print(f"Total cost: €{network.objective:,.0f}")

# Save network
network.export_to_netcdf("3node_network.nc")
```

---

## Capacity Expansion

### Example 9: Optimize Generator Capacity

```python
import pypsa
import pandas as pd

# Create network
network = pypsa.Network()
network.set_snapshots(pd.date_range('2023-01-01', periods=8760, freq='h'))

# Add buses
network.add("Bus", "region1", v_nom=380)

# Add extendable generators with different costs
network.add("Generator", "coal",
            bus="region1",
            carrier="coal",
            p_nom=0,  # Start with zero capacity
            p_nom_extendable=True,
            p_nom_max=1000,
            capital_cost=60000,   # €/MW/year
            marginal_cost=30)     # €/MWh

network.add("Generator", "solar",
            bus="region1",
            carrier="solar",
            p_nom=0,
            p_nom_extendable=True,
            p_nom_max=2000,
            capital_cost=50000,
            marginal_cost=0,
            p_max_pu=0.2)  # Simplified 20% capacity factor

network.add("Generator", "wind",
            bus="region1",
            carrier="wind",
            p_nom=0,
            p_nom_extendable=True,
            p_nom_max=2000,
            capital_cost=100000,
            marginal_cost=0,
            p_max_pu=0.35)  # Simplified 35% capacity factor

# Add load (8760 hours, average 500 MW)
load_profile = 500 + 200 * pd.Series(range(8760), index=network.snapshots).apply(
    lambda x: 0.5 * (1 + pd.np.sin(2 * pd.np.pi * x / 24))
)
network.add("Load", "demand", bus="region1", p_set=load_profile)

# Optimize
network.optimize()

print("=== Optimal Capacity Mix ===")
for gen in network.generators.index:
    p_nom_opt = network.generators.at[gen, 'p_nom_opt']
    carrier = network.generators.at[gen, 'carrier']
    capital_cost = network.generators.at[gen, 'capital_cost']
    investment = p_nom_opt * capital_cost
    print(f"\n{carrier}:")
    print(f"  Capacity: {p_nom_opt:.0f} MW")
    print(f"  Investment: €{investment:,.0f}")

print(f"\nTotal system cost: €{network.objective:,.0f}")
```

### Example 10: Transmission Expansion

```python
import pypsa
import pandas as pd

# Create 2-region network
network = pypsa.Network()
network.set_snapshots(pd.date_range('2023-01-01', periods=168, freq='h'))  # 1 week

# Regions with different resources
network.add("Bus", "north", v_nom=380)  # Good wind
network.add("Bus", "south", v_nom=380)  # Good solar

# North: Abundant wind, high demand
network.add("Generator", "wind_north", bus="north", carrier="wind",
            p_nom=500, marginal_cost=0,
            p_max_pu=0.4)  # 40% capacity factor

network.add("Load", "demand_north", bus="north",
            p_set=pd.Series(400, index=network.snapshots))

# South: Abundant solar, low demand
network.add("Generator", "solar_south", bus="south", carrier="solar",
            p_nom=600, marginal_cost=0,
            p_max_pu=0.25)  # 25% capacity factor

network.add("Load", "demand_south", bus="south",
            p_set=pd.Series(100, index=network.snapshots))

# Extendable transmission line
network.add("Line", "north-south",
            bus0="north",
            bus1="south",
            x=0.1,
            s_nom=0,  # Start with zero capacity
            s_nom_extendable=True,
            s_nom_max=500,
            capital_cost=400)  # €/MVA

# Optimize
network.optimize()

s_nom_opt = network.lines.at['north-south', 's_nom_opt']
investment = s_nom_opt * network.lines.at['north-south', 'capital_cost']

print(f"=== Transmission Expansion Results ===")
print(f"Optimal line capacity: {s_nom_opt:.0f} MVA")
print(f"Investment cost: €{investment:,.0f}")
print(f"Total system cost: €{network.objective:,.0f}")

# Check utilization
flow = network.lines_t.p0['north-south'].abs()
utilization = (flow / s_nom_opt * 100) if s_nom_opt > 0 else 0
print(f"\nLine utilization:")
print(f"  Average: {utilization.mean():.1f}%")
print(f"  Maximum: {utilization.max():.1f}%")
```

---

## Contingency Analysis

### Example 11: N-1 Contingency Analysis

```python
import pypsa

# Create simple network
network = pypsa.Network()
network.set_snapshots([0])

network.add("Bus", "bus0", v_nom=380)
network.add("Bus", "bus1", v_nom=380)
network.add("Bus", "bus2", v_nom=380)

network.add("Generator", "gen0", bus="bus0", p_nom=400, marginal_cost=30)
network.add("Generator", "gen1", bus="bus1", p_nom=300, marginal_cost=40)

network.add("Load", "load0", bus="bus0", p_set=150)
network.add("Load", "load2", bus="bus2", p_set=400)

network.add("Line", "line0-1", bus0="bus0", bus1="bus1", x=0.1, s_nom=300)
network.add("Line", "line0-2", bus0="bus0", bus1="bus2", x=0.1, s_nom=300)
network.add("Line", "line1-2", bus0="bus1", bus1="bus2", x=0.1, s_nom=300)

# Get baseline solution
network.optimize()
baseline_cost = network.objective

print(f"Baseline cost: €{baseline_cost:,.0f}\n")
print("=== N-1 Analysis ===\n")

# Test each line outage
for line in network.lines.index:
    # Create copy and remove line
    test_net = network.deepcopy()
    test_net.mremove("Line", line)
    
    # Re-optimize
    try:
        test_net.optimize()
        
        if test_net.status['status'] != 'ok':
            print(f"Line {line} outage: DIVERGED")
        else:
            cost_increase = test_net.objective - baseline_cost
            pct_increase = cost_increase / baseline_cost * 100
            
            # Check for overloads
            overloaded = []
            if not test_net.lines_t.p0.empty:
                for other_line in test_net.lines.index:
                    p_flow = test_net.lines_t.p0[other_line].abs().max()
                    s_nom = test_net.lines.at[other_line, 's_nom']
                    if p_flow > s_nom:
                        loading = p_flow / s_nom * 100
                        overloaded.append((other_line, loading))
            
            status = "⚠️  CRITICAL" if overloaded else "✓ Secure"
            print(f"Line {line} outage: {status}")
            print(f"  Cost: €{test_net.objective:,.0f} (+€{cost_increase:,.0f}, +{pct_increase:.1f}%)")
            
            if overloaded:
                print(f"  Overloaded lines:")
                for other_line, loading in overloaded:
                    print(f"    {other_line}: {loading:.1f}%")
            print()
    
    except Exception as e:
        print(f"Line {line} outage: FAILED ({e})\n")
```

---

## Advanced Topics

### Example 12: Storage Optimization

```python
import pypsa
import pandas as pd

network = pypsa.Network()
network.set_snapshots(pd.date_range('2023-01-01', periods=168, freq='h'))

# Single bus
network.add("Bus", "bus", v_nom=380)

# Intermittent renewable
wind_profile = pd.Series([0.2 + 0.5 * (1 + pd.np.sin(2 * pd.np.pi * (i-6) / 24))
                          for i in range(168)],
                         index=network.snapshots)
network.add("Generator", "wind", bus="bus", carrier="wind",
            p_nom=400, marginal_cost=0,
            p_max_pu=wind_profile)

# Load
load_profile = pd.Series([300 + 100 * (1 + pd.np.sin(2 * pd.np.pi * (i-6) / 24))
                          for i in range(168)],
                         index=network.snapshots)
network.add("Load", "load", bus="bus", p_set=load_profile)

# Battery storage
network.add("StorageUnit", "battery",
            bus="bus",
            carrier="battery",
            p_nom=100,           # 100 MW power
            max_hours=4,         # 400 MWh energy
            efficiency_store=0.95,
            efficiency_dispatch=0.95,
            marginal_cost=0.01)

# Optimize
network.optimize()

print("=== Storage Operation ===")
print(f"Total system cost: €{network.objective:,.0f}")

# Calculate storage cycles
charge = network.storage_units_t.p['battery'][network.storage_units_t.p['battery'] < 0].abs().sum()
discharge = network.storage_units_t.p['battery'][network.storage_units_t.p['battery'] > 0].sum()
energy_capacity = network.storage_units.at['battery', 'max_hours'] * network.storage_units.at['battery', 'p_nom']
cycles = discharge / energy_capacity

print(f"\nBattery statistics:")
print(f"  Energy charged: {charge:.1f} MWh")
print(f"  Energy discharged: {discharge:.1f} MWh")
print(f"  Cycles: {cycles:.2f}")
print(f"  Round-trip efficiency: {(discharge/charge*100):.1f}%")
```

### Example 13: Sector Coupling with Power-to-Gas

```python
import pypsa
import pandas as pd

network = pypsa.Network()
network.set_snapshots(pd.date_range('2023-01-01', periods=168, freq='h'))

# Electricity bus
network.add("Bus", "elec", carrier="AC", v_nom=380)

# Gas bus
network.add("Bus", "gas", carrier="gas")

# Electricity generation
network.add("Generator", "wind", bus="elec", carrier="wind",
            p_nom=500, marginal_cost=0,
            p_max_pu=0.4)

network.add("Generator", "gas_power", bus="elec", carrier="gas_power",
            p_nom=300, marginal_cost=60)

# Electricity load
network.add("Load", "elec_load", bus="elec",
            p_set=pd.Series(300, index=network.snapshots))

# Gas load
network.add("Load", "gas_load", bus="gas",
            p_set=pd.Series(50, index=network.snapshots))

# Power-to-gas link
network.add("Link", "P2G",
            bus0="elec",
            bus1="gas",
            carrier="P2G",
            efficiency=0.6,     # 60% efficiency
            p_nom=100,
            marginal_cost=0.5)

# Gas storage
network.add("Store", "gas_storage",
            bus="gas",
            carrier="gas",
            e_nom=1000,         # 1000 MWh storage
            e_initial=500,
            e_cyclic=True,
            marginal_cost=0)

# Optimize
network.optimize()

print("=== Sector Coupling Results ===")
print(f"Total system cost: €{network.objective:,.0f}")

# P2G operation
p2g_flow = network.links_t.p0['P2G']
total_p2g = p2g_flow.sum()
hours_operating = (p2g_flow > 0).sum()

print(f"\nPower-to-Gas operation:")
print(f"  Total conversion: {total_p2g:.1f} MWh (electricity)")
print(f"  Gas produced: {total_p2g * 0.6:.1f} MWh (gas)")
print(f"  Operating hours: {hours_operating}/{len(network.snapshots)}")

# Gas storage usage
gas_storage = network.stores_t.e['gas_storage']
print(f"\nGas storage:")
print(f"  Min: {gas_storage.min():.1f} MWh")
print(f"  Max: {gas_storage.max():.1f} MWh")
print(f"  Final: {gas_storage.iloc[-1]:.1f} MWh")
```
