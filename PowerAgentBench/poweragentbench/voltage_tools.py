"""Agent-facing tools for the IEEE 33-bus BESS voltage benchmark."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from poweragentbench.voltage_case import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_SCENARIO_ROOT,
    load_benchmark_config,
    load_scenario_metadata,
    public_scenario_card,
)
from poweragentbench.voltage_evaluator import evaluate_voltage_dispatch


@dataclass
class VoltageToolState:
    attempts: list[dict[str, Any]] = field(default_factory=list)
    preview_calls: int = 0
    final_dispatch: Any = None


class VoltageToolServer:
    """Isolated tool server for one scenario and one experimental condition."""

    def __init__(
        self,
        scenario_id: str,
        *,
        scenario_root: str | Path = DEFAULT_SCENARIO_ROOT,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
        domain_interface: bool = True,
        verification: bool = True,
        recovery: bool = True,
        max_attempts: int | None = None,
        max_previews: int | None = None,
    ) -> None:
        self.scenario_id = scenario_id
        self.scenario_root = Path(scenario_root)
        self.config_path = Path(config_path)
        self.config = load_benchmark_config(self.config_path)
        self.metadata = load_scenario_metadata(scenario_id, self.scenario_root)
        self.domain_interface = bool(domain_interface)
        self.verification = bool(verification)
        self.recovery = bool(recovery)
        self.max_attempts = int(
            max_attempts or self.config["agent"]["max_submission_attempts"]
        )
        self.max_previews = int(
            max_previews or self.config["agent"]["max_preview_calls"]
        )
        self.state = VoltageToolState()

    @property
    def allowed_tools(self) -> list[str]:
        tools = ["case_summary", "inspect_voltage_state", "get_bess_capabilities"]
        if self.verification:
            tools.append("preview_bess_dispatch")
        tools.append("submit")
        return tools

    def execute(
        self, tool: str, args: Mapping[str, Any] | None
    ) -> tuple[dict[str, Any], bool]:
        tool = str(tool).strip().lower()
        args = args or {}
        if tool == "case_summary":
            return {
                "scenario_id": self.scenario_id,
                "network": self.metadata["network"],
                "n_bess": len(self.metadata["bess"]),
                "voltage_limits_pu": self.metadata["voltage_limits_pu"],
                "allowed_tools": self.allowed_tools,
                "submission_attempts_remaining": self.max_attempts
                - len(self.state.attempts),
            }, False
        if tool == "inspect_voltage_state":
            return public_scenario_card(
                self.metadata, domain_specific=self.domain_interface
            ), False
        if tool == "get_bess_capabilities":
            return {
                "bess": self.metadata["bess"],
                "sign_convention": "positive p_mw discharges/injects; negative p_mw charges/withdraws",
            }, False
        if tool == "preview_bess_dispatch":
            if not self.verification:
                return {
                    "error": "preview_bess_dispatch is disabled in this experimental condition"
                }, False
            if self.state.preview_calls >= self.max_previews:
                return {
                    "error": "preview budget exhausted",
                    "max_preview_calls": self.max_previews,
                }, False
            self.state.preview_calls += 1
            report = evaluate_voltage_dispatch(
                self.scenario_id,
                args.get("dispatch"),
                scenario_root=self.scenario_root,
                config_path=self.config_path,
            )
            return {
                "preview": _feedback(report),
                "preview_calls_remaining": self.max_previews - self.state.preview_calls,
            }, False
        if tool == "submit":
            self.state.final_dispatch = args.get("dispatch")
            report = evaluate_voltage_dispatch(
                self.scenario_id,
                args.get("dispatch"),
                scenario_root=self.scenario_root,
                config_path=self.config_path,
            )
            self.state.attempts.append(report)
            success = report.get("success") == 1.0
            exhausted = len(self.state.attempts) >= self.max_attempts
            done = bool(success or not self.recovery or exhausted)
            observation = {
                "accepted": bool(success),
                "verification": _feedback(report),
                "attempt": len(self.state.attempts),
                "submission_attempts_remaining": self.max_attempts
                - len(self.state.attempts),
                "must_replan": bool(not done),
            }
            return observation, done
        return {
            "error": f"unknown tool {tool!r}",
            "allowed_tools": self.allowed_tools,
        }, False


def _feedback(report: Mapping[str, Any]) -> dict[str, Any]:
    if report.get("valid_action") != 1.0:
        return {"success": False, "valid_action": False, "error": report.get("error")}
    state = report.get("final_state") or {}
    return {
        "success": bool(report.get("success")),
        "valid_action": True,
        "converged": bool(report.get("converged")),
        "min_vm_pu": report.get("final_min_vm_pu"),
        "max_vm_pu": report.get("final_max_vm_pu"),
        "remaining_undervoltage_buses": state.get("undervoltage_buses", {}),
        "remaining_overvoltage_buses": state.get("overvoltage_buses", {}),
        "voltage_violation_magnitude": report.get("final_violation_magnitude"),
        "voltage_improvement": report.get("voltage_improvement"),
        "new_thermal_violation": bool(report.get("new_thermal_violation")),
        "error": report.get("error"),
    }
