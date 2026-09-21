#!/usr/bin/env python3
"""Minimal validation of the potpourri skill scripts.

Run:
  python scripts/test_scripts.py

Solver-dependent checks skip cleanly when no compatible solver is installed, so
this is safe to run in a bare environment. Set POTPOURRI_SKILL_FULL_TESTS=1 to
also solve a small multi-period model (slower: a few tens of seconds).
"""

import os
import sys

import pandapower as pp

sys.path.insert(0, os.path.dirname(__file__))

from inspect_case import check_network, inspect_case, load_case  # noqa: E402
from solve_opf import (  # noqa: E402
    available_solvers,
    build_multi_period,
    configure_limits,
    solve_case,
    valid_objectives,
    validate_objective_choice,
)

LV_CASE = "simbench:1-LV-rural1--0-sw"
HIGH_PV_ROW = 20017  # profile row where PV output far exceeds local load


def _tiny_net():
    """Two-bus network with a deliberate bound contradiction."""
    net = pp.create_empty_network()
    b0 = pp.create_bus(net, vn_kv=20.0)
    b1 = pp.create_bus(net, vn_kv=20.0)
    pp.create_ext_grid(net, b0)
    pp.create_line(net, b0, b1, length_km=1.0, std_type="NAYY 4x50 SE")
    pp.create_load(net, b1, p_mw=0.05)
    net.bus["min_vm_pu"] = 1.10
    net.bus["max_vm_pu"] = 1.05
    return net


def _first(names):
    """Return the first available solver from names, or None."""
    avail = available_solvers()
    return next((n for n in names if avail.get(n)), None)


