"""Export the stressed IEEE 39-bus benchmark case to PandaPower and MATPOWER formats."""
from __future__ import annotations

from pathlib import Path

import numpy as np

from poweragentbench.benchmark_utils import (
    REPO_ROOT,
    SCENARIO_GENERATOR_DELTAS_MW,
    SCENARIO_LOAD_IDS,
    SCENARIO_LOAD_SCALE,
    SCENARIO_VM_TARGET_SHIFT_PU,
)

PP_JSON_PATH = REPO_ROOT / "cases" / "case39" / "pandapower" / "case39.json"
MATPOWER_PATH = REPO_ROOT / "cases" / "case39" / "matpower" / "case39.m"

# Mapping from PyPSA generator IDs (G1..G10) to pandapower gen table indices.
# pandapower.networks.case39() has 10 generators; the index order matches the
# MATPOWER source: gen indices 0..9 correspond to buses 30..39 (G1..G10 in our
# PyPSA naming where G1 is on bus 30, G2 on bus 31, etc.).
_PYPSA_TO_PP_GEN = {
    "G1": 0,
    "G2": 1,
    "G3": 2,
    "G4": 3,
    "G5": 4,
    "G6": 5,
    "G7": 6,
    "G8": 7,
    "G9": 8,
    "G10": 9,
}

# Mapping from PyPSA load IDs (L1..L21) to pandapower load table indices.
# pandapower.networks.case39() has 21 loads numbered 0..20.  The PyPSA names
# L1..L21 map directly: L1 -> index 0, L10 -> index 9, etc.
_PYPSA_TO_PP_LOAD = {f"L{i}": i - 1 for i in range(1, 22)}


def build_stressed_pp_net():
    """Reproduce the benchmark stress pattern directly in pandapower."""
    import pandapower as pp
    import pandapower.networks as pn

    net = pn.case39()

    # Scale selected loads
    for load_name in SCENARIO_LOAD_IDS:
        idx = _PYPSA_TO_PP_LOAD[load_name]
        net.load.at[idx, "p_mw"] *= SCENARIO_LOAD_SCALE
        net.load.at[idx, "q_mvar"] *= SCENARIO_LOAD_SCALE

    # Adjust generator dispatch
    for gen_name, delta_mw in SCENARIO_GENERATOR_DELTAS_MW.items():
        idx = _PYPSA_TO_PP_GEN[gen_name]
        net.gen.at[idx, "p_mw"] += delta_mw

    # Shift voltage setpoints
    for gen_name, delta_pu in SCENARIO_VM_TARGET_SHIFT_PU.items():
        idx = _PYPSA_TO_PP_GEN[gen_name]
        net.gen.at[idx, "vm_pu"] += delta_pu

    pp.runpp(net)
    return net


def export_pandapower_json(net, path: Path) -> None:
    """Export a pandapower network to JSON."""
    import pandapower as pp

    path.parent.mkdir(parents=True, exist_ok=True)
    pp.to_json(net, str(path))
    print(f"PandaPower JSON written to {path}")


def _format_matrix_row(row: np.ndarray) -> str:
    """Format a single row for a MATPOWER matrix."""
    parts = []
    for v in row:
        if np.isnan(v):
            parts.append("\t0")
        elif np.isinf(v):
            parts.append("\t9999" if v > 0 else "\t-9999")
        elif v == int(v):
            parts.append(f"\t{int(v)}")
        else:
            parts.append(f"\t{v:.6g}")
    return "".join(parts) + ";"


