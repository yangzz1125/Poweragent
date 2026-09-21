#!/usr/bin/env python3
"""End-to-end smoke test for every surge/ skill script.

Runs each helper against an embedded built-in case so contributors can
verify the scripts before opening a PR. No external data required.

Usage:
    python test_scripts.py                 # uses case118
    python test_scripts.py case14          # uses any listed built-in
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import surge  # noqa: E402

from network_analysis import analyze_network, print_network_report  # noqa: E402
from sensitivity_analysis import lodf_summary, ptdf_summary  # noqa: E402
from contingency_analysis import (  # noqa: E402
    get_critical_contingencies,
    run_n1,
    summarize_n1,
)
from opf_analysis import solve_ac_opf, solve_dc_opf  # noqa: E402
from transfer_capability import buses_by_area, compute_atc_both  # noqa: E402


def _check(name: str, fn):
    try:
        payload = fn()
        json.dumps(payload, default=str)
        print(f"OK  {name}")
        return True
    except Exception as exc:  # pragma: no cover - smoke-test runner
        print(f"FAIL {name}: {exc}")
        return False


def main() -> int:
    case = sys.argv[1] if len(sys.argv) > 1 else "case118"
    print(f"Loading built-in case: {case}")
    if case not in surge.list_builtin_cases():
        print(f"Unknown case: {case}. Available: {surge.list_builtin_cases()}")
        return 1
    net = surge.load_builtin_case(case)

    passed = 0
    total = 0

    # network_analysis
    total += 1
    passed += _check(
        "network_analysis.analyze_network",
        lambda: analyze_network(net),
    )

    # sensitivity_analysis
    total += 1
    passed += _check(
        "sensitivity_analysis.ptdf_summary",
        lambda: ptdf_summary(net, top_k_per_branch=5),
    )
    total += 1
    passed += _check(
        "sensitivity_analysis.lodf_summary",
        lambda: lodf_summary(net, top_k_per_branch=5),
    )

    # contingency_analysis
    total += 1
    result_n1 = [None]

    def _n1():
        r = run_n1(net)
        result_n1[0] = r
        return r

    passed += _check("contingency_analysis.run_n1", _n1)
    if result_n1[0] is not None:
        total += 1
        passed += _check(
            "contingency_analysis.get_critical_contingencies",
            lambda: get_critical_contingencies(result_n1[0]),
        )
        total += 1
        passed += _check(
            "contingency_analysis.summarize_n1",
            lambda: summarize_n1(result_n1[0]),
        )

    # opf_analysis
    total += 1
    passed += _check(
        "opf_analysis.solve_dc_opf (HiGHS)",
        lambda: solve_dc_opf(net, lp_solver="highs"),
    )
    total += 1
    passed += _check(
        "opf_analysis.solve_ac_opf (Ipopt)",
        lambda: solve_ac_opf(net, nlp_solver="ipopt"),
    )

    # transfer_capability — only if ≥2 areas
    groups = buses_by_area(net)
    areas = sorted(groups)
    if len(areas) >= 2:
        total += 1
        passed += _check(
            "transfer_capability.compute_atc_both",
            lambda: compute_atc_both(
                net,
                source_buses=groups[areas[0]][:3],
                sink_buses=groups[areas[1]][:3],
            ),
        )
    else:
        print(f"SKIP transfer_capability: {case} has only {len(areas)} area(s)")

    print()
    print(f"{passed} / {total} scripts passed on {case}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