def main() -> int:
    checks = 0
    skipped = []

    # 1 - inspection of a clean case
    payload = inspect_case(LV_CASE, profile_index=HIGH_PV_ROW)
    assert payload["ok"] is True, payload["findings"]["blocking"]
    assert payload["findings"]["blocking"] == []
    assert payload["base_case"]["converged"] is True
    assert payload["findings"]["n_reference_buses"] == 1
    assert payload["meta"]["has_profiles"] is True
    print(
        "OK inspect_case: {} buses, base vm_pu {:.4f}..{:.4f}".format(
            payload["findings"]["counts"]["bus"],
            payload["base_case"]["vm_pu_min"],
            payload["base_case"]["vm_pu_max"],
        )
    )
    checks += 1

    # 2 - the validator must catch a contradictory voltage band
    findings = check_network(_tiny_net())
    assert any("min_vm_pu > max_vm_pu" in f for f in findings["blocking"]), findings
    print("OK check_network flags min_vm_pu > max_vm_pu as blocking")
    checks += 1

    # 3 - objective/formulation compatibility
    assert "voltage_deviation" in valid_objectives("ac", multi_period=False)
    assert "voltage_deviation" not in valid_objectives("dc", multi_period=False)
    assert "poly_cost" not in valid_objectives("ac", multi_period=True)
    for formulation, objective in (("dc", "voltage_deviation"), ("dc", "losses")):
        try:
            validate_objective_choice(objective, formulation, multi_period=False)
        except ValueError:
            pass
        else:  # pragma: no cover - guard against a silent regression
            raise AssertionError(
                f"{objective} on a {formulation} model should be rejected"
            )
    print("OK objective/formulation validation rejects impossible pairings")
    checks += 1

    # 4 - solver probing must never raise, whatever is installed
    avail = available_solvers()
    assert isinstance(avail, dict) and avail
    usable = sorted(k for k, v in avail.items() if v)
    print(f"OK available_solvers: {usable or 'none available'}")
    checks += 1

    # 5 - DC OPF with any LP/MIP solver
    lp = _first(("glpk", "cbc", "highs", "appsi_highs", "gurobi", "cplex"))
    if lp is None:
        skipped.append("DC OPF (no LP/MIP solver)")
    else:
        dc = solve_case(
            case=LV_CASE,
            formulation="dc",
            objective="ext_grid_import",
            solver=lp,
            profile_index=HIGH_PV_ROW,
        )
        assert dc["ok"] is True, dc["solver"]
        assert dc["solver"]["optimal_termination"] is True
        assert dc["results"]["power_balance"]["balanced"] is True
        assert "voltage_note" in dc["results"], "DC must not report a voltage result"
        print(
            "OK DC OPF ({}): objective {:.6g} pu, ext_grid {:+.4f} MW".format(
                lp,
                dc["objective_value"],
                dc["results"]["dispatch"]["ext_grid_p_mw"],
            )
        )
        checks += 1

    # 6 - AC OPF with any NLP solver
    nlp = _first(("ipopt",))
    if nlp is None:
        skipped.append("AC OPF (no NLP solver)")
    else:
        ac = solve_case(
            case=LV_CASE,
            formulation="ac",
            objective="voltage_deviation",
            solver=nlp,
            profile_index=HIGH_PV_ROW,
            allow_curtailment=False,
        )
        assert ac["ok"] is True, ac["solver"]
        assert ac["solver"]["optimal_termination"] is True
        res = ac["results"]
        assert res["power_balance"]["balanced"] is True
        # Reported extrema must agree with the configured band, and the
        # reported values must be the solved ones, not the base case.
        assert 0.5 < res["vm_pu_min"] <= res["vm_pu_max"] < 1.5
        assert res["curtailment"]["curtailed_mw"] < 1e-6, "curtailment was blocked"
        print(
            "OK AC OPF ({}): objective {:.6g}, vm_pu {:.4f}..{:.4f}, "
            "max line {:.2f}%".format(
                nlp,
                ac["objective_value"],
                res["vm_pu_min"],
                res["vm_pu_max"],
                res["max_line_loading_percent"]["value"],
            )
        )
        checks += 1

        # 6b - a genuinely infeasible model must report no results rather than
        # handing back the constructor's base-case power flow. A 1 % branch
        # rating cannot carry the pinned PV export, so no feasible point exists.
        # (Note an unreachable *voltage* band is not a good infeasibility test:
        # with free_slack_vm=True the slack lifts the whole network into it.)
        infeasible = solve_case(
            case=LV_CASE,
            formulation="ac",
            objective="voltage_deviation",
            solver=nlp,
            profile_index=HIGH_PV_ROW,
            allow_curtailment=False,
            max_line_loading=1.0,
            max_trafo_loading=1.0,
        )
        assert infeasible["ok"] is False
        assert infeasible["results"] is None
        assert infeasible["solver"]["optimal_termination"] is False
        assert any(
            row["escalate_to"] == "operations-planning-mitigation"
            for row in infeasible["escalation"]
        ), infeasible["escalation"]
        print(
            "OK infeasible thermal limits report no results "
            f"(termination={infeasible['solver']['termination_condition']})"
        )
        checks += 1

    # 7 - multi-period construction (structure only unless FULL is set)
    net, _ = load_case(LV_CASE)
    configure_limits(net)
    opf, battery = build_multi_period(
        net,
        "ac",
        to_t=HIGH_PV_ROW + 3,
        from_t=HIGH_PV_ROW,
        add_opf_kwargs={},
        battery={"penetration": 30.0},
    )
    assert len(list(opf.model.T)) == 3
    assert float(opf.model.deltaT.value) == 0.25
    assert battery["units"] >= 1
    assert hasattr(opf.model, "BAT_SOC")
    print(
        "OK multi-period build: {} steps x {} h, {} battery unit(s)".format(
            len(list(opf.model.T)), opf.model.deltaT.value, battery["units"]
        )
    )
    checks += 1

    # blocking curtailment is not expressible in a multi-period model
    try:
        solve_case(case=LV_CASE, horizon=3, allow_curtailment=False)
    except ValueError as err:
        assert "multi-period" in str(err)
        print("OK multi-period refuses allow_curtailment=False with an explanation")
        checks += 1
    else:  # pragma: no cover
        raise AssertionError("multi-period should refuse allow_curtailment=False")

    if os.environ.get("POTPOURRI_SKILL_FULL_TESTS") == "1" and _first(("ipopt",)):
        mp = solve_case(
            case=LV_CASE,
            formulation="ac",
            objective="voltage_deviation",
            horizon=3,
            from_t=HIGH_PV_ROW,
            battery_penetration=30.0,
            seed=0,
        )
        assert mp["ok"] is True, mp["solver"]
        assert mp["results"]["n_steps"] == 3
        assert mp["results"]["battery"] is not None
        assert len(mp["results"]["per_step"]) == 3
        print(
            "OK multi-period solve: objective {:.6g}, worst vm_pu {:.4f}".format(
                mp["objective_value"], mp["results"]["vm_pu_min"]
            )
        )
        checks += 1
    else:
        skipped.append("multi-period solve (set POTPOURRI_SKILL_FULL_TESTS=1)")

    print(f"\n{checks} check(s) passed.")
    for item in skipped:
        print(f"skipped: {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
