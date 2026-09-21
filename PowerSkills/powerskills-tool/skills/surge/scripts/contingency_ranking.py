#!/usr/bin/env python3
"""Rank N-1 branch contingencies by severity and export to CSV.

Canonical workflow: load a case, run base AC PF, run N-1 branch
contingency analysis, rank by (count of violations, max branch loading,
min voltage), export ranked list to CSV, and map each binding
contingency to the mitigation skill that should handle it.

Usage:
    python contingency_ranking.py <case_name_or_path> [output_dir]

Examples:
    # Use an embedded benchmark case
    python contingency_ranking.py case118 ./out

    # Use your own MATPOWER / PSS/E / XIIDM file
    python contingency_ranking.py /path/to/mycase.m ./out

Writes:
    {output_dir}/base_case_summary.json
    {output_dir}/binding_contingencies.csv
    {output_dir}/per_contingency_violations.csv
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

import surge


BUILTIN_NAMES = set(surge.list_builtin_cases())


def load_case(name_or_path: str) -> "surge.Network":
    if name_or_path in BUILTIN_NAMES:
        return surge.load_builtin_case(name_or_path)
    return surge.load(name_or_path)


def _severity_key(row: dict[str, Any]) -> tuple:
    """Sort key: more violations first, then higher max loading, then lower min voltage."""
    return (
        -int(row.get("n_violations", 0)),
        -float(row.get("max_loading_pct", 0.0)),
        float(row.get("min_vm_pu", 1.0)),
    )


def _classify_mitigation(row: dict[str, Any]) -> str:
    """Route a binding contingency to the right mitigation skill."""
    if row.get("min_vm_pu", 1.0) < 0.95 or row.get("max_vm_pu", 1.0) > 1.05:
        return "voltage-violation-mitigation"
    if row.get("max_loading_pct", 0.0) > 100.0:
        return "thermal-overload-mitigation"
    return "contingency-mitigation"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    case_arg = sys.argv[1]
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("./contingency_out")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load & solve base case
    net = load_case(case_arg)
    base = surge.solve_ac_pf(net)
    if not base.converged:
        print(
            f"Base case did NOT converge (max_mismatch={base.max_mismatch:.2e}). "
            "Fix the base case before running contingencies.",
            file=sys.stderr,
        )
        return 1

    # 2. Base case summary
    base_summary = {
        "case": case_arg,
        "n_buses": net.n_buses,
        "n_branches": net.n_branches,
        "base_pf_iterations": base.iterations,
        "base_pf_max_mismatch": base.max_mismatch,
    }
    (out_dir / "base_case_summary.json").write_text(json.dumps(base_summary, indent=2))

    # 3. Run N-1 branch contingency analysis
    from surge import analyze_n1_branch
    result = analyze_n1_branch(net)
    result_dict = result.to_dict()

    per_cont = result_dict.get("results", [])
    flat_violations = result_dict.get("violations", [])
    if not per_cont:
        print("No N-1 contingencies analyzed.")
        (out_dir / "binding_contingencies.csv").write_text("label\n")
        (out_dir / "per_contingency_violations.csv").write_text("label\n")
        return 0

    # 4. Flatten violations by contingency for quick max-vm lookup
    viol_by_cont: dict[str, list[dict[str, Any]]] = {}
    for v in flat_violations:
        cid = v.get("contingency_id", "?")
        viol_by_cont.setdefault(cid, []).append(v)

    # 5. Build ranked rows — keep only contingencies with ≥ 1 violation
    rows: list[dict[str, Any]] = []
    for pc in per_cont:
        n_viol = pc.get("n_violations", 0) or 0
        if n_viol == 0:
            continue
        cid = pc.get("contingency_id", "?")
        viols = viol_by_cont.get(cid, [])
        vms = [v["vm_pu"] for v in viols if v.get("vm_pu") is not None]
        row = {
            "label": pc.get("label", cid),
            "contingency_id": cid,
            "converged": bool(pc.get("converged", False)),
            "n_islands": int(pc.get("n_islands", 1) or 1),
            "n_violations": int(n_viol),
            "max_loading_pct": float(pc.get("max_loading_pct", 0.0) or 0.0),
            "min_vm_pu": float(pc.get("min_vm_pu", 1.0) or 1.0),
            "max_vm_pu": max(vms) if vms else 1.0,
        }
        row["mitigation_skill"] = _classify_mitigation(row)
        rows.append(row)

    if not rows:
        print("No binding N-1 branch contingencies found.")
        (out_dir / "binding_contingencies.csv").write_text("label\n")
        (out_dir / "per_contingency_violations.csv").write_text("label\n")
        return 0

    all_violations = flat_violations

    # 5. Sort by severity
    rows.sort(key=_severity_key)

    # 6. Export CSVs
    with (out_dir / "binding_contingencies.csv").open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["label", "contingency_id", "converged", "n_islands",
                        "n_violations", "max_loading_pct", "min_vm_pu",
                        "max_vm_pu", "mitigation_skill"],
        )
        w.writeheader()
        w.writerows(rows)
    if all_violations:
        with (out_dir / "per_contingency_violations.csv").open("w", newline="") as f:
            fieldnames = sorted({k for v in all_violations for k in v.keys()})
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(all_violations)

    # 7. Print top-10 to stdout so agents / users see the headline
    print(f"\nTop {min(10, len(rows))} binding N-1 contingencies (severity-ranked):")
    print(f"  {'label':<30} {'n_viol':>6} {'max_load%':>10} {'min_vm':>8}  mitigation")
    print(f"  {'-'*30} {'-'*6} {'-'*10} {'-'*8}  {'-'*30}")
    for r in rows[:10]:
        print(
            f"  {r['label'][:30]:<30} {r['n_violations']:>6} "
            f"{r['max_loading_pct']:>10.1f} {r['min_vm_pu']:>8.3f}  {r['mitigation_skill']}"
        )
    print(f"\nFull results written to {out_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
