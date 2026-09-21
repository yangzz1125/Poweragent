"""Independent, replay-based evaluator for BESS active-power voltage correction."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from poweragentbench.voltage_case import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_SCENARIO_ROOT,
    load_benchmark_config,
    load_scenario_metadata,
    load_scenario_network,
    sha256_file,
)


def normalize_dispatch(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, Mapping):
        if "dispatch" in raw:
            raw = raw["dispatch"]
        elif "bess_id" in raw and "p_mw" in raw:
            raw = [raw]
        else:
            raw = [{"bess_id": key, "p_mw": value} for key, value in raw.items()]
    if raw is None:
        return []
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise ValueError(  # noqa: TRY004 - evaluator reports all invalid submissions uniformly
            "dispatch must be a list of {bess_id, p_mw} objects"
        )
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError(  # noqa: TRY004 - evaluator reports all invalid submissions uniformly
                "each dispatch entry must be an object"
            )
        bess_id = item.get("bess_id")
        p_mw = item.get("p_mw")
        if not isinstance(bess_id, str) or not bess_id:
            raise ValueError("each dispatch entry requires a non-empty bess_id")
        if (
            isinstance(p_mw, bool)
            or not isinstance(p_mw, (int, float))
            or not math.isfinite(float(p_mw))
        ):
            raise ValueError(f"BESS {bess_id} p_mw must be a finite number")
        result.append({"bess_id": bess_id, "p_mw": float(p_mw)})
    return result


def validate_dispatch(raw: Any, metadata: Mapping[str, Any]) -> list[dict[str, Any]]:
    entries = normalize_dispatch(raw)
    specs = {str(spec["bess_id"]): spec for spec in metadata["bess"]}
    seen: set[str] = set()
    validated: list[dict[str, Any]] = []
    for entry in entries:
        bess_id = entry["bess_id"]
        if bess_id in seen:
            raise ValueError(f"duplicate dispatch for {bess_id}")
        seen.add(bess_id)
        if bess_id not in specs:
            raise ValueError(f"unknown BESS {bess_id!r}")
        spec = specs[bess_id]
        value = float(entry["p_mw"])
        lower, upper = float(spec["p_min_mw"]), float(spec["p_max_mw"])
        step = float(spec["step_mw"])
        if value < lower - 1e-9 or value > upper + 1e-9:
            raise ValueError(f"BESS {bess_id} p_mw={value} outside [{lower}, {upper}]")
        if not math.isclose(
            value / step, round(value / step), abs_tol=1e-9, rel_tol=0.0
        ):
            raise ValueError(
                f"BESS {bess_id} p_mw={value} is not aligned to step {step}"
            )
        validated.append({"bess_id": bess_id, "p_mw": value})
    return validated


def apply_bess_dispatch(
    net: Any, dispatch: Sequence[Mapping[str, Any]], metadata: Mapping[str, Any]
) -> None:
    values = {str(item["bess_id"]): float(item["p_mw"]) for item in dispatch}
    for spec in metadata["bess"]:
        bess_id = str(spec["bess_id"])
        matches = net.storage.index[net.storage["name"].astype(str) == bess_id].tolist()
        if len(matches) != 1:
            raise ValueError(
                f"scenario must contain exactly one storage element named {bess_id}"
            )
        # Benchmark: positive=discharge/injection. pandapower: positive=charging/load.
        net.storage.at[matches[0], "p_mw"] = -float(values.get(bess_id, 0.0))


def run_locked_power_flow(
    net: Any, solver: Mapping[str, Any]
) -> tuple[bool, str | None]:
    import pandapower as pp

    try:
        pp.runpp(
            net,
            algorithm=str(solver["algorithm"]),
            calculate_voltage_angles=bool(solver["calculate_voltage_angles"]),
            init=str(solver["init"]),
            max_iteration=int(solver["max_iteration"]),
            tolerance_mva=float(solver["tolerance_mva"]),
        )
        return bool(
            net.converged
        ), None if net.converged else "power flow did not converge"
    except Exception as exc:  # noqa: BLE001 - solver failures are scored, not process-fatal
        return False, str(exc)


def state_metrics(
    net: Any, metadata: Mapping[str, Any], *, converged: bool, error: str | None = None
) -> dict[str, Any]:
    limits = metadata["voltage_limits_pu"]
    v_min, v_max = float(limits["min"]), float(limits["max"])
    if not converged:
        return {
            "converged": False,
            "error": error,
            "min_vm_pu": None,
            "max_vm_pu": None,
            "undervoltage_buses": [],
            "overvoltage_buses": [],
            "voltage_violation_count": 0,
            "voltage_violation_magnitude": None,
            "max_line_loading_percent": None,
            "overloaded_lines": [],
        }
    voltages = net.res_bus.vm_pu.astype(float)
    undervoltage = voltages[voltages < v_min].sort_values()
    overvoltage = voltages[voltages > v_max].sort_values(ascending=False)
    loading_limit = float(metadata.get("line_loading_percent_max", 100.0))
    line_loading = net.res_line.loading_percent.astype(float)
    overloaded = line_loading[line_loading > loading_limit].sort_values(ascending=False)
    magnitude = float(
        (v_min - voltages).clip(lower=0.0).sum()
        + (voltages - v_max).clip(lower=0.0).sum()
    )
    return {
        "converged": True,
        "error": None,
        "min_vm_pu": float(voltages.min()),
        "min_vm_bus": int(voltages.idxmin()),
        "max_vm_pu": float(voltages.max()),
        "max_vm_bus": int(voltages.idxmax()),
        "bus_voltages_pu": {
            str(int(bus)): float(value) for bus, value in voltages.items()
        },
        "undervoltage_buses": {
            str(int(bus)): float(value) for bus, value in undervoltage.items()
        },
        "overvoltage_buses": {
            str(int(bus)): float(value) for bus, value in overvoltage.items()
        },
        "voltage_violation_count": int(len(undervoltage) + len(overvoltage)),
        "voltage_violation_magnitude": magnitude,
        "max_line_loading_percent": float(line_loading.max())
        if len(line_loading)
        else 0.0,
        "overloaded_lines": {
            str(int(idx)): float(value) for idx, value in overloaded.items()
        },
    }


def evaluate_voltage_dispatch(
    scenario_id: str,
    dispatch: Any,
    *,
    scenario_root: str | Path = DEFAULT_SCENARIO_ROOT,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
    verify_hashes: bool = True,
) -> dict[str, Any]:
    """Reload a frozen case and independently replay a submitted dispatch."""
    config = load_benchmark_config(config_path)
    metadata = load_scenario_metadata(
        scenario_id, scenario_root, verify_hashes=verify_hashes
    )
    expected_config_hash = metadata.get("benchmark_config_sha256")
    if expected_config_hash and expected_config_hash != sha256_file(config_path):
        raise ValueError("benchmark config hash differs from frozen scenario manifest")
    try:
        validated = validate_dispatch(dispatch, metadata)
    except ValueError as exc:
        return {
            "scenario_id": scenario_id,
            "success": 0.0,
            "valid_action": 0.0,
            "error": str(exc),
            "submitted_dispatch": [],
            "artifact_hash": metadata["artifact_hash"],
        }
    net = load_scenario_network(scenario_id, scenario_root, verify_hashes=verify_hashes)
    apply_bess_dispatch(net, validated, metadata)
    converged, error = run_locked_power_flow(net, config["solver"])
    final = state_metrics(net, metadata, converged=converged, error=error)
    initial = metadata["initial_state"]
    success = bool(converged and final["voltage_violation_count"] == 0)
    before = float(initial["voltage_violation_magnitude"])
    after = final["voltage_violation_magnitude"]
    improvement = 0.0 if after is None else before - float(after)
    action_l1 = sum(abs(float(item["p_mw"])) for item in validated)
    return {
        "scenario_id": scenario_id,
        "success": float(success),
        "valid_action": 1.0,
        "converged": float(converged),
        "initial_violation_count": float(initial["voltage_violation_count"]),
        "final_violation_count": float(final["voltage_violation_count"]),
        "initial_min_vm_pu": float(initial["min_vm_pu"]),
        "final_min_vm_pu": final["min_vm_pu"],
        "initial_max_vm_pu": float(initial["max_vm_pu"]),
        "final_max_vm_pu": final["max_vm_pu"],
        "initial_violation_magnitude": before,
        "final_violation_magnitude": after,
        "voltage_improvement": improvement,
        "new_thermal_violation": float(bool(final["overloaded_lines"])),
        "max_line_loading_percent": final["max_line_loading_percent"],
        "action_l1_mw": float(action_l1),
        "action_cost": float(action_l1),
        "submitted_dispatch": validated,
        "final_state": final,
        "error": error,
        "artifact_hash": metadata["artifact_hash"],
        "dataset_version": metadata["dataset_version"],
        "pandapower_version": __import__("pandapower").__version__,
        "solver": config["solver"],
    }
