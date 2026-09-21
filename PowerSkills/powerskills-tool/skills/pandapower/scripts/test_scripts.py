#!/usr/bin/env python3
"""Minimal validation of pandapower scripts.

Run:
  python scripts/test_scripts.py
"""

import os
import sys

import pandapower as pp

# Ensure scripts directory is importable
sys.path.insert(0, os.path.dirname(__file__))

from network_analysis import analyze_network
from contingency_analysis import analyze_n1, get_critical_contingencies


def main() -> int:
    net = pp.networks.case14()
    pp.runpp(net)

    analysis = analyze_network(net)
    assert analysis["violations"]["converged"] is True

    n1 = analyze_n1(net, elements=["line"])
    critical = get_critical_contingencies(n1)

    print("✓ scripts import OK")
    print(f"✓ analyze_network OK (has_violations={analysis['violations']['has_violations']})")
    print(f"✓ analyze_n1 OK (contingencies={len(n1)}, critical={len(critical)})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
