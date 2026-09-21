#!/usr/bin/env python3
"""SCED / SCUC dispatch helpers for Surge.

Helpers default to `lp_solver="highs"` for open-source reproducibility.
Pass `lp_solver=None` to let Surge auto-detect (prefers Gurobi when
licensed).

Typical usage:
    import surge
    from dispatch_analysis import solve_sced, summarize_dispatch

    net = surge.market30()
    result = solve_sced(net)
    print(summarize_dispatch(result))
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

import surge
from surge.dispatch import solve_dispatch


def solve_sced(
    net: surge.Network,
    request: Optional[Mapping[str, Any]] = None,
    lp_solver: Optional[str] = "highs",
) -> Dict[str, Any]:
    """Run a single-period SCED.

    Args:
        net: Loaded Surge network.
        request: Optional DispatchRequest dict. When None, surge runs a
            default single-period DC SCED with all generators committed.
        lp_solver: "highs" (default), "gurobi", "copt", "cplex", or None
            for auto-detect.

    Returns:
        DispatchResult.to_dict() payload plus `solver_used`.
    """
    result = solve_dispatch(net, request, lp_solver=lp_solver)
    payload = result.to_dict()
    payload["solver_used"] = lp_solver or "default"
    return payload


def solve_scuc(
    net: surge.Network,
    request: Mapping[str, Any],
    lp_solver: Optional[str] = "highs",
    nlp_solver: Optional[str] = None,
) -> Dict[str, Any]:
    """Run a multi-period SCUC with commitment decisions.

    Args:
        net: Loaded Surge network.
        request: DispatchRequest dict describing periods and
            commitment scope. Required — SCUC without a structured
            request collapses to a single-period LP.
        lp_solver: "highs" (default), "gurobi", etc.
        nlp_solver: NLP backend for AC reconciliation, when the
            request asks for it. Default None = auto-detect.

    Returns:
        DispatchResult.to_dict() payload plus `solver_used`.
    """
    result = solve_dispatch(net, request, lp_solver=lp_solver, nlp_solver=nlp_solver)
    payload = result.to_dict()
    payload["solver_used"] = {
        "lp": lp_solver or "default",
        "nlp": nlp_solver or "default",
    }
    return payload


def summarize_dispatch(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Compact summary of a DispatchResult payload.

    Returns fields the agent can report back to the user without
    overwhelming context.
    """
    periods = payload.get("periods", [])
    return {
        "solver_used": payload.get("solver_used"),
        "n_periods": len(periods),
        "status": payload.get("status"),
        "objective": payload.get("objective"),
        "solve_time_secs": payload.get("solve_time_secs"),
    }


def print_dispatch_report(payload: Dict[str, Any]) -> None:
    print("=" * 60)
    print("Dispatch result")
    print("=" * 60)
    s = summarize_dispatch(payload)
    for k, v in s.items():
        print(f"  {k}: {v}")
    print("=" * 60)


if __name__ == "__main__":
    import sys

    name = sys.argv[1] if len(sys.argv) > 1 else "market30"
    net = (
        surge.load_builtin_case(name)
        if name in surge.list_builtin_cases()
        else surge.load(name)
    )
    result = solve_sced(net, lp_solver="highs")
    print_dispatch_report(result)
