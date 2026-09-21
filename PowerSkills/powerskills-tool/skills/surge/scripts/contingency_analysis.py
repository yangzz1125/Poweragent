#!/usr/bin/env python3
"""N-1 / N-2 contingency workflows for Surge.

Helpers wrapping `surge.analyze_n1_branch`, `analyze_n1_generator`,
and `analyze_n2_branch` with compact critical-flag summaries.

Typical usage:
    import surge
    from contingency_analysis import run_n1, summarize_n1, print_n1_report

    net = surge.case118()
    results = run_n1(net)
    summary = summarize_n1(results)
    print_n1_report(results, top_n=10)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import surge


def run_n1(net: surge.Network) -> Dict[str, Any]:
    """Run N-1 branch contingency analysis and return the raw to_dict()."""
    ca = surge.analyze_n1_branch(net)
    return ca.to_dict()


def run_n1_generator(net: surge.Network) -> Dict[str, Any]:
    """Run N-1 generator contingency analysis."""
    ca = surge.analyze_n1_generator(net)
    return ca.to_dict()


def run_n2(net: surge.Network) -> Dict[str, Any]:
    """Run all-pairs N-2 branch contingency analysis.

    Warning: quadratic in branch count. Use N-1 first.
    """
    ca = surge.analyze_n2_branch(net)
    return ca.to_dict()


def get_critical_contingencies(
    result: Dict[str, Any],
    loading_pct_threshold: float = 110.0,
    vm_deviation_threshold: float = 0.05,
) -> List[Dict[str, Any]]:
    """Filter per-contingency results to those flagged as critical.

    A contingency is critical when:
      - it has at least one ThermalOverload with
        loading_pct > loading_pct_threshold, or
      - it has at least one VoltageLow/VoltageHigh with vm_pu outside
        [1.0 - vm_deviation_threshold, 1.0 + vm_deviation_threshold],
      - it did not converge,
      - it caused islanding.

    Args:
        result: dict returned by run_n1 / run_n1_generator / run_n2.
        loading_pct_threshold: minimum loading_pct to flag as critical.
        vm_deviation_threshold: absolute voltage deviation from 1.0 pu
            to flag as critical.

    Returns:
        List of per-contingency dicts with an added `critical_reason`
        field describing why each was flagged.
    """
    critical: List[Dict[str, Any]] = []
    violations_by_ctg: Dict[str, List[Dict[str, Any]]] = {}
    for v in result.get("violations", []):
        violations_by_ctg.setdefault(v["contingency_id"], []).append(v)

    for r in result.get("results", []):
        reasons: List[str] = []
        if not r.get("converged", True):
            reasons.append("non_convergent")
        if r.get("max_loading_pct", 0.0) > loading_pct_threshold:
            reasons.append(f"thermal_overload>{loading_pct_threshold}%")
        vm = r.get("min_vm_pu")
        if vm is not None and vm != vm:  # NaN check without importing math
            vm = None
        if vm is not None:
            if abs(vm - 1.0) > vm_deviation_threshold:
                reasons.append(f"voltage_deviation>{vm_deviation_threshold:.2f}pu")
        if r.get("n_islands", 1) > 1:
            reasons.append("islanding")
        if r.get("vsm_category") in ("critical", "unstable"):
            reasons.append(f"vsm_{r['vsm_category']}")
        if reasons:
            critical.append(
                {
                    **r,
                    "critical_reason": reasons,
                    "violations": violations_by_ctg.get(r["contingency_id"], []),
                }
            )
    return critical


def summarize_n1(result: Dict[str, Any]) -> Dict[str, Any]:
    """Compact summary suitable for report back to the user."""
    return {
        "n_contingencies": result["n_contingencies"],
        "n_with_violations": result["n_with_violations"],
        "n_violations": result["n_violations"],
        "n_converged": result["n_converged"],
        "n_voltage_critical": result["n_voltage_critical"],
        "solve_time_secs": result["solve_time_secs"],
    }


def print_n1_report(result: Dict[str, Any], top_n: int = 10) -> None:
    """Human-readable report of an N-1 run."""
    summary = summarize_n1(result)
    print("=" * 60)
    print("N-1 contingency analysis")
    print("=" * 60)
    print(
        f"  total={summary['n_contingencies']}  "
        f"with_violations={summary['n_with_violations']}  "
        f"n_violations={summary['n_violations']}"
    )
    print(
        f"  converged={summary['n_converged']}  "
        f"voltage_critical={summary['n_voltage_critical']}  "
        f"time={summary['solve_time_secs']:.2f}s"
    )
    critical = get_critical_contingencies(result)
    if critical:
        print(f"\nTop critical contingencies (first {top_n}):")
        for r in critical[:top_n]:
            reason = ", ".join(r["critical_reason"])
            loading = r.get("max_loading_pct", 0.0)
            print(f"  {r['contingency_id']:<25s}  load={loading:>6.1f}%  [{reason}]")
    print("=" * 60)


if __name__ == "__main__":
    import sys

    name = sys.argv[1] if len(sys.argv) > 1 else "case118"
    if name in surge.list_builtin_cases():
        net = surge.load_builtin_case(name)
    else:
        net = surge.load(name)

    # Base case must converge before contingency results mean anything.
    base = surge.solve_ac_pf(net)
    if not base.converged:
        print(f"Base case did NOT converge (max_mismatch={base.max_mismatch:.2e})")
        print("Aborting contingency sweep.")
        sys.exit(1)

    result = run_n1(net)
    print_n1_report(result, top_n=10)
