#!/usr/bin/env python3
"""DC sensitivity helpers (PTDF / LODF / OTDF) for Surge.

Default to `format="summary"` for bounded output on any network size.
`"sparse"` and `"full"` are opt-in.

Typical usage:
    import surge
    from sensitivity_analysis import ptdf_summary, lodf_summary

    net = surge.case118()
    summary = ptdf_summary(net)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import surge
from surge.dc import (
    BranchKey,
    LodfRequest,
    OtdfRequest,
    PtdfRequest,
    compute_lodf,
    compute_otdf,
    compute_ptdf,
)


BranchTriple = Tuple[int, int, str]


def _triples_to_keys(
    triples: Optional[List[BranchTriple]],
) -> Optional[Tuple[BranchKey, ...]]:
    if not triples:
        return None
    return tuple(
        BranchKey(from_bus=f, to_bus=t, circuit=str(c)) for (f, t, c) in triples
    )


def ptdf_summary(
    net: surge.Network,
    monitored_branches: Optional[List[BranchTriple]] = None,
    top_k_per_branch: int = 10,
) -> Dict[str, Any]:
    """Compute PTDF and return the agent-safe summary.

    Args:
        net: Loaded Surge network.
        monitored_branches: Optional filter as (from_bus, to_bus,
            circuit) triples. None computes all in-service branches.
        top_k_per_branch: Largest-|value| bus entries retained per
            monitored branch.

    Returns:
        Dict with shape, sparsity, nnz, max_abs, top_per_row, bus_numbers,
        monitored_branch_keys.
    """
    request = (
        PtdfRequest(monitored_branches=_triples_to_keys(monitored_branches))
        if monitored_branches
        else None
    )
    return compute_ptdf(net, request).to_dict(
        format="summary", top_k_per_branch=top_k_per_branch
    )


def ptdf_row_for_branch(
    net: surge.Network, branch: BranchTriple, top_k: int = 10
) -> Dict[str, Any]:
    """Focused PTDF drill-down for a single monitored branch.

    Safe to call with `format="full"` since the row length is bounded
    by the number of buses.
    """
    result = compute_ptdf(
        net,
        PtdfRequest(monitored_branches=_triples_to_keys([branch])),
    )
    payload = result.to_dict(format="full")
    payload["_top_k"] = result.to_dict(
        format="summary", top_k_per_branch=top_k
    )["top_per_row"][0]
    return payload


def lodf_summary(
    net: surge.Network,
    monitored_branches: Optional[List[BranchTriple]] = None,
    outage_branches: Optional[List[BranchTriple]] = None,
    top_k_per_branch: int = 10,
) -> Dict[str, Any]:
    """Compute LODF summary.

    When both arguments are None, runs all-in-service × all-in-service.
    """
    req = None
    if monitored_branches or outage_branches:
        req = LodfRequest(
            monitored_branches=_triples_to_keys(monitored_branches),
            outage_branches=_triples_to_keys(outage_branches),
        )
    return compute_lodf(net, req).to_dict(
        format="summary", top_k_per_branch=top_k_per_branch
    )


def otdf_summary(
    net: surge.Network,
    monitored_branches: List[BranchTriple],
    outage_branches: List[BranchTriple],
    top_k_per_pair: int = 10,
) -> Dict[str, Any]:
    """Compute OTDF (3-D tensor) in summary format.

    Both branch lists are required — OTDF's tensor is large enough
    that passing an unfiltered request is rarely what the user wants.
    """
    req = OtdfRequest(
        monitored_branches=_triples_to_keys(monitored_branches),
        outage_branches=_triples_to_keys(outage_branches),
    )
    return compute_otdf(net, req).to_dict(
        format="summary", top_k_per_pair=top_k_per_pair
    )


def print_ptdf_report(summary: Dict[str, Any], limit_branches: int = 10) -> None:
    """Print a formatted PTDF summary — first `limit_branches` rows."""
    print("=" * 60)
    print("PTDF summary")
    print("=" * 60)
    print(f"  shape={summary['shape']}")
    print(f"  sparsity={summary['sparsity']:.3f}  max_abs={summary['max_abs']:.3f}")
    print(f"  non-zero entries: {summary['nnz']}")
    print()
    keys = summary["monitored_branch_keys"]
    bus_numbers = summary["bus_numbers"]
    rows = summary["top_per_row"][:limit_branches]
    for key, top in zip(keys, rows):
        f, t, c = key
        print(f"  branch ({f}, {t}, {c}):")
        for col, val in top:
            print(f"    bus {bus_numbers[col]}: {val:+.4f}")
    print("=" * 60)


if __name__ == "__main__":
    import sys

    name = sys.argv[1] if len(sys.argv) > 1 else "case118"
    if name in surge.list_builtin_cases():
        net = surge.load_builtin_case(name)
    else:
        net = surge.load(name)
    print_ptdf_report(ptdf_summary(net, top_k_per_branch=3))
