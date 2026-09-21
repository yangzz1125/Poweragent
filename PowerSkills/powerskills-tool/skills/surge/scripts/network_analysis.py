#!/usr/bin/env python3
"""Network inspection and base-case review for Surge.

Helpers return structured dicts for downstream decision-making. The
`__main__` block loads a built-in case and prints a formatted report.

Typical usage:
    import surge
    from network_analysis import analyze_network, print_network_report
    net = surge.case118()
    results = analyze_network(net)
    print_network_report(results)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import surge


def summarize_network(net: surge.Network) -> Dict[str, Any]:
    """Return the comprehensive Network.summary() payload.

    Small wrapper so agent code has a single consistent entry point.
    """
    return net.summary()


def solve_base_ac(net: surge.Network) -> Dict[str, Any]:
    """Solve AC power flow and return a compact status summary.

    Returns:
        {
            "converged": bool,
            "iterations": int,
            "max_mismatch": float,
            "solve_time_secs": float,
        }
    """
    sol = surge.solve_ac_pf(net)
    return {
        "converged": bool(sol.converged),
        "iterations": int(sol.iterations),
        "max_mismatch": float(sol.max_mismatch),
        "solve_time_secs": float(sol.solve_time_secs),
    }


def extreme_buses(
    net: surge.Network, n: int = 5
) -> Dict[str, List[Dict[str, Any]]]:
    """Return the buses with the largest loads and the lowest / highest
    nominal voltage limits.

    Useful for quick "what are the interesting buses" inspection
    before running contingency or sensitivity studies.
    """
    df = net.bus_dataframe()
    try:
        import pandas as pd
        if isinstance(df, pd.DataFrame):
            df = df.reset_index()
            biggest_loads = (
                df.nlargest(n, "pd_mw")[["bus_id", "name", "base_kv", "pd_mw"]]
                .to_dict(orient="records")
            )
            lowest_vmin = (
                df.nsmallest(n, "vmin_pu")[["bus_id", "name", "vmin_pu"]]
                .to_dict(orient="records")
            )
            highest_vmax = (
                df.nlargest(n, "vmax_pu")[["bus_id", "name", "vmax_pu"]]
                .to_dict(orient="records")
            )
            return {
                "biggest_loads": biggest_loads,
                "lowest_vmin_pu": lowest_vmin,
                "highest_vmax_pu": highest_vmax,
            }
    except ImportError:
        pass
    # Dict fallback (pandas unavailable)
    return {
        "biggest_loads": [],
        "lowest_vmin_pu": [],
        "highest_vmax_pu": [],
        "_note": "pandas not installed — extreme_buses skipped",
    }


def analyze_network(net: surge.Network) -> Dict[str, Any]:
    """Combined network inspection suitable for agent consumption.

    Runs `summarize_network`, solves the AC base case, and collects
    `extreme_buses`. Agents should read `base_pf.converged` before
    trusting `summary` totals as realistic operating points.
    """
    return {
        "summary": summarize_network(net),
        "base_pf": solve_base_ac(net),
        "extreme_buses": extreme_buses(net, n=5),
    }


def print_network_report(result: Dict[str, Any]) -> None:
    summary = result["summary"]
    pf = result["base_pf"]
    print("=" * 60)
    print(f"Surge Network Analysis: {summary.get('name', '<unnamed>')}")
    print("=" * 60)
    print(
        f"  buses={summary['n_buses']} "
        f"branches={summary['n_branches']} "
        f"gens={summary['n_generators']} "
        f"loads={summary['n_loads']}"
    )
    print(
        f"  total_load_mw={summary['total_load_mw']:.1f}  "
        f"total_gen_mw={summary['total_generation_mw']:.1f}  "
        f"gen_capacity_mw={summary['total_generation_capacity_mw']:.1f}"
    )
    print(
        f"  areas={summary['n_areas']} "
        f"zones={summary['n_zones']} "
        f"voltage_levels_kv={summary['voltage_levels_kv']}"
    )
    print()
    print("Base-case AC power flow:")
    print(
        f"  converged={pf['converged']}  iterations={pf['iterations']}  "
        f"max_mismatch={pf['max_mismatch']:.2e}  "
        f"time={pf['solve_time_secs'] * 1000:.1f} ms"
    )
    print()

    extremes = result["extreme_buses"]
    if extremes.get("biggest_loads"):
        print("Biggest loads:")
        for row in extremes["biggest_loads"]:
            print(
                f"  bus {row['bus_id']:>5}  {row.get('name', ''):20s}  "
                f"pd={row['pd_mw']:.1f} MW  base_kv={row['base_kv']}"
            )
    print("=" * 60)


if __name__ == "__main__":
    import sys

    name = sys.argv[1] if len(sys.argv) > 1 else "case118"
    if name in surge.list_builtin_cases():
        net = surge.load_builtin_case(name)
    else:
        net = surge.load(name)
    print_network_report(analyze_network(net))
