#!/usr/bin/env python3
"""NERC ATC and AC-aware ATC helpers for Surge.

Typical usage:
    import surge
    from transfer_capability import buses_by_area, compute_atc_both

    net = surge.case118()
    by_area = buses_by_area(net)
    areas = sorted(by_area)
    result = compute_atc_both(
        net,
        source_buses=by_area[areas[0]],
        sink_buses=by_area[areas[1]],
    )
"""
from __future__ import annotations

from typing import Any, Dict, List

import surge
from surge import transfer


def buses_by_area(net: surge.Network) -> Dict[int, List[int]]:
    """Group bus numbers by area number.

    Useful for assembling `source_buses` and `sink_buses` lists for
    inter-area transfer studies.
    """
    groups: Dict[int, List[int]] = {}
    for b in net.buses:
        groups.setdefault(b.area, []).append(b.number)
    return groups


def compute_nerc_atc(
    net: surge.Network,
    source_buses: List[int],
    sink_buses: List[int],
    name: str = "atc",
    trm_fraction: float = 0.05,
    cbm_mw: float = 0.0,
    etc_mw: float = 0.0,
) -> Dict[str, Any]:
    """Compute NERC MOD-029 / MOD-030 ATC between two bus sets."""
    path = transfer.TransferPath(name, source_buses, sink_buses)
    opts = transfer.AtcOptions(
        trm_fraction=trm_fraction, cbm_mw=cbm_mw, etc_mw=etc_mw
    )
    return transfer.compute_nerc_atc(net, path, opts).to_dict()


def compute_ac_atc(
    net: surge.Network,
    source_buses: List[int],
    sink_buses: List[int],
    name: str = "ac-atc",
    v_min: float = 0.95,
    v_max: float = 1.05,
) -> Dict[str, Any]:
    """Compute AC-aware ATC with voltage constraints."""
    path = transfer.TransferPath(name, source_buses, sink_buses)
    return transfer.compute_ac_atc(net, path, v_min, v_max).to_dict()


def compute_atc_both(
    net: surge.Network, source_buses: List[int], sink_buses: List[int]
) -> Dict[str, Any]:
    """Compute NERC ATC and AC ATC side-by-side for the same path."""
    return {
        "nerc": compute_nerc_atc(net, source_buses, sink_buses),
        "ac": compute_ac_atc(net, source_buses, sink_buses),
    }


def print_atc_report(result: Dict[str, Any]) -> None:
    print("=" * 60)
    print("ATC study")
    print("=" * 60)
    nerc = result.get("nerc", {})
    ac = result.get("ac", {})
    if nerc:
        print("  NERC:")
        print(f"    atc_mw={nerc.get('atc_mw'):.2f}  ttc_mw={nerc.get('ttc_mw'):.2f}")
        print(f"    trm_mw={nerc.get('trm_mw'):.2f}  cbm_mw={nerc.get('cbm_mw'):.2f}")
        print(f"    limit_cause={nerc.get('limit_cause')}")
    if ac:
        print("  AC:")
        print(f"    atc_mw={ac.get('atc_mw'):.2f}")
        print(
            f"    thermal_limit={ac.get('thermal_limit_mw'):.2f}  "
            f"voltage_limit={ac.get('voltage_limit_mw'):.2f}"
        )
        print(f"    limiting_constraint={ac.get('limiting_constraint')}")
    print("=" * 60)


if __name__ == "__main__":
    import sys

    name = sys.argv[1] if len(sys.argv) > 1 else "case118"
    net = (
        surge.load_builtin_case(name)
        if name in surge.list_builtin_cases()
        else surge.load(name)
    )
    groups = buses_by_area(net)
    areas = sorted(groups)
    if len(areas) < 2:
        print(
            f"Network has only {len(areas)} area(s); "
            "ATC needs at least two distinct bus sets."
        )
        sys.exit(1)
    src = groups[areas[0]][:5]
    snk = groups[areas[1]][:5]
    print(f"Source area {areas[0]}: buses {src}")
    print(f"Sink   area {areas[1]}: buses {snk}")
    print_atc_report(compute_atc_both(net, src, snk))
