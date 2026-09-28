"""Scripted and LLM agents for BESS active-power voltage correction."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from poweragentbench.llm_agent_adapter import load_prompt_template, parse_json_command
from poweragentbench.openai_client import OpenAIResponsesClient
from poweragentbench.voltage_case import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_SCENARIO_ROOT,
    load_scenario_metadata,
)
from poweragentbench.voltage_evaluator import evaluate_voltage_dispatch
from poweragentbench.voltage_tools import VoltageToolServer, VoltageToolState
from poweragentbench.voltage_costs import BudgetStop, Campaign, atomic_json, read_events

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
    n_llm_turns: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    usage_unavailable: bool = False
    api_retries: int = 0
    latency_seconds: float = 0.0
    n_preview_requests: int = 0
    n_submit_calls: int = 0
    n_evaluator_calls: int = 0
    n_actual_power_flows: int = 0
    termination_reason: str = "unknown"
    paused: bool = False


class LLMVoltageAgent:
    def __init__(
        self,
        llm: LLMCallable,
        *,
        name: str,
        system_prompt: str | None = None,
        max_turns: int = 12,
        checkpoint_path: Path | None = None,
        event_sink: Callable[[dict], None] | None = None,
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
        self.checkpoint_path = checkpoint_path
        self.event_sink = event_sink
        self.domain_interface = bool(domain_interface)
        self.verification = bool(verification)
        self.recovery = bool(recovery)
        self.scenario_root = Path(scenario_root)
        self.config_path = Path(config_path)

    def run(self, scenario_id: str) -> VoltageAgentOutput:
        started = time.monotonic()
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
        usages: list[dict[str, Any] | None] = []
        retries = 0
        completed_turns = 0
        elapsed = 0.0
        termination = "turn_limit"
        paused = False
        hook = getattr(self.llm, "request_hook", None)
        if self.checkpoint_path and self.checkpoint_path.exists():
            saved = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            if saved["scenario_id"] != scenario_id:
                raise ValueError("checkpoint scenario mismatch")
            server.state = VoltageToolState(**saved["state"])
            messages, responses, tool_log = saved["messages"], saved["responses"], saved["tool_log"]
            usages, retries = saved["usages"], saved["retries"]
            invalid, submitted = saved["invalid"], saved["submitted"]
            completed_turns, elapsed = saved["completed_turns"], saved["elapsed_seconds"]
            if saved.get("finished"):
                termination = saved["termination_reason"]
        finished = bool(self.checkpoint_path and self.checkpoint_path.exists() and saved.get("finished"))

        def checkpoint(*, finished=False):
            if self.checkpoint_path:
                atomic_json(self.checkpoint_path, {"scenario_id": scenario_id, "state": asdict(server.state),
                    "messages": messages, "responses": responses, "tool_log": tool_log, "usages": usages,
                    "retries": retries, "invalid": invalid, "submitted": submitted,
                    "completed_turns": completed_turns, "elapsed_seconds": elapsed + time.monotonic() - started,
                    "termination_reason": termination, "finished": finished})

        def emit(kind: str, **data):
            if self.event_sink:
                self.event_sink({"event": kind, "turn": completed_turns, **data})

        checkpoint(finished=finished)
        emit("episode_resume" if completed_turns else "episode_start", n_completed_turns=completed_turns)
        for turn in range(completed_turns, self.max_turns):
            if finished:
                break
            cached = None
            if isinstance(hook, Campaign):
                self.llm.request_context["turn"] = turn + 1
                context = self.llm.request_context
                # Recover a paid response received before a checkpoint was saved.
                matches = [e for e in read_events(hook.path) if e["event"] == "finished"
                           and all(e.get("context", {}).get(k) == context.get(k) for k in ("run_id", "episode_key", "episode_attempt_id", "turn"))]
                cached = matches[-1] if matches else None
            try:
                if cached:
                    response = cached["visible_text"]
                    self.llm.last_debug = {"usage": {"input_tokens": cached["input_tokens"], "output_tokens": cached["output_tokens"], "total_tokens": cached["total_tokens"]},
                                           "status": cached.get("response_status"), "incomplete_details": {"reason": cached.get("incomplete_reason")},
                                           "choices": [{"finish_reason": cached.get("finish_reason")}]}
                else:
                    response = self.llm(messages) or ""
            except BudgetStop as stop:
                emit("api_policy_stop", reason=stop.reason)
                termination = stop.reason
                paused = stop.reason != "episode_cost_limit"
                checkpoint(finished=not paused)
                break
            except Exception as exc:
                termination = "infrastructure_error"
                emit("api_error", error_type=type(exc).__name__)
                checkpoint()
                raise
            raw_usage = (getattr(self.llm, "last_debug", None) or {}).get("usage")
            usages.append(raw_usage if isinstance(raw_usage, dict) else None)
            retries += int(cached["retry_index"] if cached else getattr(self.llm, "retry_count_last_call", 0))
            responses.append(response)
            messages.append({"role": "assistant", "content": response})
            completed_turns = turn + 1
            completion = OpenAIResponsesClient.completion_metadata(getattr(self.llm, "last_debug", None) or {})
            emit("model_response", request_id=cached["request_id"] if cached else getattr(self.llm, "last_request_id", None),
                 text=response, recovered_paid_response=bool(cached), **completion)
            try:
                command = parse_json_command(response)
            except ValueError:
                invalid += 1
                observation = {
                    "error": "invalid JSON command",
                    "instruction": "Return exactly one JSON command with fields 'tool' and 'args'.",
                }
                truncated = completion["incomplete_reason"] == "max_output_tokens" or completion["finish_reason"] == "length"
                error_kind = "output_truncated" if truncated else "parse_error"
                tool_log.append({"tool": error_kind, "observation": observation})
                emit(error_kind, error_code="max_output_tokens" if truncated else "invalid_json_command", **completion)
                messages.append({"role": "user", "content": json.dumps({"observation": observation})})
                checkpoint()
                continue
            tool = str(command.get("tool", ""))
            args = command.get("args", {})
            if not isinstance(args, dict):
                invalid += 1
                observation = {"error": "args must be a JSON object"}
                tool_log.append({"tool": "parse_error", "observation": observation})
                emit("parse_error", error_code="invalid_args")
                messages.append({"role": "user", "content": json.dumps({"observation": observation})})
                checkpoint()
                continue
            before_pf, before_evaluators = server.state.actual_power_flows, server.state.evaluator_calls
            emit("tool_started", tool=tool, args=args)
            try:
                observation, done = server.execute(tool, args)
            except Exception as exc:
                termination = "infrastructure_error"
                emit("tool_error", tool=tool, error_type=type(exc).__name__)
                checkpoint()
                raise
            feedback = observation.get("preview", observation.get("verification", {}))
            outcome = ("invalid_dispatch" if feedback.get("valid_action") is False else
                       "pf_nonconverged" if feedback.get("converged") is False else
                       "voltage_unresolved" if feedback.get("success") is False else
                       "unknown_tool" if tool.strip().lower() not in server.allowed_tools and tool.strip().lower() != "preview_bess_dispatch" else
                       "tool_error" if "error" in observation else "ok")
            emit("tool_finished", tool=tool, args=args, observation=observation, outcome=outcome, done=done,
                 n_actual_power_flows=server.state.actual_power_flows - before_pf,
                 n_evaluator_calls=server.state.evaluator_calls - before_evaluators)
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
                termination = "success" if observation.get("accepted") else ("first_failure_no_recovery" if not self.recovery else "submit_limit")
                checkpoint(finished=True)
                break
            checkpoint()
            if isinstance(hook, Campaign):
                reason = hook.reason(self.llm.request_context)
                if reason:
                    termination, paused = reason, reason != "episode_cost_limit"
                    checkpoint(finished=not paused)
                    break
        else:
            checkpoint(finished=True)
        if termination == "turn_limit" and isinstance(hook, Campaign):
            reason = hook.reason(self.llm.request_context, check_window=False)
            if reason:
                termination, paused = reason, reason != "episode_cost_limit"
                checkpoint(finished=not paused)
        emit("episode_stop", reason=termination, paused=paused, no_submission=not bool(submitted),
             n_llm_turns=len(responses))
        dispatch = (
            server.state.final_dispatch
            if server.state.final_dispatch is not None
            else []
        )
        auto = 0.0
        if not submitted:
            auto = 1.0
        def token_sum(*fields: str) -> int | None:
            values = [next((usage[key] for key in fields if key in usage), None) if usage else None for usage in usages]
            return sum(values) if values and all(isinstance(value, int) for value in values) else None

        input_tokens = token_sum("input_tokens", "prompt_tokens")
        output_tokens = token_sum("output_tokens", "completion_tokens")
        total_tokens = token_sum("total_tokens")
        if total_tokens is None and input_tokens is not None and output_tokens is not None:
            total_tokens = input_tokens + output_tokens
        return VoltageAgentOutput(
            name=self.name,
            dispatch=dispatch,
            termination_reason=termination,
            paused=paused,
            n_llm_turns=len(responses),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            usage_unavailable=bool(usages and (input_tokens is None or output_tokens is None)),
            api_retries=retries,
            latency_seconds=elapsed + time.monotonic() - started,
            attempts=server.state.attempts,
            tool_log=tool_log,
            raw_responses=responses,
            invalid_tool_calls=float(invalid),
            submitted_explicitly=submitted,
            auto_finalized=auto,
            preview_calls=float(server.state.preview_calls),
            power_flow_calls=float(server.state.actual_power_flows),
            n_preview_requests=server.state.preview_requests,
            n_submit_calls=len(server.state.attempts),
            n_evaluator_calls=server.state.evaluator_calls,
            n_actual_power_flows=server.state.actual_power_flows,
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
    if output.auto_finalized and not output.attempts:
        report["valid_action"] = 0.0
        report["success"] = 0.0
    report.update(
        {
            "agent": output.name,
            "n_attempts": float(len(output.attempts)),
            "n_recovery_steps": float(max(0, len(output.attempts) - 1)),
            "preview_calls": float(output.preview_calls),
            "n_power_flows": float(report["n_actual_power_flows"] + output.power_flow_calls),
            "n_llm_turns": output.n_llm_turns,
            "n_preview_calls": int(output.preview_calls),
            "n_preview_requests": output.n_preview_requests,
            "n_submit_calls": output.n_submit_calls or len(output.attempts),
            "n_evaluator_calls": 1 + output.n_evaluator_calls,
            "n_actual_power_flows": report["n_actual_power_flows"] + output.n_actual_power_flows,
            "input_tokens": output.input_tokens,
            "output_tokens": output.output_tokens,
            "total_tokens": output.total_tokens,
            "usage_unavailable": output.usage_unavailable,
            "api_retries": output.api_retries,
            "latency_seconds": output.latency_seconds,
            "first_pass_success": int(bool(output.attempts and output.attempts[0]["success"] == 1.0)),
            "recovered": int(bool(output.attempts and output.attempts[0]["success"] != 1.0 and report["success"] == 1.0)),
            "first_submit_failed": int(bool(output.attempts and output.attempts[0]["success"] != 1.0)),
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
