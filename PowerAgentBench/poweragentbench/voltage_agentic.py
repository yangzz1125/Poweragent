"""Scripted and LLM agents for BESS active-power voltage correction."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from poweragentbench.llm_agent_adapter import load_prompt_template, parse_json_command
from poweragentbench.voltage_case import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_SCENARIO_ROOT,
    load_scenario_metadata,
)
from poweragentbench.voltage_evaluator import evaluate_voltage_dispatch
from poweragentbench.voltage_tools import VoltageToolServer

Message = dict[str, str]
LLMCallable = Callable[[list[Message]], str]


@dataclass
class VoltageAgentOutput:
    name: str
    dispatch: Any
    attempts: list[dict[str, Any]] = field(default_factory=list)
    tool_log: list[dict[str, Any]] = field(default_factory=list)
    raw_responses: list[str] = field(default_factory=list)
    invalid_tool_calls: float = 0.0
    submitted_explicitly: float = 1.0
    auto_finalized: float = 0.0
    preview_calls: float = 0.0
    power_flow_calls: float = 0.0


class LLMVoltageAgent:
    def __init__(
        self,
        llm: LLMCallable,
        *,
        name: str,
        system_prompt: str | None = None,
        max_turns: int = 12,
        domain_interface: bool = True,
        verification: bool = True,
        recovery: bool = True,
        scenario_root: str | Path = DEFAULT_SCENARIO_ROOT,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
    ) -> None:
        self.llm = llm
        self.name = name
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self.max_turns = int(max_turns)
        self.domain_interface = bool(domain_interface)
        self.verification = bool(verification)
        self.recovery = bool(recovery)
        self.scenario_root = Path(scenario_root)
        self.config_path = Path(config_path)

    def run(self, scenario_id: str) -> VoltageAgentOutput:
        server = VoltageToolServer(
            scenario_id,
            scenario_root=self.scenario_root,
            config_path=self.config_path,
            domain_interface=self.domain_interface,
            verification=self.verification,
            recovery=self.recovery,
        )
        messages = self._initial_messages(server)
        tool_log: list[dict[str, Any]] = []
        responses: list[str] = []
        invalid = 0
        submitted = 0.0
        for _ in range(self.max_turns):
            response = self.llm(messages) or ""
            responses.append(response)
            messages.append({"role": "assistant", "content": response})
            try:
                command = parse_json_command(response)
                tool = str(command.get("tool", ""))
                args = command.get("args", {}) or {}
                observation, done = server.execute(tool, args)
                if "error" in observation:
                    invalid += 1
                if tool.strip().lower() == "submit":
                    submitted = 1.0
                tool_log.append(
                    {"tool": tool, "args": args, "observation": observation}
                )
                messages.append(
                    {
                        "role": "user",
                        "content": json.dumps({"observation": observation}),
                    }
                )
                if done:
                    break
            except Exception as exc:  # noqa: BLE001 - tool/adapter faults are recoverable observations
                invalid += 1
                observation = {
                    "error": str(exc),
                    "instruction": "Return exactly one JSON command with fields 'tool' and 'args'.",
                }
                tool_log.append({"tool": "parse_error", "observation": observation})
                messages.append(
                    {
                        "role": "user",
                        "content": json.dumps({"observation": observation}),
                    }
                )
        dispatch = (
            server.state.final_dispatch
            if server.state.final_dispatch is not None
            else []
        )
        auto = 0.0
        if not submitted:
            auto = 1.0
        return VoltageAgentOutput(
            name=self.name,
            dispatch=dispatch,
            attempts=server.state.attempts,
            tool_log=tool_log,
            raw_responses=responses,
            invalid_tool_calls=float(invalid),
            submitted_explicitly=submitted,
            auto_finalized=auto,
            preview_calls=float(server.state.preview_calls),
            power_flow_calls=float(
                len(server.state.attempts) + server.state.preview_calls
            ),
        )

    def _initial_messages(self, server: VoltageToolServer) -> list[Message]:
        task = {
            "task": "correct IEEE 33-bus voltage violations using BESS active power only",
            "scenario_id": server.scenario_id,
            "experimental_condition": {
                "domain_specific_interface": self.domain_interface,
                "verification": self.verification,
                "recovery": self.recovery,
            },
            "allowed_tools": server.allowed_tools,
            "command_schema": {"tool": "<tool_name>", "args": {}},
            "submit_example": {
                "tool": "submit",
                "args": {"dispatch": [{"bess_id": "BESS_1", "p_mw": 0.25}]},
            },
        }
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": json.dumps(task)},
        ]


class NoActionVoltageAgent:
    name = "No-action"

    def run(self, scenario_id: str) -> VoltageAgentOutput:
        return VoltageAgentOutput(name=self.name, dispatch=[])


class NearestBESSGreedyAgent:
    name = "Nearest-BESS-greedy"

    def __init__(
        self,
        max_steps: int = 40,
        *,
        scenario_root: str | Path = DEFAULT_SCENARIO_ROOT,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
    ) -> None:
        self.max_steps = int(max_steps)
        self.scenario_root = Path(scenario_root)
        self.config_path = Path(config_path)

    def run(self, scenario_id: str) -> VoltageAgentOutput:
        metadata = load_scenario_metadata(scenario_id, self.scenario_root)
        condition = metadata["initial_state"]["condition"]
        target_buses = metadata["initial_state"][
            "undervoltage_buses" if condition == "UNDERVOLTAGE" else "overvoltage_buses"
        ]
        worst_bus = int(next(iter(target_buses)))
        specs = sorted(
            metadata["bess"], key=lambda spec: abs(int(spec["bus"]) - worst_bus)
        )
        values = {spec["bess_id"]: 0.0 for spec in specs}
        sign = 1.0 if condition == "UNDERVOLTAGE" else -1.0
        power_flow_calls = 0
        for step_index in range(self.max_steps):
            report = evaluate_voltage_dispatch(
                scenario_id,
                _dispatch(values),
                scenario_root=self.scenario_root,
                config_path=self.config_path,
            )
            power_flow_calls += 1
            if report["success"] == 1.0:
                break
            spec = specs[step_index % len(specs)]
            candidate = values[spec["bess_id"]] + sign * float(spec["step_mw"])
            values[spec["bess_id"]] = min(
                float(spec["p_max_mw"]), max(float(spec["p_min_mw"]), candidate)
            )
        return VoltageAgentOutput(
            name=self.name,
            dispatch=_dispatch(values),
            power_flow_calls=float(power_flow_calls),
        )


class VoltageSensitivityGreedyAgent:
    name = "Voltage-sensitivity-greedy"

    def __init__(
        self,
        max_steps: int = 40,
        *,
        scenario_root: str | Path = DEFAULT_SCENARIO_ROOT,
        config_path: str | Path = DEFAULT_CONFIG_PATH,
    ) -> None:
        self.max_steps = int(max_steps)
        self.scenario_root = Path(scenario_root)
        self.config_path = Path(config_path)

    def run(self, scenario_id: str) -> VoltageAgentOutput:
        metadata = load_scenario_metadata(scenario_id, self.scenario_root)
        specs = list(metadata["bess"])
        values = {spec["bess_id"]: 0.0 for spec in specs}
        power_flow_calls = 0
        for _ in range(self.max_steps):
            current = evaluate_voltage_dispatch(
                scenario_id,
                _dispatch(values),
                scenario_root=self.scenario_root,
                config_path=self.config_path,
            )
            power_flow_calls += 1
            if current["success"] == 1.0:
                break
            current_mag = current.get("final_violation_magnitude")
            best: tuple[float, str, float] | None = None
            for spec in specs:
                bess_id = str(spec["bess_id"])
                for direction in (-1.0, 1.0):
                    candidate_value = values[bess_id] + direction * float(
                        spec["step_mw"]
                    )
                    if (
                        candidate_value < float(spec["p_min_mw"]) - 1e-9
                        or candidate_value > float(spec["p_max_mw"]) + 1e-9
                    ):
                        continue
                    trial = dict(values)
                    trial[bess_id] = candidate_value
                    report = evaluate_voltage_dispatch(
                        scenario_id,
                        _dispatch(trial),
                        scenario_root=self.scenario_root,
                        config_path=self.config_path,
                    )
                    power_flow_calls += 1
                    magnitude = report.get("final_violation_magnitude")
                    if (
                        report.get("valid_action") != 1.0
                        or magnitude is None
                        or report.get("new_thermal_violation") == 1.0
                    ):
                        continue
                    score = float(
                        current_mag if current_mag is not None else np.inf
                    ) - float(magnitude)
                    if report["success"] == 1.0:
                        score += 1000.0
                    if best is None or score > best[0]:
                        best = (score, bess_id, candidate_value)
            if best is None or best[0] <= 1e-12:
                break
            values[best[1]] = best[2]
        return VoltageAgentOutput(
            name=self.name,
            dispatch=_dispatch(values),
            power_flow_calls=float(power_flow_calls),
        )


def score_voltage_output(
    scenario_id: str,
    output: VoltageAgentOutput,
    *,
    scenario_root: str | Path = DEFAULT_SCENARIO_ROOT,
    config_path: str | Path = DEFAULT_CONFIG_PATH,
) -> dict[str, Any]:
    report = evaluate_voltage_dispatch(
        scenario_id,
        output.dispatch,
        scenario_root=scenario_root,
        config_path=config_path,
    )
    report.update(
        {
            "agent": output.name,
            "n_attempts": float(len(output.attempts)),
            "n_recovery_steps": float(max(0, len(output.attempts) - 1)),
            "preview_calls": float(output.preview_calls),
            "n_power_flows": float(1 + output.power_flow_calls),
            "invalid_tool_calls": float(output.invalid_tool_calls),
            "submitted_explicitly": float(output.submitted_explicitly),
            "auto_finalized": float(output.auto_finalized),
        }
    )
    return report


def aggregate_voltage_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    summary: dict[str, Any] = {"agent": rows[0]["agent"], "cases": len(rows)}
    excluded = {
        "scenario_id",
        "agent",
        "artifact_hash",
        "repetition_index",
    }
    keys = list(dict.fromkeys(key for row in rows for key in row))
    for key in keys:
        value = next((row[key] for row in rows if key in row), None)
        if (
            key in excluded
            or isinstance(value, bool)
            or not isinstance(value, (int, float))
        ):
            continue
        values = [
            float(row[key])
            for row in rows
            if isinstance(row.get(key), (int, float))
            and not isinstance(row.get(key), bool)
        ]
        if values:
            summary[f"{key}_mean"] = float(np.mean(values))
            summary[f"{key}_std"] = float(np.std(values))
    return summary


def _dispatch(values: Mapping[str, float]) -> list[dict[str, Any]]:
    return [
        {"bess_id": key, "p_mw": float(value)} for key, value in sorted(values.items())
    ]


DEFAULT_SYSTEM_PROMPT = """You are an engineering agent correcting steady-state voltage violations on an IEEE 33-bus distribution feeder.
Return exactly one JSON command per turn and no prose: {"tool":"<tool_name>","args":{...}}.
Use only the declared BESS active-power controls. Positive benchmark p_mw means discharge/injection and negative p_mw means charging/withdrawal. Respect every BESS bound and step size.
Inspect the state and capabilities before acting. If preview_bess_dispatch is available, use it to verify a candidate. Finish with submit. If submit returns must_replan=true, use its independent power-flow feedback and submit a corrected dispatch."""


def load_voltage_prompt(path: str | Path | None) -> str | None:
    return load_prompt_template(path)
