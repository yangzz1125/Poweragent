from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("MPLCONFIGDIR", str(REPO_ROOT / ".mplconfig"))

import pypsa

TASK_ID = "steady_level_1_case39_easy"
NETWORK_FILE = REPO_ROOT / "cases" / "case39" / "pypsa" / "case39.nc"
ACTIONSPACE_FILE = REPO_ROOT / "benchmarks" / "steady" / "level_1" / "actionspace.json"
ACTIONCOST_FILE = REPO_ROOT / "benchmarks" / "steady" / "level_1" / "actioncost.json"
BASELINE_SUMMARY_FILE = REPO_ROOT / "benchmarks" / "steady" / "level_1" / "baseline_summary.json"

SCENARIO_LOAD_IDS = ["L10", "L11", "L12", "L14", "L15", "L16", "L17", "L18", "L20"]
SCENARIO_LOAD_SCALE = 1.25
SCENARIO_GENERATOR_DELTAS_MW = {
    "G7": -20.0,
    "G8": -100.0,
    "G9": -180.0,
    "G1": 150.0,
    "G2": 150.0,
}
SCENARIO_VM_TARGET_SHIFT_PU = {
    "G6": -0.01,
    "G7": -0.01,
    "G8": -0.01,
    "G9": -0.01,
}


for logger_name in (
    "matplotlib",
    "pandapower",
    "pypsa",
    "pypsa.network.io",
    "pypsa.network.power_flow",
    "pypsa.network.transform",
):
    logging.getLogger(logger_name).setLevel(logging.ERROR)


def build_pypsa_case39() -> pypsa.Network:
    """Build the IEEE 39-bus system in PyPSA from pandapower's case39 source."""
    import pandapower as pp
    import pandapower.networks as pn
    from pandapower.converter.pypower import to_ppc

    pp_net = pn.case39()
    pp.runpp(pp_net)
    ppc = to_ppc(pp_net)
    network = pypsa.Network()
    network.import_from_pypower_ppc(ppc)
    network.name = "IEEE 39-bus Level 1 Easy Scenario"
    return network


def apply_scenario_modifications(network: pypsa.Network) -> pypsa.Network:
    """Apply the stressed dispatch and load pattern for the benchmark."""
    for load_id in SCENARIO_LOAD_IDS:
        network.loads.at[load_id, "p_set"] *= SCENARIO_LOAD_SCALE
        network.loads.at[load_id, "q_set"] *= SCENARIO_LOAD_SCALE

    for generator_id, delta_mw in SCENARIO_GENERATOR_DELTAS_MW.items():
        network.generators.at[generator_id, "p_set"] += delta_mw

    for generator_id, delta_pu in SCENARIO_VM_TARGET_SHIFT_PU.items():
        bus_id = network.generators.at[generator_id, "bus"]
        network.buses.at[bus_id, "v_mag_pu_set"] += delta_pu

    return network


def build_scenario_network() -> pypsa.Network:
    network = build_pypsa_case39()
    return apply_scenario_modifications(network)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def export_scenario_network(path: Path = NETWORK_FILE) -> Path:
    network = build_scenario_network()
    network.export_to_netcdf(path)
    return path


def load_actionspace(path: Path = ACTIONSPACE_FILE) -> dict[str, Any]:
    payload = load_json(path)
    payload["action_index"] = {action["id"]: action for action in payload["actions"]}
    return payload


def load_actioncost(path: Path = ACTIONCOST_FILE) -> dict[str, Any]:
    payload = load_json(path)
    payload["action_index"] = {action["id"]: action for action in payload["actions"]}
    return payload


def load_solution(path: Path) -> dict[str, float]:
    payload = load_json(path)
    values: dict[str, float] = {}

    if "actions" not in payload or not isinstance(payload["actions"], list):
        raise ValueError("Solution JSON must contain an 'actions' list.")

    for item in payload["actions"]:
        if not isinstance(item, dict):
            raise ValueError("Each action entry must be a JSON object.")
        action_id = item.get("id")
        value = item.get("value")
        if not isinstance(action_id, str):
            raise ValueError("Each action entry must include a string 'id'.")
        if not isinstance(value, (int, float)):
            raise ValueError(f"Action '{action_id}' must include a numeric 'value'.")
        if action_id in values:
            raise ValueError(f"Duplicate action '{action_id}' in solution file.")
        values[action_id] = float(value)

    return values


def _assert_step(value: float, min_value: float, step: float, action_id: str) -> None:
    steps = (value - min_value) / step
    if not math.isclose(steps, round(steps), rel_tol=0.0, abs_tol=1e-9):
        raise ValueError(
            f"Action '{action_id}' value {value} does not align with step size {step}."
        )


