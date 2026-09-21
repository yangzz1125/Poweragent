#!/usr/bin/env python3
"""Build, solve, and validate a potpourri OPF over a pandapower network.

Covers steps 4-8 of the potpourri ladder: pick a formulation, configure limits
and controllability, attach an objective, solve with an available solver, and
validate the answer before reporting it.

Three things about potpourri make a naive result extraction wrong, and this
script handles all three:

1. ``net.res_*`` is populated by the model constructor (which runs ``pp.runpp``),
   so it is never empty. When a solve does not reach optimal termination
   potpourri skips the result mapping and ``net.res_*`` still holds the
   *base case*. Results are therefore only read here after
   ``pyo.check_optimal_termination`` passes.
2. Multi-period ``solve(to_net=True)`` does not write ``net.res_*`` at all — it
   only logs that it did. This script calls
   ``pyo_to_net_multi_period.pyo_sol_to_net_res(net, model, t)`` per time step.
3. After a DC OPF, ``net.res_bus.vm_pu`` is a flat 1.0 placeholder, not a
   solved voltage, so no voltage finding is ever derived from a DC run.

Typical usage:
    from solve_opf import solve_case, available_solvers

    print(available_solvers())
    payload = solve_case(
        case="simbench:1-LV-rural1--0-sw",
        formulation="ac",
        objective="voltage_deviation",
        profile_index=672,
    )

CLI:
    python solve_opf.py --case simbench:1-LV-rural1--0-sw --formulation ac \
        --objective voltage_deviation --profile-index 672
    python solve_opf.py --case simbench:1-LV-rural1--0-sw --formulation dc \
        --objective ext_grid_import --solver glpk --profile-index 672
    python solve_opf.py --case simbench:1-LV-rural1--0-sw --horizon 8 \
        --objective voltage_deviation --battery-penetration 20 --seed 0
    python solve_opf.py --list-solvers
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import pyomo.environ as pyo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inspect_case import (  # noqa: E402
    element_counts,
    json_default,
    load_case,
    max_with_index,
)

# Objectives potpourri itself provides, per model class. Anything not in these
# maps is built here as an explicit Pyomo objective, following the pattern in
# the potpourri repo's own scripts/objective_tradeoff_demo.py.
AC_SINGLE_OBJECTIVES = {
    "voltage_deviation": "add_voltage_deviation_objective",
    "reactive_power": "add_reactive_power_flow_objective",
}
AC_MULTI_OBJECTIVES = {
    "voltage_deviation": "add_voltage_deviation_objective",
    "generation": "add_generation_objective",
    "weighted_generation": "add_weighted_generation_objective",
}
# Built here rather than by potpourri.
SCRIPT_OBJECTIVES = ("ext_grid_import", "losses")
# From potpourri.models.cost_objective.
COST_OBJECTIVES = ("poly_cost",)

ALL_OBJECTIVES = sorted(
    set(AC_SINGLE_OBJECTIVES)
    | set(AC_MULTI_OBJECTIVES)
    | set(SCRIPT_OBJECTIVES)
    | set(COST_OBJECTIVES)
)

DEFAULT_SOLVER = {"ac": "ipopt", "dc": "glpk"}
CANDIDATE_SOLVERS = (
    "ipopt",
    "glpk",
    "cbc",
    "gurobi",
    "gurobi_direct_minlp",
    "highs",
    "appsi_highs",
    "bonmin",
    "couenne",
    "mindtpy",
    "scip",
    "cplex",
)

BINDING_TOL_PU = 1e-4      # voltage, p.u.
BINDING_TOL_PCT = 0.5      # branch loading, %
CURTAIL_TOL_MW = 1e-6


# ------------------------------------------------------------------- solvers
def available_solvers(names: Tuple[str, ...] = CANDIDATE_SOLVERS) -> Dict[str, bool]:
    """Probe which Pyomo solvers are actually usable in this environment.

    Pyomo's ASL-backed solvers (bonmin, couenne) print a traceback to stderr
    when the executable is missing even with ``exception_flag=False``, so the
    probe is silenced — otherwise a routine availability check looks like a
    crash.
    """
    out: Dict[str, bool] = {}
    logger = logging.getLogger("pyomo")
    prev_level = logger.level
    logger.setLevel(logging.CRITICAL)
    try:
        for name in names:
            buf = io.StringIO()
            try:
                with contextlib.redirect_stderr(buf), contextlib.redirect_stdout(buf):
                    out[name] = bool(
                        pyo.SolverFactory(name).available(exception_flag=False)
                    )
            except Exception:  # noqa: BLE001 - unavailable is the answer
                out[name] = False
    finally:
        logger.setLevel(prev_level)
    return out


def require_solver(solver: str, formulation: str) -> Tuple[str, Dict[str, bool]]:
    """Resolve and validate the solver, or raise with the available options.

    Checking before building the model matters because potpourri raises a bare
    ``RuntimeError("Attempting to use an unavailable solver")`` from inside
    ``solve()``, after the whole Pyomo model has been constructed.
    """
    avail = available_solvers()
    chosen = solver or DEFAULT_SOLVER[formulation]
    if not avail.get(chosen, False):
        usable = sorted(k for k, v in avail.items() if v)
        raise RuntimeError(
            f"Solver {chosen!r} is not available in this environment. "
            f"Available: {usable or 'none'}. "
            f"A {'nonlinear (AC)' if formulation == 'ac' else 'linear (DC)'} "
            f"formulation needs "
            + (
                "an NLP solver such as IPOPT."
                if formulation == "ac"
                else "an LP/MIP solver such as GLPK, CBC or HiGHS."
            )
        )
    return chosen, avail


# -------------------------------------------------------------------- limits
def configure_limits(
    net,
    v_min: float = 0.95,
    v_max: float = 1.05,
    max_line_loading: float = 100.0,
    max_trafo_loading: float = 100.0,
    controllable_sgen: bool = True,
    allow_curtailment: bool = True,
    ext_grid_p_mw: float = 1e4,
    ext_grid_q_mvar: float = 1e4,
) -> Dict[str, Any]:
    """Write the OPF limits and controllability flags potpourri reads.

    potpourri derives its Pyomo bounds from these pandapower columns at
    ``add_OPF()`` time, so they must exist *before* the model is built. Setting
    them explicitly (rather than relying on defaults) is also what makes the
    reported "binding constraint" statements meaningful: a limit that was never
    set cannot bind.

    Returns the configuration actually applied, for the report.
    """
    if v_min > v_max:
        raise ValueError(f"v_min ({v_min}) must not exceed v_max ({v_max})")
    if max_line_loading <= 0 or max_trafo_loading <= 0:
        raise ValueError("Loading limits must be positive percentages")

    net.bus["min_vm_pu"] = v_min
    net.bus["max_vm_pu"] = v_max
    if len(net.line):
        net.line["max_loading_percent"] = max_line_loading
    if len(net.trafo):
        net.trafo["max_loading_percent"] = max_trafo_loading

    n_ctrl_sgen = 0
    if len(net.sgen) and controllable_sgen:
        net.sgen["controllable"] = True
        # max_p_mw is the *available* output at this snapshot; curtailment is
        # then a reduction below it, never an increase above it.
        net.sgen["max_p_mw"] = net.sgen["p_mw"]
        net.sgen["min_p_mw"] = 0.0 if allow_curtailment else net.sgen["p_mw"]
        n_ctrl_sgen = len(net.sgen)

    if len(net.ext_grid):
        net.ext_grid["max_p_mw"] = ext_grid_p_mw
        net.ext_grid["min_p_mw"] = -ext_grid_p_mw
        net.ext_grid["max_q_mvar"] = ext_grid_q_mvar
        net.ext_grid["min_q_mvar"] = -ext_grid_q_mvar

    return {
        "v_min_pu": v_min,
        "v_max_pu": v_max,
        "max_line_loading_percent": max_line_loading,
        "max_trafo_loading_percent": max_trafo_loading,
        "controllable_sgen": n_ctrl_sgen,
        "sgen_curtailment_allowed": bool(allow_curtailment and n_ctrl_sgen),
        "ext_grid_p_limit_mw": ext_grid_p_mw,
        "ext_grid_q_limit_mvar": ext_grid_q_mvar,
    }


# ----------------------------------------------------------------- objectives
def valid_objectives(formulation: str, multi_period: bool) -> List[str]:
    """List the objectives that are actually defined for this model kind."""
    out = set(AC_MULTI_OBJECTIVES if multi_period else AC_SINGLE_OBJECTIVES)
    if formulation != "ac":
        out = set()
    out.add("ext_grid_import")
    if formulation == "ac":
        out.add("losses")
    if not multi_period:
        out.add("poly_cost")
    return sorted(out)


def validate_objective_choice(
    objective: str, formulation: str, multi_period: bool
) -> None:
    """Reject an impossible objective/formulation pairing before building.

    Constructing the Pyomo model is the expensive step, so catching
    "minimise voltage deviation with a DC model" here rather than in
    :func:`attach_objective` saves the whole build.
    """
    allowed = valid_objectives(formulation, multi_period)
    if objective in allowed:
        return

    kind = "multi-period" if multi_period else "single-period"
    this_helpers = AC_MULTI_OBJECTIVES if multi_period else AC_SINGLE_OBJECTIVES
    other_helpers = AC_SINGLE_OBJECTIVES if multi_period else AC_MULTI_OBJECTIVES

    # The formulation is the stronger constraint: an AC-only objective is
    # unusable on a DC model whichever period kind provides the helper.
    if objective == "losses":
        reason = (
            "the DC model is lossless by construction, so its loss objective "
            "is identically zero"
        )
    elif formulation == "dc":
        reason = "a DC model has no voltage magnitude or reactive power"
    elif objective in other_helpers and objective not in this_helpers:
        reason = (
            f"it is a {'single-period' if multi_period else 'multi-period'} "
            "helper, which this model class does not provide"
        )
    elif objective == "poly_cost":
        reason = (
            "add_poly_cost_objective reads the scalar pG/psG variables, which "
            "are time-indexed in a multi-period model"
        )
    else:
        reason = "it is not defined for this model"

    raise ValueError(
        f"Objective {objective!r} cannot be used with a {kind} "
        f"{formulation.upper()} model: {reason}. Available here: {allowed}."
    )


def attach_objective(opf, objective: str, formulation: str, multi_period: bool) -> str:
    """Attach the requested objective and return the model attribute name.

    Raises ValueError when the objective is not defined for the chosen
    formulation, rather than silently substituting a different one — a DC model
    has no voltage variable, so "minimise voltage deviation" is not a DC study.
    """
    model = opf.model
    helpers = AC_MULTI_OBJECTIVES if multi_period else AC_SINGLE_OBJECTIVES

    if objective in helpers:
        if formulation != "ac":
            raise ValueError(
                f"Objective {objective!r} needs the AC formulation "
                f"(a DC model has no voltage magnitude or reactive power). "
                f"Use --formulation ac, or pick one of "
                f"{sorted(SCRIPT_OBJECTIVES + COST_OBJECTIVES)}."
            )
        getattr(opf, helpers[objective])()
        return {
            "voltage_deviation": "obj_v_deviation",
            "reactive_power": "obj_reactive",
            "generation": "obj",
            "weighted_generation": "obj",
        }[objective]

    if objective == "poly_cost":
        from potpourri.models.cost_objective import add_poly_cost_objective

        if multi_period:
            raise ValueError(
                "poly_cost is a single-period objective: "
                "add_poly_cost_objective reads the scalar pG/psG variables, "
                "which are time-indexed in a multi-period model."
            )
        if "poly_cost" not in opf.net or opf.net.poly_cost.empty:
            raise ValueError(
                "Objective 'poly_cost' needs cost data in net.poly_cost, "
                "which this network does not have. SimBench networks carry no "
                "cost curves — use ext_grid_import or losses instead."
            )
        add_poly_cost_objective(opf, allow_quadratic=(formulation == "ac"))
        return "obj_poly_cost"

    if objective == "ext_grid_import":
        # Same expression as the potpourri repo's objective_tradeoff_demo.py.
        if multi_period:
            expr = sum(
                model.pG[g, t] for g in model.eG for t in model.T
            )
        else:
            expr = sum(model.pG[g] for g in model.eG)
        model.obj_import = pyo.Objective(expr=expr, sense=pyo.minimize)
        return "obj_import"

    if objective == "losses":
        if formulation != "ac":
            raise ValueError(
                "Objective 'losses' needs the AC formulation: the DC model is "
                "lossless by construction, so its loss objective is identically "
                "zero."
            )
        if multi_period:
            expr = sum(
                model.pLfrom[l, t] + model.pLto[l, t]
                for l in model.L
                for t in model.T
            ) + sum(
                model.pThv[tr, t] + model.pTlv[tr, t]
                for tr in model.TRANSF
                for t in model.T
            )
        else:
            expr = sum(
                model.pLfrom[l] + model.pLto[l] for l in model.L
            ) + sum(model.pThv[tr] + model.pTlv[tr] for tr in model.TRANSF)
        model.obj_losses = pyo.Objective(expr=expr, sense=pyo.minimize)
        return "obj_losses"

    raise ValueError(
        f"Unknown objective {objective!r}. Choose from {ALL_OBJECTIVES}."
    )


def objective_interpretation(objective: str, base_mva: float) -> str:
    """State what the objective value means, including its units."""
    return {
        "voltage_deviation": (
            "sum of squared per-unit voltage deviations from 1.0 p.u. "
            "(from the slack's base voltage at reference buses); "
            "dimensionless, 0 is a perfectly flat profile. It puts no value on "
            "energy, so where curtailment is allowed the flattest profile is "
            "usually zero renewable injection — check the reported curtailment "
            "before accepting the dispatch"
        ),
        "reactive_power": (
            "sum of squared static-generator reactive power, in "
            f"(p.u. on {base_mva} MVA)^2; penalises Q use without pricing it"
        ),
        "generation": (
            "sum of squared generator/external-grid active power, in "
            f"(p.u. on {base_mva} MVA)^2; a smoothing proxy, not a cost"
        ),
        "weighted_generation": (
            "4 * sum(external-grid P) + 1 * sum(sgen P) in p.u. on "
            f"{base_mva} MVA. The weights 4 and 1 are hard-coded in potpourri "
            "and carry no economic meaning — treat the value as a ranking "
            "score, not a cost"
        ),
        "ext_grid_import": (
            f"total active power imported through the external grid, p.u. on "
            f"{base_mva} MVA (negative = net export). Minimising it maximises "
            "local generation use"
        ),
        "losses": (
            f"total active branch losses, p.u. on {base_mva} MVA, as the sum "
            "of both branch-end injections"
        ),
        "poly_cost": "total polynomial generation cost from net.poly_cost, in EUR/h",
    }[objective]


# --------------------------------------------------------------------- models
def build_single_period(net, formulation: str, add_opf_kwargs: Dict[str, Any]):
    """Construct a single-period ACOPF or DCOPF and attach OPF constraints."""
    if formulation == "ac":
        from potpourri.models.ACOPF_base import ACOPF

        opf = ACOPF(net)
    else:
        from potpourri.models.DCOPF import DCOPF

        opf = DCOPF(net)
    opf.add_OPF(**add_opf_kwargs)
    return opf


def build_multi_period(
    net,
    formulation: str,
    to_t: int,
    from_t: int,
    add_opf_kwargs: Dict[str, Any],
    battery: Optional[Dict[str, Any]] = None,
):
    """Construct a multi-period model, optionally with batteries attached.

    Devices are attached *before* ``add_OPF()`` so their variables exist when
    the OPF constraints reference them — the order the potpourri example
    scripts use.
    """
    if formulation == "ac":
        from potpourri.models_multi_period.ACOPF_multi_period import (
            ACOPF_multi_period,
        )

        opf = ACOPF_multi_period(net, toT=to_t, fromT=from_t)
    else:
        from potpourri.models_multi_period.DCOPF_multi_period import (
            DCOPF_multi_period,
        )

        opf = DCOPF_multi_period(net, toT=to_t, fromT=from_t)

    battery_info = None
    if battery:
        from potpourri.technologies.battery import Battery_multi_period

        device = Battery_multi_period(opf.net, T=to_t - from_t, **battery)
        device.get_all(opf.model)
        battery_info = {
            "units": int(len(device.random_indexes)),
            "power_pu": float(device.bat_power),
            "capacity_pu_h": float(device.bat_cap),
            "efficiency": float(device.bat_efficiency),
            "soc_min": float(device.bat_soc_min),
            "soc_max": float(device.bat_soc_max),
            "initial_soc": float(
                device.bat_initial_soc_fraction * device.bat_soc_max
            ),
        }

    opf.add_OPF(**add_opf_kwargs)
    return opf, battery_info


# ------------------------------------------------------------------- results
def termination_report(results) -> Dict[str, Any]:
    """Extract the solver outcome without asserting anything about quality."""
    solver = getattr(results, "solver", None)
    return {
        "status": str(getattr(solver, "status", "unknown")),
        "termination_condition": str(
            getattr(solver, "termination_condition", "unknown")
        ),
        "message": str(getattr(solver, "message", "") or ""),
        "optimal_termination": bool(pyo.check_optimal_termination(results)),
    }


def single_period_results(opf, formulation: str, limits: Dict[str, Any]) -> Dict[str, Any]:
    """Summarise a solved single-period model from net.res_* and the model."""
    net = opf.net
    out: Dict[str, Any] = {}

    if formulation == "ac":
        vm = net.res_bus.vm_pu.dropna()
        if len(vm):
            out["vm_pu_min"] = float(vm.min())
            out["vm_pu_min_bus"] = int(vm.idxmin())
            out["vm_pu_max"] = float(vm.max())
            out["vm_pu_max_bus"] = int(vm.idxmax())
    else:
        out["voltage_note"] = (
            "DC formulation: net.res_bus.vm_pu is a flat 1.0 placeholder, not "
            "a solved voltage. No voltage conclusion can be drawn from this run."
        )

    out["max_line_loading_percent"] = max_with_index(net.res_line, "loading_percent")
    out["max_trafo_loading_percent"] = max_with_index(net.res_trafo, "loading_percent")
    out["dispatch"] = _dispatch_summary(net)
    out["curtailment"] = _curtailment_summary(net)
    out["power_balance"] = _power_balance(net, formulation)
    out["binding"] = _binding_constraints(net, formulation, limits)
    out["storage"] = _single_period_storage(opf)
    return out


def _dispatch_summary(net) -> Dict[str, Any]:
    """Active/reactive dispatch by element group, in MW / Mvar."""
    def _sum(table, col):
        df = net[table]
        return float(df[col].sum()) if len(df) and col in df.columns else 0.0

    return {
        "ext_grid_p_mw": _sum("res_ext_grid", "p_mw"),
        "ext_grid_q_mvar": _sum("res_ext_grid", "q_mvar"),
        "gen_p_mw": _sum("res_gen", "p_mw"),
        "sgen_p_mw": _sum("res_sgen", "p_mw"),
        "sgen_q_mvar": _sum("res_sgen", "q_mvar"),
        "load_p_mw": _sum("res_load", "p_mw"),
        "storage_p_mw": _sum("res_storage", "p_mw"),
    }


def _multi_period_curtailment(model) -> Optional[Dict[str, Any]]:
    """Curtailment for a multi-period model, read from the model itself.

    In a multi-period model the available sgen power is the SimBench profile
    value held in ``model.PsG[g, t]`` — not ``net.sgen.max_p_mw``, which only
    carries the network's static snapshot. ``model.sPGmax`` equals ``PsG`` and
    ``model.sPGmin`` is hard-coded to 0, so curtailment down to zero is always
    permitted here regardless of what ``net.sgen.min_p_mw`` says.
    """
    if not hasattr(model, "sGc") or not len(list(model.sGc)):
        return None
    base = float(pyo.value(model.baseMVA))
    dt = float(pyo.value(model.deltaT))
    avail_mwh = 0.0
    curtailed_mwh = 0.0
    per_sgen: Dict[int, float] = {}
    for g in model.sGc:
        for t in model.T:
            avail = float(pyo.value(model.PsG[g, t])) * base
            actual = float(pyo.value(model.psG[g, t])) * base
            gap = max(avail - actual, 0.0)
            avail_mwh += avail * dt
            curtailed_mwh += gap * dt
            if gap > CURTAIL_TOL_MW:
                per_sgen[int(g)] = per_sgen.get(int(g), 0.0) + gap * dt
    return {
        "available_mwh": avail_mwh,
        "curtailed_mwh": curtailed_mwh,
        "dispatched_mwh": avail_mwh - curtailed_mwh,
        "curtailed_percent": (
            curtailed_mwh / avail_mwh * 100.0 if avail_mwh > 0 else 0.0
        ),
        "curtailed_sgens": sorted(per_sgen),
        "source": "model.PsG (SimBench profile) vs model.psG (dispatch)",
    }


def _curtailment_summary(net) -> Optional[Dict[str, Any]]:
    """Compare solved sgen output against the available max_p_mw."""
    if not len(net.sgen) or "max_p_mw" not in net.sgen.columns:
        return None
    if not len(net.res_sgen):
        return None
    available = net.sgen["max_p_mw"].astype(float)
    actual = net.res_sgen["p_mw"].astype(float)
    common = available.index.intersection(actual.index)
    if not len(common):
        return None
    delta = (available.loc[common] - actual.loc[common]).clip(lower=0.0)
    curtailed = delta[delta > CURTAIL_TOL_MW]
    total_avail = float(available.loc[common].sum())
    return {
        "available_mw": total_avail,
        "dispatched_mw": float(actual.loc[common].sum()),
        "curtailed_mw": float(delta.sum()),
        "curtailed_percent": (
            float(delta.sum() / total_avail * 100.0) if total_avail > 0 else 0.0
        ),
        "curtailed_sgens": [int(i) for i in curtailed.index[:20]],
    }


def _power_balance(net, formulation: str) -> Dict[str, Any]:
    """Check generation - load - losses against zero."""
    def _sum(table, col):
        df = net[table]
        return float(df[col].sum()) if len(df) and col in df.columns else 0.0

    gen = (
        _sum("res_ext_grid", "p_mw")
        + _sum("res_gen", "p_mw")
        + _sum("res_sgen", "p_mw")
    )
    load = _sum("res_load", "p_mw") + _sum("res_storage", "p_mw")
    losses = _sum("res_line", "pl_mw") + _sum("res_trafo", "pl_mw")
    if formulation == "dc":
        losses = 0.0
    residual = gen - load - losses
    scale = max(abs(gen), abs(load), 1e-9)
    return {
        "generation_mw": gen,
        "load_mw": load,
        "losses_mw": losses,
        "residual_mw": residual,
        "residual_relative": abs(residual) / scale,
        "balanced": abs(residual) / scale < 1e-3,
        "note": (
            "DC formulation is lossless by construction, so losses are "
            "excluded from the balance."
            if formulation == "dc"
            else ""
        ),
    }


def _binding_constraints(net, formulation: str, limits: Dict[str, Any]) -> Dict[str, List[str]]:
    """Report which configured limits the solution sits on.

    Compares solved values against the limits that were actually configured, so
    the statement "this constraint binds" always refers to a real input.
    """
    binding: List[str] = []
    violated: List[str] = []

    v_min = limits.get("v_min_pu")
    v_max = limits.get("v_max_pu")
    if formulation == "ac" and len(net.res_bus) and v_min is not None:
        vm = net.res_bus.vm_pu.dropna()
        for bus, val in vm.items():
            if val <= v_min + BINDING_TOL_PU:
                (violated if val < v_min - BINDING_TOL_PU else binding).append(
                    f"bus {int(bus)} vm_pu={val:.5f} at lower limit {v_min}"
                )
            elif val >= v_max - BINDING_TOL_PU:
                (violated if val > v_max + BINDING_TOL_PU else binding).append(
                    f"bus {int(bus)} vm_pu={val:.5f} at upper limit {v_max}"
                )

    for table, res_table, key in (
        ("line", "res_line", "max_line_loading_percent"),
        ("trafo", "res_trafo", "max_trafo_loading_percent"),
    ):
        limit = limits.get(key)
        if limit is None or not len(net[res_table]):
            continue
        loading = net[res_table]["loading_percent"].dropna()
        for idx, val in loading.items():
            if val >= limit - BINDING_TOL_PCT:
                target = violated if val > limit + BINDING_TOL_PCT else binding
                target.append(
                    f"{table} {int(idx)} loading={val:.2f}% against limit {limit}%"
                )

    return {"binding": binding[:30], "violated": violated[:30]}


def _single_period_storage(opf) -> Optional[Dict[str, Any]]:
    """Read the single-period storage block if the network had storage."""
    model = opf.model
    if not hasattr(model, "STOR") or not len(list(model.STOR)):
        return None
    base = float(pyo.value(model.baseMVA))
    rows = []
    for s in model.STOR:
        rows.append(
            {
                "storage": int(s),
                "p_charge_mw": float(pyo.value(model.STOR_Pchg[s])) * base,
                "p_discharge_mw": float(pyo.value(model.STOR_Pdis[s])) * base,
                "soc": float(pyo.value(model.STOR_SOC[s])),
            }
        )
    simultaneous = [
        r["storage"]
        for r in rows
        if r["p_charge_mw"] > 1e-6 and r["p_discharge_mw"] > 1e-6
    ]
    return {
        "units": rows[:20],
        "simultaneous_charge_discharge": simultaneous,
        "note": (
            "potpourri relaxes the no-simultaneous-charge/discharge "
            "complementarity to Pchg + Pdis <= Pmax, so a small overlap is "
            "possible and is listed above when present."
        ),
    }


def multi_period_results(opf, formulation: str, limits: Dict[str, Any]) -> Dict[str, Any]:
    """Summarise a solved multi-period model, mapping each step explicitly.

    Multi-period ``solve()`` never writes ``net.res_*``, so the mapping is done
    here per time step via potpourri's own post-processing helper.
    """
    from potpourri.models_multi_period.pyo_to_net_multi_period import (
        pyo_sol_to_net_res,
    )

    model = opf.model
    steps = list(model.T)
    per_step: List[Dict[str, Any]] = []
    for t in steps:
        pyo_sol_to_net_res(opf.net, model, t)
        entry: Dict[str, Any] = {"t": int(t)}
        if formulation == "ac":
            vm = opf.net.res_bus.vm_pu.dropna()
            if len(vm):
                entry.update(
                    vm_pu_min=float(vm.min()),
                    vm_pu_min_bus=int(vm.idxmin()),
                    vm_pu_max=float(vm.max()),
                    vm_pu_max_bus=int(vm.idxmax()),
                )
        entry["max_line_loading_percent"] = max_with_index(
            opf.net.res_line, "loading_percent"
        )
        entry["max_trafo_loading_percent"] = max_with_index(
            opf.net.res_trafo, "loading_percent"
        )
        entry["dispatch"] = _dispatch_summary(opf.net)
        entry["power_balance"] = _power_balance(opf.net, formulation)
        entry["binding"] = _binding_constraints(opf.net, formulation, limits)
        per_step.append(entry)

    out: Dict[str, Any] = {
        "n_steps": len(steps),
        "first_step": int(steps[0]),
        "last_step": int(steps[-1]),
        "step_hours": float(pyo.value(model.deltaT)),
        "horizon_hours": len(steps) * float(pyo.value(model.deltaT)),
        "per_step": per_step,
        "mapping_note": (
            "Multi-period solve(to_net=True) does not populate net.res_*; each "
            "step above was mapped explicitly with "
            "pyo_to_net_multi_period.pyo_sol_to_net_res(net, model, t)."
        ),
    }

    if formulation == "ac":
        mins = [s["vm_pu_min"] for s in per_step if "vm_pu_min" in s]
        maxs = [s["vm_pu_max"] for s in per_step if "vm_pu_max" in s]
        if mins and maxs:
            worst_lo = min(range(len(mins)), key=lambda i: mins[i])
            worst_hi = max(range(len(maxs)), key=lambda i: maxs[i])
            out["vm_pu_min"] = mins[worst_lo]
            out["vm_pu_min_at"] = {
                "t": per_step[worst_lo]["t"],
                "bus": per_step[worst_lo]["vm_pu_min_bus"],
            }
            out["vm_pu_max"] = maxs[worst_hi]
            out["vm_pu_max_at"] = {
                "t": per_step[worst_hi]["t"],
                "bus": per_step[worst_hi]["vm_pu_max_bus"],
            }

    loadings = [
        (s["max_line_loading_percent"], s["t"])
        for s in per_step
        if s.get("max_line_loading_percent")
    ]
    if loadings:
        worst, t_at = max(loadings, key=lambda item: item[0]["value"])
        out["max_line_loading_percent"] = worst
        out["max_line_loading_at_t"] = t_at
    trafo_loadings = [
        (s["max_trafo_loading_percent"], s["t"])
        for s in per_step
        if s.get("max_trafo_loading_percent")
    ]
    if trafo_loadings:
        worst_tr, t_at = max(trafo_loadings, key=lambda item: item[0]["value"])
        out["max_trafo_loading_percent"] = worst_tr
        out["max_trafo_loading_at_t"] = t_at

    out["binding"] = {
        "binding": sorted({b for s in per_step for b in s["binding"]["binding"]})[:30],
        "violated": sorted({b for s in per_step for b in s["binding"]["violated"]})[:30],
    }

    # Horizon aggregates. Energy uses deltaT, which potpourri fixes at 0.25 h.
    dt = float(pyo.value(model.deltaT))
    out["energy"] = {
        key.replace("_p_mw", "_mwh").replace("_q_mvar", "_mvarh"): sum(
            s["dispatch"][key] for s in per_step
        ) * dt
        for key in per_step[0]["dispatch"]
    }
    out["dispatch"] = {
        key: sum(s["dispatch"][key] for s in per_step) / len(per_step)
        for key in per_step[0]["dispatch"]
    }
    out["dispatch_note"] = "Values are horizon means in MW / Mvar; see 'energy' for MWh."

    worst_bal = max(
        (s["power_balance"] for s in per_step),
        key=lambda b: b["residual_relative"],
    )
    out["power_balance"] = dict(
        worst_bal,
        note="Worst per-step residual over the horizon. " + worst_bal.get("note", ""),
    )

    out["curtailment"] = _multi_period_curtailment(model)
    out["reverse_flow_mw"] = min(
        s["dispatch"]["ext_grid_p_mw"] for s in per_step
    )
    out["battery"] = _battery_trajectories(model)
    return out


def _battery_trajectories(model) -> Optional[Dict[str, Any]]:
    """Extract SOC / power trajectories and check the SOC window."""
    if not hasattr(model, "BAT") or not len(list(model.BAT)):
        return None
    steps = list(model.T)
    units = []
    for b in model.BAT:
        soc = [float(pyo.value(model.BAT_SOC[b, t])) for t in steps]
        power = [float(pyo.value(model.BAT_P[b, t])) for t in steps]
        units.append(
            {
                "battery": int(b),
                "soc_min": min(soc),
                "soc_max": max(soc),
                "soc_initial": soc[0],
                "soc_final": soc[-1],
                "p_min_pu": min(power),
                "p_max_pu": max(power),
                "energy_throughput_pu_h": sum(
                    abs(p) for p in power
                ) * float(pyo.value(model.deltaT)),
            }
        )
    soc_lo = float(min(pyo.value(model.BAT_SOCmin[b]) for b in model.BAT))
    soc_hi = float(max(pyo.value(model.BAT_SOCmax[b]) for b in model.BAT))
    out_of_window = [
        u["battery"]
        for u in units
        if u["soc_min"] < soc_lo - 1e-6 or u["soc_max"] > soc_hi + 1e-6
    ]
    return {
        "units": units[:20],
        "soc_bounds": {"min": soc_lo, "max": soc_hi},
        "soc_outside_bounds": out_of_window,
        "modelling_caveats": [
            "SOC is bounded on every step except the first, which is pinned to "
            "BAT_SOC_init; there is no terminal-SOC constraint, so the battery "
            "may legitimately finish the horizon empty.",
            "The SOC update is SOC[t] = SOC[t-1] + deltaT * BAT_P[t] * eff / cap "
            "with a single signed power variable, so a charge/discharge cycle "
            "returns exactly to its starting SOC. The efficiency scales the "
            "power-to-SOC ratio but produces no round-trip loss — do not read "
            "the result as an economic storage dispatch.",
        ],
    }


# ------------------------------------------------------------------ escalation
def escalation_triggers(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    """Map quantified findings to the powerskills-engineering playbooks."""
    out: List[Dict[str, str]] = []
    limits = payload["configuration"]["limits"]
    term = payload["solver"]
    results = payload.get("results") or {}
    formulation = payload["configuration"]["formulation"]

    if not term["optimal_termination"]:
        condition = term["termination_condition"].lower()
        # Separate "the model has no feasible point" from "the solver failed to
        # find one". They need different playbooks: the first is a constraint
        # or data problem, the second is numerical.
        if "infeasible" in condition or "unbounded" in condition:
            kind = (
                "The model has no feasible point (or is unbounded): this is a "
                "constraint, bound, or data problem, not a solver problem."
            )
            skill = "operations-planning-mitigation"
        else:
            kind = (
                "The solver stopped without proving optimality or "
                "infeasibility, which points at initialisation, scaling, or "
                "iteration/time limits rather than the constraint set."
            )
            skill = "convergence-failure-mitigation"
        out.append(
            {
                "observation": (
                    f"Solver {term['solver']} returned status={term['status']}, "
                    f"termination_condition={term['termination_condition']}. "
                    f"{kind} No results are reported."
                ),
                "escalate_to": skill,
            }
        )
        return out

    v_min = limits["v_min_pu"]
    v_max = limits["v_max_pu"]
    if formulation == "ac" and "vm_pu_min" in results:
        lo, hi = results["vm_pu_min"], results["vm_pu_max"]
        if lo < v_min - BINDING_TOL_PU or hi > v_max + BINDING_TOL_PU:
            where_lo = results.get("vm_pu_min_bus", results.get("vm_pu_min_at"))
            where_hi = results.get("vm_pu_max_bus", results.get("vm_pu_max_at"))
            out.append(
                {
                    "observation": (
                        f"Bus voltage outside the configured band "
                        f"[{v_min}, {v_max}] pu: min {lo:.4f} pu at {where_lo}, "
                        f"max {hi:.4f} pu at {where_hi}."
                    ),
                    "escalate_to": "voltage-violation-mitigation",
                }
            )

    for label, key, limit_key in (
        ("Line", "max_line_loading_percent", "max_line_loading_percent"),
        ("Transformer", "max_trafo_loading_percent", "max_trafo_loading_percent"),
    ):
        entry = results.get(key)
        limit = limits[limit_key]
        if entry and entry["value"] > limit + BINDING_TOL_PCT:
            out.append(
                {
                    "observation": (
                        f"{label} {entry['index']} at {entry['value']:.1f}% "
                        f"loading against its configured {limit}% rating."
                    ),
                    "escalate_to": "thermal-overload-mitigation",
                }
            )

    curt = results.get("curtailment")
    if curt and curt["curtailed_percent"] > 5.0:
        unit = "MWh" if "curtailed_mwh" in curt else "MW"
        cut = curt.get("curtailed_mwh", curt.get("curtailed_mw"))
        avail = curt.get("available_mwh", curt.get("available_mw"))
        out.append(
            {
                "observation": (
                    f"{cut:.4f} {unit} of {avail:.4f} {unit} available "
                    f"renewable output curtailed "
                    f"({curt['curtailed_percent']:.1f}%), sgens "
                    f"{curt['curtailed_sgens']}."
                ),
                "escalate_to": "operations-planning-mitigation",
            }
        )

    balance = results.get("power_balance")
    if balance and not balance["balanced"]:
        out.append(
            {
                "observation": (
                    f"Power balance residual {balance['residual_mw']:+.6f} MW "
                    f"({balance['residual_relative']:.2%} of throughput) — the "
                    "extracted solution does not close."
                ),
                "escalate_to": "operations-planning-mitigation",
            }
        )

    if results.get("reverse_flow_mw", 0.0) < 0.0:
        out.append(
            {
                "observation": (
                    f"Net export through the external grid "
                    f"({results['reverse_flow_mw']:.4f} MW): the feeder is "
                    "reverse-fed by distributed generation."
                ),
                "escalate_to": "der-hosting-capacity-mitigation",
            }
        )
    return out


# ------------------------------------------------------------------- top level
def solve_case(
    case: str,
    formulation: str = "ac",
    objective: str = "voltage_deviation",
    solver: Optional[str] = None,
    profile_index: Optional[int] = None,
    horizon: Optional[int] = None,
    from_t: int = 0,
    v_min: float = 0.95,
    v_max: float = 1.05,
    max_line_loading: float = 100.0,
    max_trafo_loading: float = 100.0,
    allow_curtailment: bool = True,
    thermal_limit: str = "current",
    angle_limits: bool = False,
    time_limit: int = 600,
    max_iter: Optional[int] = None,
    battery_penetration: Optional[float] = None,
    battery_power_pu: float = 0.006,
    battery_capacity_pu_h: float = 0.015,
    battery_efficiency: float = 0.9,
    seed: Optional[int] = None,
    print_solver_output: bool = False,
) -> Dict[str, Any]:
    """Run one potpourri OPF end to end and return a structured payload.

    Args:
        case: ``simbench:<code>`` or a pandapower JSON path.
        formulation: ``"ac"`` (nonlinear, voltages and reactive power) or
            ``"dc"`` (linear, active power only).
        objective: One of :data:`ALL_OBJECTIVES`.
        solver: Pyomo solver name; defaults to IPOPT for AC and GLPK for DC.
        profile_index: SimBench profile row for a single-period snapshot.
        horizon: Number of time steps for a multi-period study. ``None`` runs a
            single period. Multi-period needs a network with SimBench profiles.
        battery_penetration: Percentage of non-slack buses to equip with a
            battery (multi-period only).
        seed: NumPy seed. Battery placement is random, so a seed is required
            for a reproducible multi-period battery study.
    """
    if formulation not in ("ac", "dc"):
        raise ValueError(f"formulation must be 'ac' or 'dc', got {formulation!r}")
    if objective not in ALL_OBJECTIVES:
        raise ValueError(
            f"Unknown objective {objective!r}. Choose from {ALL_OBJECTIVES}."
        )
    if thermal_limit not in ("current", "mva"):
        raise ValueError("thermal_limit must be 'current' or 'mva'")
    multi_period = horizon is not None
    if multi_period:
        if horizon < 2:
            raise ValueError("horizon must be at least 2 time steps")
        if from_t < 0:
            raise ValueError("from_t must be >= 0")
        if profile_index is not None:
            raise ValueError(
                "profile_index pins a single snapshot and cannot be combined "
                "with horizon; drop one of them."
            )
        if not allow_curtailment:
            raise ValueError(
                "Curtailment cannot be blocked in a multi-period model: "
                "Sgens_multi_period.static_generation_real_power_limits sets "
                "sPGmin to 0 for every controllable sgen and time step, "
                "ignoring net.sgen.min_p_mw. Either accept curtailment as "
                "available flexibility, or run single-period snapshots where "
                "min_p_mw is honoured."
            )
    validate_objective_choice(objective, formulation, multi_period)
    if battery_penetration is not None:
        if not multi_period:
            raise ValueError(
                "Batteries are a multi-period device (Battery_multi_period); "
                "pass horizon to run a multi-period study."
            )
        if not 0 < battery_penetration <= 100:
            raise ValueError("battery_penetration must be in (0, 100]")

    chosen_solver, avail = require_solver(solver, formulation)

    if seed is not None:
        import numpy as np

        np.random.seed(seed)

    net, meta = load_case(case, profile_index=profile_index)
    if multi_period and not meta["has_profiles"]:
        raise ValueError(
            f"{case} carries no time-series profiles, so a {horizon}-step "
            "multi-period model cannot be built. potpourri's multi-period "
            "models read net.profiles (SimBench). Use a simbench: case, or "
            "run single-period snapshots instead."
        )
    if multi_period and meta["profile_rows"] is not None:
        if from_t + horizon > meta["profile_rows"]:
            raise ValueError(
                f"from_t + horizon = {from_t + horizon} exceeds the "
                f"{meta['profile_rows']} available profile rows."
            )

    limits = configure_limits(
        net,
        v_min=v_min,
        v_max=v_max,
        max_line_loading=max_line_loading,
        max_trafo_loading=max_trafo_loading,
        allow_curtailment=allow_curtailment,
    )

    # The multi-period add_OPF surface is narrower than the single-period one:
    # ACOPF_multi_period._calc_opf_parameters() takes no keyword arguments, so
    # thermal_limit and angle_limits raise TypeError there rather than being
    # ignored. Refuse them up front instead of failing deep inside potpourri.
    add_opf_kwargs: Dict[str, Any] = {}
    if multi_period:
        if thermal_limit != "current":
            raise ValueError(
                "thermal_limit is a single-period option: "
                "ACOPF_multi_period.add_OPF does not accept it. The "
                "multi-period AC model always uses the current-limit form "
                "|S|^2 <= SLmax^2 * v^2."
            )
        if angle_limits:
            raise ValueError(
                "angle_limits is a single-period option: the multi-period "
                "models implement no branch phase-angle-difference "
                "constraints."
            )
    else:
        if formulation == "ac":
            add_opf_kwargs["thermal_limit"] = thermal_limit
        if angle_limits:
            add_opf_kwargs["angle_limits"] = True

    battery_cfg = None
    if battery_penetration is not None:
        battery_cfg = {
            "penetration": battery_penetration,
            "power_pu": battery_power_pu,
            "capacity_pu_h": battery_capacity_pu_h,
            "efficiency": battery_efficiency,
        }

    build_start = time.perf_counter()
    battery_info = None
    if multi_period:
        opf, battery_info = build_multi_period(
            net, formulation, from_t + horizon, from_t, add_opf_kwargs, battery_cfg
        )
    else:
        opf = build_single_period(net, formulation, add_opf_kwargs)
    obj_attr = attach_objective(opf, objective, formulation, multi_period)
    build_seconds = time.perf_counter() - build_start

    payload: Dict[str, Any] = {
        "meta": meta,
        "configuration": {
            "formulation": formulation,
            "study": "multi_period" if multi_period else "single_period",
            "objective": objective,
            "objective_source": (
                "potpourri helper"
                if objective in (AC_MULTI_OBJECTIVES if multi_period else AC_SINGLE_OBJECTIVES)
                else "potpourri.models.cost_objective"
                if objective in COST_OBJECTIVES
                else "built by this script as an explicit Pyomo objective"
            ),
            "objective_interpretation": objective_interpretation(
                objective, float(net.sn_mva)
            ),
            "limits": limits,
            "add_OPF_kwargs": add_opf_kwargs,
            "elements": element_counts(opf.net),
            "battery": battery_info,
            "seed": seed,
        },
        "model": {
            "class": type(opf).__name__,
            "build_seconds": build_seconds,
            "n_variables": int(
                sum(1 for v in opf.model.component_data_objects(pyo.Var))
            ),
            "n_constraints": int(
                sum(1 for c in opf.model.component_data_objects(pyo.Constraint))
            ),
        },
    }

    solve_start = time.perf_counter()
    results = opf.solve(
        solver=chosen_solver,
        print_solver_output=print_solver_output,
        time_limit=time_limit,
        max_iter=max_iter,
    )
    solve_seconds = time.perf_counter() - solve_start

    term = termination_report(results)
    term.update(
        solver=chosen_solver,
        solve_seconds=solve_seconds,
        available_solvers=sorted(k for k, v in avail.items() if v),
        time_limit_honoured=chosen_solver.startswith("gurobi")
        or chosen_solver == "mindtpy",
    )
    payload["solver"] = term

    if not term["optimal_termination"]:
        payload["results"] = None
        payload["results_note"] = (
            "Solve did not reach optimal termination, so no results are "
            "reported. potpourri skips its net.res_* mapping in this case, "
            "but net.res_* still holds the constructor's base-case power flow "
            "— reading it now would report the base case as if it were the "
            "optimisation result."
        )
        payload["escalation"] = escalation_triggers(payload)
        payload["ok"] = False
        return payload

    payload["objective_value"] = float(pyo.value(getattr(opf.model, obj_attr)))
    if multi_period:
        payload["results"] = multi_period_results(opf, formulation, limits)
    else:
        payload["results"] = single_period_results(opf, formulation, limits)
        payload["results"]["reverse_flow_mw"] = payload["results"]["dispatch"][
            "ext_grid_p_mw"
        ]
    payload["escalation"] = escalation_triggers(payload)
    payload["ok"] = True
    return payload


def print_report(payload: Dict[str, Any]) -> None:
    """Print the engineering summary, quantified and unit-labelled."""
    cfg = payload["configuration"]
    meta = payload["meta"]
    solver = payload["solver"]
    res = payload.get("results")

    print("=" * 68)
    print(f"potpourri {cfg['formulation'].upper()} OPF: {meta['case']}")
    print("=" * 68)
    print(
        f"  network      : {cfg['elements']['bus']} buses, "
        f"{cfg['elements']['line']} lines, {cfg['elements']['trafo']} trafos, "
        f"{cfg['elements']['sgen']} sgens, {cfg['elements']['load']} loads "
        f"(baseMVA {meta['sn_mva']})"
    )
    print(f"  study        : {cfg['study']}   model class {payload['model']['class']}")
    if cfg["study"] == "multi_period" and res:
        print(
            f"  horizon      : {res['n_steps']} steps x {res['step_hours']} h "
            f"= {res['horizon_hours']} h  (t={res['first_step']}..{res['last_step']})"
        )
    elif meta.get("profile_index") is not None:
        print(f"  snapshot     : profile row {meta['profile_index']}")
    print(
        f"  limits       : vm [{cfg['limits']['v_min_pu']}, "
        f"{cfg['limits']['v_max_pu']}] pu, line "
        f"{cfg['limits']['max_line_loading_percent']}%, trafo "
        f"{cfg['limits']['max_trafo_loading_percent']}%"
    )
    print(
        f"  controllable : {cfg['limits']['controllable_sgen']} sgen(s), "
        f"curtailment {'allowed' if cfg['limits']['sgen_curtailment_allowed'] else 'blocked'}"
    )
    if cfg.get("battery"):
        bat = cfg["battery"]
        print(
            f"  batteries    : {bat['units']} units, P={bat['power_pu']} pu, "
            f"E={bat['capacity_pu_h']} pu.h, eta={bat['efficiency']}, "
            f"SOC0={bat['initial_soc']} (seed {cfg['seed']})"
        )
    print(
        f"  model size   : {payload['model']['n_variables']} vars, "
        f"{payload['model']['n_constraints']} constraints, built in "
        f"{payload['model']['build_seconds']:.2f} s"
    )
    print(f"\n  objective    : {cfg['objective']} ({cfg['objective_source']})")
    print(f"                 {cfg['objective_interpretation']}")
    print(
        f"  solver       : {solver['solver']}  "
        f"(available: {', '.join(solver['available_solvers']) or 'none'})"
    )
    print(
        f"  termination  : status={solver['status']}, "
        f"condition={solver['termination_condition']} in "
        f"{solver['solve_seconds']:.2f} s"
    )
    if not solver["time_limit_honoured"]:
        print(
            "                 note: this solver ignores time_limit "
            "(only mindtpy and gurobi* honour it)"
        )

    if res is None:
        print(f"\n  NO RESULTS: {payload['results_note']}")
    else:
        print(f"\n  objective value: {payload['objective_value']:.6g}")
        if cfg["formulation"] == "ac":
            if "vm_pu_min" in res:
                lo_at = res.get("vm_pu_min_bus", res.get("vm_pu_min_at"))
                hi_at = res.get("vm_pu_max_bus", res.get("vm_pu_max_at"))
                print(
                    f"  voltage      : {res['vm_pu_min']:.4f} pu at {lo_at} .. "
                    f"{res['vm_pu_max']:.4f} pu at {hi_at}"
                )
        else:
            print(f"  voltage      : n/a - {res['voltage_note']}")
        for label, key, at_key in (
            ("line", "max_line_loading_percent", "max_line_loading_at_t"),
            ("trafo", "max_trafo_loading_percent", "max_trafo_loading_at_t"),
        ):
            entry = res.get(key)
            if entry:
                at_t = res.get(at_key)
                extra = f" at t={at_t}" if at_t is not None else ""
                print(
                    f"  max {label:6s}: {entry['value']:.2f}% "
                    f"(index {entry['index']}){extra}"
                )
        bal = res.get("power_balance")
        if bal:
            print(
                f"  balance      : gen {bal['generation_mw']:.4f} MW - load "
                f"{bal['load_mw']:.4f} MW - losses {bal['losses_mw']:.4f} MW "
                f"= {bal['residual_mw']:+.2e} MW "
                f"({'OK' if bal['balanced'] else 'DOES NOT CLOSE'})"
            )
        disp = res.get("dispatch")
        if disp:
            suffix = " (horizon mean)" if cfg["study"] == "multi_period" else ""
            print(
                f"  dispatch{suffix:14s}: ext_grid {disp['ext_grid_p_mw']:+.4f} MW / "
                f"{disp['ext_grid_q_mvar']:+.4f} Mvar, sgen "
                f"{disp['sgen_p_mw']:.4f} MW, gen {disp['gen_p_mw']:.4f} MW, "
                f"load {disp['load_p_mw']:.4f} MW"
            )
        energy = res.get("energy")
        if energy:
            print(
                f"  energy       : ext_grid {energy['ext_grid_mwh']:+.5f} MWh, "
                f"sgen {energy['sgen_mwh']:.5f} MWh, load "
                f"{energy['load_mwh']:.5f} MWh over {res['horizon_hours']} h"
            )
        curt = res.get("curtailment")
        if curt:
            if "curtailed_mwh" in curt:
                print(
                    f"  curtailment  : {curt['curtailed_mwh']:.5f} MWh of "
                    f"{curt['available_mwh']:.5f} MWh available "
                    f"({curt['curtailed_percent']:.2f}%)"
                )
            else:
                print(
                    f"  curtailment  : {curt['curtailed_mw']:.5f} MW of "
                    f"{curt['available_mw']:.5f} MW available "
                    f"({curt['curtailed_percent']:.2f}%)"
                )
        bat = res.get("battery")
        if bat:
            print(f"  batteries    : SOC window {bat['soc_bounds']}")
            for unit in bat["units"][:5]:
                print(
                    f"    bat {unit['battery']:>3}: SOC "
                    f"{unit['soc_min']:.3f}..{unit['soc_max']:.3f} "
                    f"(start {unit['soc_initial']:.3f}, end {unit['soc_final']:.3f}), "
                    f"P {unit['p_min_pu']:+.5f}..{unit['p_max_pu']:+.5f} pu"
                )
            if bat["soc_outside_bounds"]:
                print(f"    SOC OUTSIDE BOUNDS: {bat['soc_outside_bounds']}")
            for caveat in bat["modelling_caveats"]:
                print(f"    caveat: {caveat}")
        stor = res.get("storage")
        if stor:
            for unit in stor["units"][:5]:
                print(
                    f"    storage {unit['storage']}: charge "
                    f"{unit['p_charge_mw']:.5f} MW, discharge "
                    f"{unit['p_discharge_mw']:.5f} MW, SOC {unit['soc']:.4f}"
                )
            if stor["simultaneous_charge_discharge"]:
                print(
                    "    simultaneous charge+discharge on "
                    f"{stor['simultaneous_charge_discharge']} — {stor['note']}"
                )
        binding = res.get("binding")
        if binding:
            if binding["binding"]:
                print(f"  binding constraints ({len(binding['binding'])}):")
                for item in binding["binding"][:10]:
                    print(f"    - {item}")
            else:
                print("  binding constraints: none at tolerance")
            if binding["violated"]:
                print(f"  VIOLATED ({len(binding['violated'])}):")
                for item in binding["violated"][:10]:
                    print(f"    - {item}")

    esc = payload.get("escalation") or []
    if esc:
        print(f"\n  Escalation ({len(esc)}):")
        for row in esc:
            print(f"    -> {row['escalate_to']}")
            print(f"       {row['observation']}")
    else:
        print("\n  Escalation: none triggered")
    print("=" * 68)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build, solve, and validate a potpourri OPF over a pandapower "
            "network."
        ),
        epilog=(
            "Exit codes: 0 solved and validated, 1 solved but not optimal "
            "termination, 2 invalid input or unloadable case, 3 no compatible "
            "solver available."
        ),
    )
    parser.add_argument(
        "--case",
        help="simbench:<code> or a pandapower JSON file path.",
    )
    parser.add_argument(
        "--formulation",
        choices=("ac", "dc"),
        default="ac",
        help="ac = nonlinear with voltages and reactive power (default); "
        "dc = linear active-power screening.",
    )
    parser.add_argument(
        "--objective",
        choices=ALL_OBJECTIVES,
        default="voltage_deviation",
        help="Objective to minimise (default: voltage_deviation).",
    )
    parser.add_argument(
        "--solver",
        default=None,
        help="Pyomo solver name. Default: ipopt for AC, glpk for DC.",
    )
    parser.add_argument(
        "--profile-index",
        type=int,
        default=None,
        help="SimBench profile row for a single snapshot.",
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=None,
        help="Number of time steps for a multi-period study (needs a network "
        "with SimBench profiles). Omit for a single period.",
    )
    parser.add_argument(
        "--from-t", type=int, default=0, help="First time step (default 0)."
    )
    parser.add_argument("--v-min", type=float, default=0.95, help="Minimum bus voltage, pu.")
    parser.add_argument("--v-max", type=float, default=1.05, help="Maximum bus voltage, pu.")
    parser.add_argument(
        "--max-line-loading", type=float, default=100.0, help="Line rating, %%."
    )
    parser.add_argument(
        "--max-trafo-loading", type=float, default=100.0, help="Transformer rating, %%."
    )
    parser.add_argument(
        "--no-curtailment",
        action="store_true",
        help="Pin controllable sgens to their available output instead of "
        "allowing curtailment down to zero.",
    )
    parser.add_argument(
        "--thermal-limit",
        choices=("current", "mva"),
        default="current",
        help="AC branch limit form: 'current' (|S| <= SLmax*v, distribution "
        "conductors) or 'mva' (constant MVA, MATPOWER/PGLib convention).",
    )
    parser.add_argument(
        "--angle-limits",
        action="store_true",
        help="Enforce branch phase-angle-difference limits from "
        "net.line.angmin_degree / angmax_degree.",
    )
    parser.add_argument("--time-limit", type=int, default=600, help="Solver time limit, s.")
    parser.add_argument("--max-iter", type=int, default=None, help="Solver iteration cap.")
    parser.add_argument(
        "--battery-penetration",
        type=float,
        default=None,
        help="%% of non-slack buses to equip with a battery (multi-period only).",
    )
    parser.add_argument("--battery-power-pu", type=float, default=0.006)
    parser.add_argument("--battery-capacity-pu-h", type=float, default=0.015)
    parser.add_argument("--battery-efficiency", type=float, default=0.9)
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="NumPy seed. Battery placement is random, so set this for a "
        "reproducible multi-period battery study.",
    )
    parser.add_argument(
        "--print-solver-output", action="store_true", help="Stream the solver log."
    )
    parser.add_argument("--json", metavar="PATH", default=None, help="Write JSON payload.")
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        default=None,
        help="Confine --json output to this directory.",
    )
    parser.add_argument(
        "--list-solvers",
        action="store_true",
        help="Print solver availability and exit.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_solvers:
        avail = available_solvers()
        print("Pyomo solver availability:")
        for name, ok in avail.items():
            print(f"  {name:22s} {'available' if ok else 'not found'}")
        usable = [k for k, v in avail.items() if v]
        print(f"\nUsable: {', '.join(usable) or 'none'}")
        print("AC (NLP) needs e.g. ipopt; DC (LP/MIP) needs e.g. glpk, cbc, highs.")
        return 0

    if not args.case:
        parser.error("--case is required (or use --list-solvers)")

    try:
        payload = solve_case(
            case=args.case,
            formulation=args.formulation,
            objective=args.objective,
            solver=args.solver,
            profile_index=args.profile_index,
            horizon=args.horizon,
            from_t=args.from_t,
            v_min=args.v_min,
            v_max=args.v_max,
            max_line_loading=args.max_line_loading,
            max_trafo_loading=args.max_trafo_loading,
            allow_curtailment=not args.no_curtailment,
            thermal_limit=args.thermal_limit,
            angle_limits=args.angle_limits,
            time_limit=args.time_limit,
            max_iter=args.max_iter,
            battery_penetration=args.battery_penetration,
            battery_power_pu=args.battery_power_pu,
            battery_capacity_pu_h=args.battery_capacity_pu_h,
            battery_efficiency=args.battery_efficiency,
            seed=args.seed,
            print_solver_output=args.print_solver_output,
        )
    except RuntimeError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 3
    except (FileNotFoundError, ValueError, ImportError) as err:
        print(f"ERROR: {type(err).__name__}: {err}", file=sys.stderr)
        return 2

    print_report(payload)
    if args.json:
        path = args.json
        if args.output_dir:
            os.makedirs(args.output_dir, exist_ok=True)
            path = os.path.join(args.output_dir, os.path.basename(path))
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=json_default)
        print(f"\nStructured payload written to {path}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