def export_matpower_m(net, path: Path) -> None:
    """Export a pandapower network to a MATPOWER .m file."""
    import pandapower as pp
    from pandapower.converter.pypower import to_ppc

    # Ensure we have solved results for initial values
    pp.runpp(net)
    ppc = to_ppc(net)

    bus = ppc["bus"].copy()
    gen = ppc["gen"].copy()
    branch = ppc["branch"].copy()
    baseMVA = float(ppc["baseMVA"])

    # PYPOWER uses 0-based bus numbering; shift to 1-based for MATPOWER
    bus_orig = bus[:, 0].copy()
    bus_map = {int(old): int(i + 1) for i, old in enumerate(bus_orig)}

    bus[:, 0] = np.array([bus_map[int(b)] for b in bus[:, 0]])
    gen[:, 0] = np.array([bus_map[int(b)] for b in gen[:, 0]])
    branch[:, 0] = np.array([bus_map[int(b)] for b in branch[:, 0]])
    branch[:, 1] = np.array([bus_map[int(b)] for b in branch[:, 1]])

    # MATPOWER convention: tap_ratio=0 means "no transformer" (1:1),
    # whereas PYPOWER uses 1.0 for the same.  Convert lines (non-transformers)
    # that have tap_ratio == 1.0 and phase_shift == 0 to tap_ratio = 0.
    for i in range(branch.shape[0]):
        if branch[i, 8] == 1.0 and branch[i, 9] == 0.0:
            branch[i, 8] = 0.0

    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write("function mpc = case39\n")
        f.write("%CASE39  IEEE 39-bus stressed benchmark scenario (PowerAgentBench).\n\n")
        f.write("%% MATPOWER Case Format : Version 2\n")
        f.write("mpc.version = '2';\n\n")
        f.write("%%-----  Power Flow Data  -----%%\n")
        f.write(f"mpc.baseMVA = {baseMVA:.1f};\n\n")

        # Bus data
        f.write("%% bus data\n")
        f.write("%\tbus_i\ttype\tPd\tQd\tGs\tBs\tarea\tVm\tVa\tbaseKV\tzone\tVmax\tVmin\n")
        f.write("mpc.bus = [\n")
        for row in bus:
            f.write(_format_matrix_row(row) + "\n")
        f.write("];\n\n")

        # Generator data
        f.write("%% generator data\n")
        f.write("%\tbus\tPg\tQg\tQmax\tQmin\tVg\tmBase\tstatus\tPmax\tPmin"
                "\tPc1\tPc2\tQc1min\tQc1max\tQc2min\tQc2max\tramp_agc\tramp_10\tramp_30\tramp_q\tapf\n")
        f.write("mpc.gen = [\n")
        for row in gen:
            f.write(_format_matrix_row(row) + "\n")
        f.write("];\n\n")

        # Branch data
        f.write("%% branch data\n")
        f.write("%\tfbus\ttbus\tr\tx\tb\trateA\trateB\trateC\tratio\tangle\tstatus\tangmin\tangmax\n")
        f.write("mpc.branch = [\n")
        for row in branch:
            f.write(_format_matrix_row(row) + "\n")
        f.write("];\n\n")

    print(f"MATPOWER .m file written to {path}")


def verify_pandapower_roundtrip(original_net, json_path: Path) -> bool:
    """Reload the exported JSON and compare voltages with the original."""
    import pandapower as pp

    reloaded = pp.from_json(str(json_path))
    pp.runpp(reloaded)

    v_orig = original_net.res_bus.vm_pu.values
    v_reload = reloaded.res_bus.vm_pu.values

    if not np.allclose(v_orig, v_reload, atol=1e-6):
        max_diff = np.max(np.abs(v_orig - v_reload))
        print(f"WARNING: PandaPower roundtrip voltage mismatch (max diff: {max_diff:.2e})")
        return False

    print("PandaPower roundtrip verification passed (voltage atol=1e-6).")
    return True


def print_summary(net, label: str) -> None:
    """Print basic network statistics."""
    import pandapower as pp

    pp.runpp(net)
    n_bus = len(net.bus)
    total_load_mw = net.load.p_mw.sum()
    total_gen_mw = net.res_gen.p_mw.sum() + net.res_ext_grid.p_mw.sum()
    print(f"[{label}] Buses: {n_bus}, Total load: {total_load_mw:.1f} MW, Total gen (solved): {total_gen_mw:.1f} MW")


def main() -> None:
    print("Building stressed pandapower network...")
    net = build_stressed_pp_net()

    print_summary(net, "PandaPower")

    export_pandapower_json(net, PP_JSON_PATH)
    export_matpower_m(net, MATPOWER_PATH)

    verify_pandapower_roundtrip(net, PP_JSON_PATH)

    print("\nDone. Exported files:")
    print(f"  PandaPower: {PP_JSON_PATH}")
    print(f"  MATPOWER:   {MATPOWER_PATH}")


if __name__ == "__main__":
    main()