def validate_action_values(
    action_values: dict[str, float], actionspace: dict[str, Any]
) -> dict[str, float]:
    validated = {action_id: 0.0 for action_id in actionspace["action_index"]}

    for action_id, value in action_values.items():
        if action_id not in actionspace["action_index"]:
            raise ValueError(f"Unknown action '{action_id}'.")
        action = actionspace["action_index"][action_id]
        min_value = float(action["min_value"])
        max_value = float(action["max_value"])
        step = float(action["step"])
        if value < min_value - 1e-9 or value > max_value + 1e-9:
            raise ValueError(
                f"Action '{action_id}' value {value} outside [{min_value}, {max_value}]."
            )
        _assert_step(value, min_value, step, action_id)
        validated[action_id] = value

    return validated


def _add_switchable_shunt(network: pypsa.Network, action: dict[str, Any], value: float) -> None:
    if value <= 0.0:
        return
    bus_id = action["bus"]
    v_nom_kv = float(network.buses.at[bus_id, "v_nom"])
    susceptance_si = value / (v_nom_kv**2)
    network.add(
        "ShuntImpedance",
        f"{action['id']}_instance",
        bus=bus_id,
        b=susceptance_si,
    )


def apply_actions(
    network: pypsa.Network, action_values: dict[str, float], actionspace: dict[str, Any]
) -> pypsa.Network:
    for action_id, value in action_values.items():
        if math.isclose(value, 0.0, rel_tol=0.0, abs_tol=1e-12):
            continue

        action = actionspace["action_index"][action_id]
        action_type = action["type"]

        if action_type == "generator_active_power_delta_mw":
            network.generators.at[action["component_id"], "p_set"] += value
        elif action_type == "coordinated_bus_voltage_setpoint_delta_pu":
            for target in action["targets"]:
                network.buses.at[target["bus"], "v_mag_pu_set"] += value
        elif action_type == "transformer_tap_step":
            delta_ratio = float(action["tap_ratio_per_step"]) * value
            network.transformers.at[action["component_id"], "tap_ratio"] += delta_ratio
        elif action_type == "switchable_shunt_mvar":
            _add_switchable_shunt(network, action, value)
        elif action_type == "load_shed_percent":
            scale = 1.0 - value / 100.0
            load_id = action["component_id"]
            network.loads.at[load_id, "p_set"] *= scale
            network.loads.at[load_id, "q_set"] *= scale
        elif action_type == "transformer_phase_shift_delta_deg":
            network.transformers.at[action["component_id"], "phase_shift"] += value
        else:
            raise ValueError(f"Unsupported action type '{action_type}'.")

    return network


def load_or_build_scenario(network_path: Path = NETWORK_FILE) -> pypsa.Network:
    if network_path.exists():
        return pypsa.Network(network_path)
    return build_scenario_network()


def _safe_pf(network: pypsa.Network) -> tuple[bool, dict[str, Any]]:
    try:
        result = network.pf(use_seed=True)
    except Exception as exc:  # pragma: no cover - defensive wrapper
        return False, {"error": str(exc)}

    converged = bool(result["converged"].iloc[0, 0])
    if not converged:
        return False, {"error": "Power flow did not converge."}
    return True, {}


def _line_loading_pct(network: pypsa.Network) -> Any:
    line_s = (network.lines_t.p0.iloc[0] ** 2 + network.lines_t.q0.iloc[0] ** 2) ** 0.5
    return 100.0 * line_s / network.lines.s_nom


def _voltage_series(network: pypsa.Network) -> Any:
    return network.buses_t.v_mag_pu.iloc[0]


def compute_violation_score(
    line_loading_pct: Any,
    voltages_pu: Any,
    line_limit_pct: float,
    v_min_pu: float,
    v_max_pu: float,
) -> float:
    line_over = ((line_loading_pct - line_limit_pct).clip(lower=0.0) / 100.0).sum()
    low_voltage = (v_min_pu - voltages_pu).clip(lower=0.0).sum()
    high_voltage = (voltages_pu - v_max_pu).clip(lower=0.0).sum()
    return float(line_over + 10.0 * low_voltage + 10.0 * high_voltage)


