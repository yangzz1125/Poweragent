#!/usr/bin/env python3
"""Load, validate, and base-case-solve a pandapower network before potpourri OPF.

This is step 1-3 of the potpourri ladder: get a network, prove it is a credible
model, and establish a base operating point. Nothing here builds a Pyomo model —
run this first so that an infeasible OPF later can be blamed on the formulation
rather than on the network data.

The checks are the ones that actually make potpourri OPFs fail or return
nonsense: contradictory bounds (potpourri hands them to IPOPT, which reports
`other` rather than `infeasible`), unrated branches (an unrated line gets an
effectively infinite thermal limit, so congestion silently disappears), missing
reference buses, unsupplied islands, and — for multi-period work — absent or
too-short SimBench profiles.

Typical usage:
    from inspect_case import load_case, check_network, run_base_power_flow

    net, meta = load_case("simbench:1-LV-rural1--0-sw", profile_index=672)
    findings = check_network(net)
    base = run_base_power_flow(net)

CLI:
    python inspect_case.py --case simbench:1-LV-rural1--0-sw --profile-index 672
    python inspect_case.py --case grid.json --json out.json --output-dir results/
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import pandapower as pp

SIMBENCH_PREFIX = "simbench:"

# A line whose series impedance is below this (ohm) behaves as a bus-bus short.
# potpourri merges zero-impedance *switches*, but a near-zero-impedance *line*
# survives into the model and makes the admittance matrix ill-conditioned.
NEAR_ZERO_OHM = 1e-6


# --------------------------------------------------------------------- loading
def load_case(
    case: str,
    profile_index: Optional[int] = None,
) -> Tuple[pp.pandapowerNet, Dict[str, Any]]:
    """Load a pandapower network from a SimBench code or a JSON file.

    Args:
        case: Either ``"simbench:<code>"`` (e.g.
            ``"simbench:1-LV-rural1--0-sw"``) or a path to a pandapower JSON
            file.
        profile_index: When given and the network carries SimBench profiles,
            overwrite ``load``/``sgen`` power with that profile row, turning the
            network into a single snapshot. Leave ``None`` to keep the
            network's own operating point, and for multi-period studies (which
            need the full profile set intact).

    Returns:
        ``(net, meta)`` where meta records the source, whether profiles are
        available, and how many profile rows exist.
    """
    meta: Dict[str, Any] = {
        "case": case,
        "profile_index": profile_index,
        "has_profiles": False,
        "profile_rows": None,
    }

    if case.startswith(SIMBENCH_PREFIX):
        code = case[len(SIMBENCH_PREFIX):]
        if not code:
            raise ValueError("Empty SimBench code; expected simbench:<code>")
        try:
            import simbench as sb
        except ImportError as err:  # pragma: no cover - env-dependent
            raise ImportError(
                "simbench is required for simbench: cases. "
                "Install it with `pip install simbench`."
            ) from err
        net = sb.get_simbench_net(code)
        meta["source"] = "simbench"
        meta["simbench_code"] = code
        profiles = sb.get_absolute_values(
            net, profiles_instead_of_study_cases=True
        )
        meta["has_profiles"] = True
        meta["profile_rows"] = int(len(profiles[("load", "p_mw")]))
        if profile_index is not None:
            _apply_snapshot(net, profiles, profile_index, meta["profile_rows"])
    else:
        if not os.path.isfile(case):
            raise FileNotFoundError(f"Network file not found: {case}")
        net = pp.from_json(case)
        meta["source"] = "json"
        meta["has_profiles"] = bool(
            hasattr(net, "profiles") and len(getattr(net, "profiles", {}))
        )
        if profile_index is not None and not meta["has_profiles"]:
            raise ValueError(
                f"--profile-index given but {case} carries no profiles. "
                "Drop the flag, or use a simbench: case for time series."
            )

    meta["name"] = str(getattr(net, "name", "") or "unnamed")
    meta["sn_mva"] = float(net.sn_mva)
    meta["f_hz"] = float(net.f_hz) if "f_hz" in net else None
    return net, meta


def _apply_snapshot(net, profiles, idx: int, n_rows: int) -> None:
    """Overwrite load/sgen power with one profile row (in place)."""
    if idx < 0 or idx >= n_rows:
        raise ValueError(
            f"profile_index {idx} out of range; profiles have {n_rows} rows "
            f"(valid 0..{n_rows - 1})."
        )
    for table, col in (
        ("sgen", "p_mw"),
        ("load", "p_mw"),
        ("load", "q_mvar"),
    ):
        key = (table, col)
        if key in profiles and len(net[table]):
            net[table][col] = profiles[key].iloc[idx]


# ------------------------------------------------------------------ validation
def check_network(net: pp.pandapowerNet) -> Dict[str, Any]:
    """Run the pre-OPF data checks and classify findings by severity.

    ``blocking`` findings will make a potpourri OPF fail or produce a
    meaningless answer, so resolve them before building a model. ``warning``
    findings change the physical meaning of the result (an unrated line, an
    unbounded controllable device) without necessarily breaking the solve.

    Returns:
        dict with ``blocking``, ``warnings``, ``info`` (each a list of strings)
        and ``counts`` / ``controllable`` summaries.
    """
    blocking: List[str] = []
    warnings_: List[str] = []
    info: List[str] = []

    # --- reference buses ------------------------------------------------
    n_ext = int(net.ext_grid.in_service.sum()) if len(net.ext_grid) else 0
    slack_gen = 0
    if len(net.gen) and "slack" in net.gen.columns:
        slack_gen = int((net.gen.slack & net.gen.in_service).sum())
    n_ref = n_ext + slack_gen
    if n_ref == 0:
        blocking.append(
            "No reference bus: 0 in-service ext_grid and 0 slack gen. "
            "potpourri fixes the voltage angle on model.b0, which would be "
            "empty, leaving the angle reference undetermined."
        )
    elif n_ref > 1:
        info.append(
            f"{n_ref} reference buses ({n_ext} ext_grid, {slack_gen} slack "
            "gen). Valid, but active power splits between them, so read "
            "every ext_grid dispatch rather than just the first."
        )

    # --- connectivity ---------------------------------------------------
    try:
        import pandapower.topology as top

        unsupplied = top.unsupplied_buses(net)
        if unsupplied:
            blocking.append(
                f"{len(unsupplied)} unsupplied bus(es) with no path to a "
                f"reference bus: {sorted(unsupplied)[:10]}"
                f"{' ...' if len(unsupplied) > 10 else ''}. "
                "Fix the topology or drop them; potpourri writes KCL for "
                "every in-service bus."
            )
        graph = top.create_nxgraph(net, respect_switches=True)
        import networkx as nx

        n_islands = nx.number_connected_components(graph)
        if n_islands > 1:
            info.append(
                f"{n_islands} electrical islands with switches respected."
            )
    except Exception as err:  # pragma: no cover - optional dependency
        warnings_.append(f"Connectivity check skipped ({type(err).__name__}: {err}).")

    # --- nominal voltages -----------------------------------------------
    if len(net.bus):
        bad_vn = net.bus.index[~(net.bus.vn_kv > 0)].tolist()
        if bad_vn:
            blocking.append(
                f"{len(bad_vn)} bus(es) with missing or non-positive vn_kv: "
                f"{bad_vn[:10]}. Line thermal limits are derived from "
                "vn_kv * sqrt(3) * max_i_ka, so these become 0 or NaN."
            )
        levels = sorted({round(float(v), 3) for v in net.bus.vn_kv.dropna()})
        info.append(f"Voltage levels (kV): {levels}")

    # --- branch ratings -------------------------------------------------
    if len(net.line):
        no_rating = net.line.index[
            net.line.max_i_ka.isna() | (net.line.max_i_ka <= 0)
        ].tolist()
        if no_rating:
            warnings_.append(
                f"{len(no_rating)} line(s) without a usable max_i_ka: "
                f"{no_rating[:10]}. Their thermal constraint is vacuous, so "
                "congestion on them cannot appear in the OPF result."
            )
        z = (net.line.r_ohm_per_km.abs() + net.line.x_ohm_per_km.abs()) * net.line.length_km
        tiny = net.line.index[z < NEAR_ZERO_OHM].tolist()
        if tiny:
            warnings_.append(
                f"{len(tiny)} line(s) with near-zero series impedance: "
                f"{tiny[:10]}. These behave as shorts and make the AC "
                "Jacobian ill-conditioned; model them as bus-bus switches."
            )
        if "max_loading_percent" not in net.line.columns:
            info.append(
                "net.line has no max_loading_percent column; potpourri "
                "defaults to 100 %."
            )
    if len(net.trafo):
        bad_sn = net.trafo.index[
            net.trafo.sn_mva.isna() | (net.trafo.sn_mva <= 0)
        ].tolist()
        if bad_sn:
            blocking.append(
                f"{len(bad_sn)} transformer(s) with missing or non-positive "
                f"sn_mva: {bad_sn[:10]}. The transformer limit SLmaxT is "
                "sn_mva-derived and would be 0 or NaN."
            )

    # --- bounds contradictions -----------------------------------------
    blocking.extend(_check_bounds(net))

    # --- fixed values outside their own bounds -------------------------
    warnings_.extend(_check_setpoints_within_bounds(net))

    # --- controllability -----------------------------------------------
    controllable = {}
    for table in ("sgen", "gen", "load", "storage"):
        flags = bool_flags(net[table], "controllable") if len(net[table]) else None
        controllable[table] = int(flags.sum()) if flags is not None else 0
    if sum(controllable.values()) == 0:
        warnings_.append(
            "No controllable sgen/gen/load/storage. With only the external "
            "grid free, the OPF has almost no decision space — set "
            "net.<table>.controllable plus min_p_mw / max_p_mw."
        )
    else:
        for table, n_ctrl in controllable.items():
            if n_ctrl and len(net[table]):
                missing = [
                    c for c in ("min_p_mw", "max_p_mw")
                    if c not in net[table].columns
                ]
                if missing:
                    warnings_.append(
                        f"{n_ctrl} controllable {table}(s) but no {missing} "
                        "column(s): the active-power range is undefined, so "
                        "the optimiser may dispatch far outside the physical "
                        "capability."
                    )

    # --- duplicate indices ---------------------------------------------
    for table in ("bus", "line", "trafo", "load", "sgen", "gen", "ext_grid", "storage"):
        if len(net[table]) and net[table].index.duplicated().any():
            blocking.append(f"net.{table} has duplicate indices.")

    # --- storage --------------------------------------------------------
    if len(net.storage):
        for col in ("max_e_mwh", "efficiency_percent", "soc_percent"):
            if col not in net.storage.columns:
                warnings_.append(
                    f"net.storage has no {col}; potpourri's single-period "
                    "storage block needs it (soc_percent defaults to 50)."
                )

    # --- cost data ------------------------------------------------------
    if "poly_cost" in net and len(net.poly_cost):
        info.append(f"net.poly_cost has {len(net.poly_cost)} row(s).")
        if "cp2_eur_per_mw2" in net.poly_cost.columns and (
            net.poly_cost.cp2_eur_per_mw2.abs() > 0
        ).any():
            info.append(
                "Quadratic cost terms present (cp2 != 0): a DC OPF then needs "
                "a QP-capable solver, or add_poly_cost_objective("
                "allow_quadratic=False) to refuse them explicitly."
            )
    if "pwl_cost" in net and len(net.pwl_cost):
        blocking.append(
            f"net.pwl_cost has {len(net.pwl_cost)} row(s). "
            "add_poly_cost_objective raises on piecewise-linear costs; "
            "convert them to polynomial form first."
        )

    # --- switches -------------------------------------------------------
    if len(net.switch):
        n_open = int((~net.switch.closed.astype(bool)).sum())
        info.append(
            f"{len(net.switch)} switch(es), {n_open} open. potpourri merges "
            "closed zero-impedance bus-bus switches and reindexes buses, so "
            "model bus numbers need not equal net.bus indices."
        )

    return {
        "blocking": blocking,
        "warnings": warnings_,
        "info": info,
        "counts": element_counts(net),
        "controllable": controllable,
        "n_reference_buses": n_ref,
    }


def bool_flags(df, name: str):
    """Read a pandapower flag column as a clean boolean Series.

    pandapower stores these as object dtype with NaN for "not set", and
    ``fillna(False).astype(bool)`` on object dtype raises a pandas
    downcasting FutureWarning, so map explicitly instead.
    """
    if name not in df.columns:
        return None
    return df[name].map(
        lambda v: bool(v) if (v is not None and v == v) else False
    ).astype(bool)


def _check_bounds(net) -> List[str]:
    """Find min > max contradictions, which are the most common infeasibility."""
    out: List[str] = []
    checks = [
        ("bus", "min_vm_pu", "max_vm_pu"),
        ("sgen", "min_p_mw", "max_p_mw"),
        ("sgen", "min_q_mvar", "max_q_mvar"),
        ("gen", "min_p_mw", "max_p_mw"),
        ("gen", "min_q_mvar", "max_q_mvar"),
        ("load", "min_p_mw", "max_p_mw"),
        ("ext_grid", "min_p_mw", "max_p_mw"),
        ("ext_grid", "min_q_mvar", "max_q_mvar"),
    ]
    for table, lo, hi in checks:
        df = net[table]
        if not len(df) or lo not in df.columns or hi not in df.columns:
            continue
        # Compare only where both bounds are set; NaN comparisons are False
        # anyway but emit a numpy RuntimeWarning through pandas' numexpr path.
        both = df[[lo, hi]].dropna()
        bad = both.index[both[lo] > both[hi]].tolist()
        if bad:
            out.append(
                f"net.{table}: {lo} > {hi} on {len(bad)} row(s) {bad[:10]}. "
                "This is infeasible by construction; IPOPT reports it as "
                "termination_condition 'other', not 'infeasible'."
            )
    return out


def _check_setpoints_within_bounds(net) -> List[str]:
    """Flag fixed operating points that already violate their declared bounds."""
    out: List[str] = []
    for table in ("sgen", "gen"):
        df = net[table]
        ctrl = bool_flags(df, "controllable")
        if not len(df) or ctrl is None:
            continue
        for col, comparison, wording in (
            ("max_p_mw", "above", "above max_p_mw"),
            ("min_p_mw", "below", "below min_p_mw"),
        ):
            if col not in df.columns:
                continue
            sub = df.loc[ctrl, ["p_mw", col]].dropna()
            if not len(sub):
                continue
            bad = (
                sub.index[sub.p_mw > sub[col]]
                if comparison == "above"
                else sub.index[sub.p_mw < sub[col]]
            ).tolist()
            if bad:
                out.append(
                    f"net.{table}: p_mw {wording} on {bad[:10]} — the base "
                    "case is outside the OPF feasible set."
                )
    return out


def element_counts(net: pp.pandapowerNet) -> Dict[str, int]:
    """Count the element tables potpourri maps into Pyomo sets."""
    return {
        "bus": len(net.bus),
        "line": len(net.line),
        "trafo": len(net.trafo),
        "trafo3w": len(net.trafo3w),
        "impedance": len(net.impedance) if "impedance" in net else 0,
        "ext_grid": len(net.ext_grid),
        "gen": len(net.gen),
        "sgen": len(net.sgen),
        "load": len(net.load),
        "storage": len(net.storage),
        "shunt": len(net.shunt),
        "switch": len(net.switch),
    }


# ------------------------------------------------------------- base power flow
def run_base_power_flow(net: pp.pandapowerNet) -> Dict[str, Any]:
    """Solve the pandapower AC base case and summarise the operating point.

    potpourri's own constructors call ``pp.runpp`` too, so a network that fails
    here will fail there. Establishing the base case separately also gives the
    reference the AC OPF result should be compared against.
    """
    try:
        pp.runpp(net, voltage_depend_loads=False)
    except Exception as err:  # noqa: BLE001 - report, don't crash the report
        return {
            "converged": False,
            "error": f"{type(err).__name__}: {err}",
        }
    if not bool(net.converged):
        return {"converged": False, "error": "pp.runpp did not converge"}

    out: Dict[str, Any] = {"converged": True}
    vm = net.res_bus.vm_pu.dropna()
    if len(vm):
        out["vm_pu_min"] = float(vm.min())
        out["vm_pu_min_bus"] = int(vm.idxmin())
        out["vm_pu_max"] = float(vm.max())
        out["vm_pu_max_bus"] = int(vm.idxmax())
    out["max_line_loading_percent"] = max_with_index(net.res_line, "loading_percent")
    out["max_trafo_loading_percent"] = max_with_index(net.res_trafo, "loading_percent")
    out["losses_mw"] = float(
        (net.res_line.pl_mw.sum() if len(net.res_line) else 0.0)
        + (net.res_trafo.pl_mw.sum() if len(net.res_trafo) else 0.0)
    )
    out["ext_grid_p_mw"] = float(net.res_ext_grid.p_mw.sum()) if len(net.res_ext_grid) else 0.0
    out["ext_grid_q_mvar"] = float(net.res_ext_grid.q_mvar.sum()) if len(net.res_ext_grid) else 0.0
    out["load_p_mw"] = float(net.res_load.p_mw.sum()) if len(net.res_load) else 0.0
    out["sgen_p_mw"] = float(net.res_sgen.p_mw.sum()) if len(net.res_sgen) else 0.0
    out["gen_p_mw"] = float(net.res_gen.p_mw.sum()) if len(net.res_gen) else 0.0
    return out


def max_with_index(df, col: str) -> Optional[Dict[str, Any]]:
    """Return {'value', 'index'} for the largest entry of df[col], or None."""
    if df is None or not len(df) or col not in df.columns:
        return None
    series = df[col].dropna()
    if not len(series):
        return None
    return {"value": float(series.max()), "index": int(series.idxmax())}


# ------------------------------------------------------------------- top level
def inspect_case(
    case: str,
    profile_index: Optional[int] = None,
    run_power_flow: bool = True,
) -> Dict[str, Any]:
    """Load, validate, and optionally base-case-solve a network.

    Returns a single structured payload; ``ok`` is False when a blocking
    finding means an OPF should not be attempted yet.
    """
    net, meta = load_case(case, profile_index=profile_index)
    findings = check_network(net)
    payload: Dict[str, Any] = {
        "meta": meta,
        "findings": findings,
    }
    if run_power_flow:
        payload["base_case"] = run_base_power_flow(net)
    payload["ok"] = not findings["blocking"] and (
        payload.get("base_case", {}).get("converged", True)
    )
    return payload


def print_report(payload: Dict[str, Any]) -> None:
    """Print the engineering summary a reviewer actually reads."""
    meta = payload["meta"]
    findings = payload["findings"]
    counts = findings["counts"]

    print("=" * 68)
    print(f"potpourri case inspection: {meta['case']}")
    print("=" * 68)
    print(f"  name         : {meta.get('name')}")
    print(f"  source       : {meta.get('source')}   baseMVA: {meta['sn_mva']}")
    if meta.get("f_hz"):
        print(f"  frequency    : {meta['f_hz']} Hz")
    if meta.get("has_profiles"):
        print(
            f"  profiles     : yes, {meta.get('profile_rows')} rows"
            + (
                f" (snapshot applied at index {meta['profile_index']})"
                if meta.get("profile_index") is not None
                else ""
            )
        )
    else:
        print("  profiles     : none -> single-period studies only")

    print("\n  Elements:")
    for key, val in counts.items():
        if val:
            print(f"    {key:11s}: {val}")
    ctrl = findings["controllable"]
    print(
        "  Controllable : "
        + ", ".join(f"{k}={v}" for k, v in ctrl.items())
        + f"   reference buses: {findings['n_reference_buses']}"
    )

    base = payload.get("base_case")
    if base:
        print("\n  Base power flow (pandapower):")
        if not base.get("converged"):
            print(f"    DID NOT CONVERGE - {base.get('error')}")
        else:
            print(
                f"    vm_pu   : {base['vm_pu_min']:.4f} (bus "
                f"{base['vm_pu_min_bus']}) .. {base['vm_pu_max']:.4f} (bus "
                f"{base['vm_pu_max_bus']})"
            )
            for label, key in (
                ("line", "max_line_loading_percent"),
                ("trafo", "max_trafo_loading_percent"),
            ):
                entry = base.get(key)
                if entry:
                    print(
                        f"    max {label:5s}: {entry['value']:.1f} % "
                        f"(index {entry['index']})"
                    )
            print(
                f"    losses  : {base['losses_mw']:.4f} MW    "
                f"ext_grid: {base['ext_grid_p_mw']:+.4f} MW / "
                f"{base['ext_grid_q_mvar']:+.4f} Mvar"
            )

    for label, key in (
        ("BLOCKING", "blocking"),
        ("WARNING", "warnings"),
        ("INFO", "info"),
    ):
        items = findings[key]
        if items:
            print(f"\n  {label} ({len(items)}):")
            for item in items:
                print(f"    - {item}")

    print("\n  Verdict: " + ("READY for OPF" if payload["ok"] else "NOT READY"))
    print("=" * 68)


def _write_json(payload: Dict[str, Any], json_path: str, output_dir: Optional[str]) -> str:
    """Write payload to json_path, confined to output_dir when given."""
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        json_path = os.path.join(output_dir, os.path.basename(json_path))
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=json_default)
    return json_path


def json_default(obj: Any) -> Any:
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if hasattr(obj, "item"):
        return obj.item()
    if hasattr(obj, "tolist"):
        return obj.tolist()
    return str(obj)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Load, validate, and base-case-solve a pandapower network before "
            "running a potpourri OPF."
        ),
        epilog=(
            "Exit codes: 0 ready for OPF, 1 blocking data problem or base "
            "power flow failure, 2 the case could not be loaded."
        ),
    )
    parser.add_argument(
        "--case",
        required=True,
        help="simbench:<code> (e.g. simbench:1-LV-rural1--0-sw) or a "
        "pandapower JSON file path.",
    )
    parser.add_argument(
        "--profile-index",
        type=int,
        default=None,
        help="Apply this SimBench profile row as a single snapshot. Omit for "
        "the network's own operating point or for multi-period studies.",
    )
    parser.add_argument(
        "--no-power-flow",
        action="store_true",
        help="Skip the pandapower base power flow (data checks only).",
    )
    parser.add_argument(
        "--json",
        metavar="PATH",
        default=None,
        help="Also write the structured payload to this JSON file.",
    )
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        default=None,
        help="Confine --json output to this directory (created if needed).",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.profile_index is not None and args.profile_index < 0:
        build_parser().error("--profile-index must be >= 0")

    try:
        payload = inspect_case(
            args.case,
            profile_index=args.profile_index,
            run_power_flow=not args.no_power_flow,
        )
    except (FileNotFoundError, ValueError, ImportError) as err:
        print(f"ERROR: {type(err).__name__}: {err}", file=sys.stderr)
        return 2

    print_report(payload)
    if args.json:
        path = _write_json(payload, args.json, args.output_dir)
        print(f"\nStructured payload written to {path}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
