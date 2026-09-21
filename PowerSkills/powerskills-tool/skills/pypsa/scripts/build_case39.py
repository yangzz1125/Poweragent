#!/usr/bin/env python3
"""
Build PyPSA-format IEEE 39-bus (case39) from pandapower case39.

Run from repo root with both pandapower and pypsa installed:
  pip install pandapower pypsa
  python PyPSA/scripts/build_case39.py

Output:
  PyPSA/case39/    (CSV folder)
  PyPSA/case39.nc  (NetCDF, single-file test case)
"""

import sys
import os

# Allow running from repo root or from PyPSA/
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

try:
    import pandapower as pp
except ImportError:
    print("pandapower is required. Install with: pip install pandapower")
    sys.exit(1)

try:
    import pypsa
    import pandas as pd
    import numpy as np
except ImportError:
    print("pypsa and pandas are required. Install with: pip install pypsa pandas")
    sys.exit(1)


def _s_nom_from_thermal(max_i_ka, v_nom_kv):
    """MVA rating from current limit: S = sqrt(3) * V * I"""
    return np.sqrt(3) * v_nom_kv * max_i_ka


def _line_impedance_to_x_r(length_km, r_ohm_per_km, x_ohm_per_km, v_nom_kv, s_base_mva=100):
    """Convert per-km R,X to per-unit for PyPSA (base S_base_mva). PyPSA uses x in Ohm."""
    z_base = v_nom_kv ** 2 / s_base_mva
    r_pu = r_ohm_per_km * length_km / z_base
    x_pu = x_ohm_per_km * length_km / z_base
    return x_pu * z_base, r_pu * z_base  # return in Ohm for PyPSA


def build_pypsa_case39():
    """Load pandapower case39 and return PyPSA network."""
    # Load from pandapower built-in
    net = pp.networks.case39()
    pp.runpp(net)

    n = pypsa.Network(name="case39")
    n.set_snapshots(pd.Index([0]))  # single snapshot

    v_nom = 345  # kV
    s_base = 100  # MVA

    # Buses
    for idx in net.bus.index:
        name = str(idx)
        n.add("Bus", name, v_nom=v_nom)

    # Lines
    for idx, row in net.line.iterrows():
        name = f"line_{row['from_bus']}_{row['to_bus']}_{idx}"
        length = row["length_km"]
        r_ohm_km = row["r_ohm_per_km"]
        x_ohm_km = row["x_ohm_per_km"]
        max_i = row["max_i_ka"]
        s_nom = _s_nom_from_thermal(max_i, v_nom)
        r = r_ohm_km * length
        x = x_ohm_km * length
        n.add("Line", name, bus0=str(row["from_bus"]), bus1=str(row["to_bus"]), x=x, r=r, s_nom=s_nom)

    # Transformers (same voltage level in case39, model as zero-length lines with x from vk%)
    for idx, row in net.trafo.iterrows():
        name = f"trafo_{row['hv_bus']}_{row['lv_bus']}_{idx}"
        sn_mva = row["sn_mva"]
        vk = row["vk_percent"] / 100
        # x in Ohm: Z_base = V^2/S, X_pu = vk, so X_ohm = vk * V^2 / S
        x_ohm = vk * (v_nom ** 2) / sn_mva
        n.add("Line", name, bus0=str(row["hv_bus"]), bus1=str(row["lv_bus"]), x=x_ohm, r=0, s_nom=sn_mva)

    # Slack: ext_grid in pandapower -> generator with large capacity and low cost
    for idx, row in net.ext_grid.iterrows():
        bus = str(row["bus"])
        # Add as generator with high p_nom so it can absorb slack
        p_max = row.get("max_p_mw", 2000)
        n.add("Generator", "slack", bus=bus, p_nom=p_max, marginal_cost=0, carrier="slack")

    # Generators
    for idx, row in net.gen.iterrows():
        name = f"gen_{row['bus']}_{idx}"
        bus = str(row["bus"])
        p_nom = row.get("max_p_mw", row["p_mw"] * 1.5)
        marginal_cost = 30  # default €/MWh for dispatch
        n.add("Generator", name, bus=bus, p_nom=p_nom, marginal_cost=marginal_cost, carrier="conventional")

    # Loads (p_set constant for snapshot 0)
    for idx, row in net.load.iterrows():
        name = f"load_{row['bus']}_{idx}"
        bus = str(row["bus"])
        p_mw = row["p_mw"]
        n.add("Load", name, bus=bus, p_set=p_mw)

    return n


def main():
    out_dir = os.path.join(os.path.dirname(__file__), "..", "case39")
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    print("Building PyPSA case39 from pandapower case39...")
    n = build_pypsa_case39()

    print(f"  Buses: {len(n.buses)}")
    print(f"  Lines: {len(n.lines)}")
    print(f"  Generators: {len(n.generators)}")
    print(f"  Loads: {len(n.loads)}")

    # Export CSV folder
    n.export_to_csv_folder(out_dir)
    print(f"Exported CSV folder: {out_dir}")

    # Export NetCDF (single-file test case lives at PyPSA/case39.nc)
    nc_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "case39.nc"))
    n.export_to_netcdf(nc_path)
    print(f"Exported NetCDF: {nc_path}")

    # Quick sanity: run LOPF
    try:
        n.optimize()
        print(f"  Optimization test: OK (objective = {n.objective:.0f})")
    except Exception as e:
        print(f"  Optimization test: {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