def summarize_operating_state(
    network: pypsa.Network,
    line_limit_pct: float,
    v_min_pu: float,
    v_max_pu: float,
) -> dict[str, Any]:
    converged, extra = _safe_pf(network)
    summary: dict[str, Any] = {"converged": converged}
    summary.update(extra)

    if not converged:
        summary["violation_score"] = 100.0
        summary["max_line_loading_pct"] = None
        summary["worst_line"] = None
        summary["min_voltage_pu"] = None
        summary["min_voltage_bus"] = None
        summary["max_voltage_pu"] = None
        summary["max_voltage_bus"] = None
        summary["overloaded_lines"] = []
        summary["low_voltage_buses"] = []
        summary["high_voltage_buses"] = []
        return summary

    line_loading_pct = _line_loading_pct(network)
    voltages_pu = _voltage_series(network)

    overloaded_lines = (
        line_loading_pct[line_loading_pct > line_limit_pct]
        .sort_values(ascending=False)
        .round(4)
        .to_dict()
    )
    low_voltage_buses = (
        voltages_pu[voltages_pu < v_min_pu].sort_values().round(6).to_dict()
    )
    high_voltage_buses = (
        voltages_pu[voltages_pu > v_max_pu]
        .sort_values(ascending=False)
        .round(6)
        .to_dict()
    )

    summary["violation_score"] = compute_violation_score(
        line_loading_pct, voltages_pu, line_limit_pct, v_min_pu, v_max_pu
    )
    summary["max_line_loading_pct"] = float(line_loading_pct.max())
    summary["worst_line"] = str(line_loading_pct.sort_values(ascending=False).index[0])
    summary["min_voltage_pu"] = float(voltages_pu.min())
    summary["min_voltage_bus"] = str(voltages_pu.sort_values().index[0])
    summary["max_voltage_pu"] = float(voltages_pu.max())
    summary["max_voltage_bus"] = str(voltages_pu.sort_values(ascending=False).index[0])
    summary["overloaded_lines"] = overloaded_lines
    summary["low_voltage_buses"] = low_voltage_buses
    summary["high_voltage_buses"] = high_voltage_buses
    return summary


def evaluate_solution(
    action_values: dict[str, float],
    network_path: Path = NETWORK_FILE,
    actionspace_path: Path = ACTIONSPACE_FILE,
    actioncost_path: Path = ACTIONCOST_FILE,
) -> dict[str, Any]:
    actionspace = load_actionspace(actionspace_path)
    actioncost = load_actioncost(actioncost_path)
    validated_actions = validate_action_values(action_values, actionspace)

    network = load_or_build_scenario(network_path)
    apply_actions(network, validated_actions, actionspace)

    base_limits = actionspace["operating_limits"]["base_case"]
    contingency_limits = actionspace["operating_limits"]["contingency"]

    base_summary = summarize_operating_state(
        network,
        base_limits["line_loading_pct_max"],
        base_limits["bus_voltage_pu_min"],
        base_limits["bus_voltage_pu_max"],
    )

    contingency_summaries: dict[str, Any] = {}
    contingency_violation_total = 0.0
    for contingency in actionspace["contingencies"]:
        contingency_network = load_or_build_scenario(network_path)
        apply_actions(contingency_network, validated_actions, actionspace)
        contingency_network.lines.at[contingency["component_id"], "active"] = False
        summary = summarize_operating_state(
            contingency_network,
            contingency_limits["line_loading_pct_max"],
            contingency_limits["bus_voltage_pu_min"],
            contingency_limits["bus_voltage_pu_max"],
        )
        contingency_summaries[contingency["id"]] = summary
        contingency_violation_total += float(summary["violation_score"])

    action_cost = compute_action_cost(validated_actions, actionspace, actioncost)
    remaining_violation_score = float(base_summary["violation_score"]) + contingency_violation_total

    return {
        "task_id": TASK_ID,
        "base_case": base_summary,
        "contingencies": contingency_summaries,
        "remaining_violation_score": remaining_violation_score,
        "action_cost": action_cost,
        "composite_score": 10000.0 * remaining_violation_score + action_cost,
        "feasible": math.isclose(remaining_violation_score, 0.0, abs_tol=1e-12),
        "applied_actions": {
            action_id: value
            for action_id, value in validated_actions.items()
            if not math.isclose(value, 0.0, abs_tol=1e-12)
        },
        "ranking_rule": "Primary: lower remaining_violation_score. Secondary: lower action_cost.",
    }


def compute_action_cost(
    action_values: dict[str, float],
    actionspace: dict[str, Any],
    actioncost: dict[str, Any],
) -> float:
    total_cost = 0.0
    for action_id, value in action_values.items():
        if math.isclose(value, 0.0, abs_tol=1e-12):
            continue
        action = actionspace["action_index"][action_id]
        cost = actioncost["action_index"][action_id]
        step = float(action["step"])
        steps = round(abs(value) / step)
        total_cost += float(cost["cost_per_step"]) * abs(steps)
    return total_cost


def write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=False)
        fh.write("\n")


def generate_baseline_summary(
    network_path: Path = NETWORK_FILE,
    actionspace_path: Path = ACTIONSPACE_FILE,
    actioncost_path: Path = ACTIONCOST_FILE,
    output_path: Path = BASELINE_SUMMARY_FILE,
) -> dict[str, Any]:
    summary = evaluate_solution({}, network_path, actionspace_path, actioncost_path)
    write_json(output_path, summary)
    return summary
