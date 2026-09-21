#!/usr/bin/env python3
"""DC-OPF / AC-OPF / SCOPF helpers for Surge.

Pass `lp_solver=None` or `nlp_solver=None` for auto-detect, or an
explicit string (`"highs"`, `"ipopt"`, ...) for reproducible runs.

Typical usage:
    import surge
    from opf_analysis import solve_dc_opf, solve_ac_opf, solve_scopf

    net = surge.case118()
    dc = solve_dc_opf(net, lp_solver="highs")
    print(dc["total_cost"], dc["feasible"])
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import surge
from surge.opf import (
    AcOpfOptions,
    AcOpfRuntime,
    DcOpfOptions,
    DcOpfRuntime,
    ScopfOptions,
    ScopfRuntime,
    solve_ac_opf as _solve_ac_opf,
    solve_dc_opf as _solve_dc_opf,
    solve_scopf as _solve_scopf,
)


def solve_dc_opf(
    net: surge.Network, lp_solver: Optional[str] = None
) -> Dict[str, Any]:
    """Solve DC optimal power flow.

    Args:
        net: Loaded Surge network.
        lp_solver: None for auto-detect, or one of "highs", "gurobi",
            "copt", "cplex".

    Returns:
        The full DcOpfResult.to_dict() payload plus a top-level
        `solver_used` field. Key fields:
          - total_cost
          - feasible / is_feasible
          - converged (from the underlying OpfResult)
          - gen_p_mw, gen_bus_numbers
          - lmp, lmp_congestion
          - branch_loading_pct
    """
    runtime = DcOpfRuntime(lp_solver=lp_solver)
    sol = _solve_dc_opf(net, DcOpfOptions(), runtime)
    payload = sol.to_dict()
    payload["solver_used"] = lp_solver or "default"
    return payload


def solve_ac_opf(
    net: surge.Network, nlp_solver: Optional[str] = None
) -> Dict[str, Any]:
    """Solve AC optimal power flow.

    Args:
        net: Loaded Surge network.
        nlp_solver: None for auto-detect, or one of "ipopt", "copt",
            "gurobi".
    """
    runtime = AcOpfRuntime(nlp_solver=nlp_solver)
    sol = _solve_ac_opf(net, AcOpfOptions(), runtime)
    payload = sol.to_dict()
    payload["solver_used"] = nlp_solver or "default"
    return payload


def solve_scopf(
    net: surge.Network,
    lp_solver: Optional[str] = None,
    nlp_solver: Optional[str] = None,
) -> Dict[str, Any]:
    """Solve Security-Constrained OPF with N-1 screening."""
    runtime = ScopfRuntime(lp_solver=lp_solver, nlp_solver=nlp_solver)
    sol = _solve_scopf(net, ScopfOptions(), runtime)
    payload = sol.to_dict()
    payload["solver_used"] = {
        "lp": lp_solver or "default",
        "nlp": nlp_solver or "default",
    }
    return payload


def congested_branches(
    opf_payload: Dict[str, Any], threshold_pct: float = 95.0, top_n: int = 10
) -> list:
    """Pick the most-loaded branches from an OPF payload.

    Args:
        opf_payload: Return value of solve_dc_opf / solve_ac_opf /
            solve_scopf (or the nested base_opf for SCOPF).
        threshold_pct: Only include branches with
            branch_loading_pct >= threshold_pct.
        top_n: Cap on the number of rows returned.

    Returns:
        List of dicts with `index` and `loading_pct`.
    """
    if "base_opf" in opf_payload:
        opf_payload = opf_payload["base_opf"]
    loadings = opf_payload.get("branch_loading_pct", [])
    pairs = sorted(
        (
            (i, pct)
            for i, pct in enumerate(loadings)
            if pct is not None and pct >= threshold_pct
        ),
        key=lambda x: x[1],
        reverse=True,
    )[:top_n]
    return [{"index": i, "loading_pct": pct} for i, pct in pairs]


def print_opf_report(payload: Dict[str, Any], study: str = "OPF") -> None:
    print("=" * 60)
    print(f"{study} result")
    print("=" * 60)
    print(f"  solver_used={payload.get('solver_used')}")
    if "base_opf" in payload:
        base = payload["base_opf"]
        print(f"  formulation={payload.get('formulation')}  mode={payload.get('mode')}")
        print(f"  converged={payload.get('converged')}  iterations={payload.get('iterations')}")
        print(
            f"  binding_contingencies={len(payload.get('binding_contingencies', []))}  "
            f"remaining_violations={len(payload.get('remaining_violations', []))}"
        )
        print(f"  base cost={base.get('total_cost'):.2f}")
    else:
        print(f"  cost={payload.get('total_cost'):.2f}")
        print(
            f"  converged={payload.get('converged')}  "
            f"iterations={payload.get('iterations')}  "
            f"feasible={payload.get('is_feasible')}"
        )
    top = congested_branches(payload, threshold_pct=80.0, top_n=5)
    if top:
        print("\n  Most-loaded branches (>=80%):")
        for row in top:
            print(f"    branch_idx={row['index']:<5}  {row['loading_pct']:>6.1f}%")
    print("=" * 60)


if __name__ == "__main__":
    import sys

    name = sys.argv[1] if len(sys.argv) > 1 else "case118"
    net = (
        surge.load_builtin_case(name)
        if name in surge.list_builtin_cases()
        else surge.load(name)
    )
    print_opf_report(solve_dc_opf(net, lp_solver="highs"), study="DC-OPF (HiGHS)")
    print()
    print_opf_report(solve_ac_opf(net, nlp_solver="ipopt"), study="AC-OPF (Ipopt)")
