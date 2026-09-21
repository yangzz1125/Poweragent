from __future__ import annotations

import json

from poweragentbench.voltage_agentic import LLMVoltageAgent, score_voltage_output
from poweragentbench.voltage_case import DEFAULT_SCENARIO_ROOT


def _witness(scenario_id: str):
    rows = json.loads(
        (DEFAULT_SCENARIO_ROOT / "private" / "witnesses.json").read_text(
            encoding="utf-8"
        )
    )
    return next(row["dispatch"] for row in rows if row["scenario_id"] == scenario_id)


def test_llm_agent_uses_recovery_feedback() -> None:
    replies = iter(
        [
            json.dumps({"tool": "submit", "args": {"dispatch": []}}),
            json.dumps({"tool": "submit", "args": {"dispatch": _witness("V0001")}}),
        ]
    )
    agent = LLMVoltageAgent(
        lambda _messages: next(replies),
        name="mock-agent",
        recovery=True,
        verification=False,
        max_turns=2,
    )
    output = agent.run("V0001")
    metrics = score_voltage_output("V0001", output)
    assert metrics["success"] == 1.0
    assert metrics["n_attempts"] == 2.0
    assert metrics["n_recovery_steps"] == 1.0


def test_malformed_output_is_logged_and_reprompted() -> None:
    replies = iter(
        [
            "not json",
            json.dumps({"tool": "submit", "args": {"dispatch": _witness("V0001")}}),
        ]
    )
    output = LLMVoltageAgent(
        lambda _messages: next(replies), name="mock-agent", max_turns=2
    ).run("V0001")
    assert output.invalid_tool_calls == 1.0
    assert output.tool_log[0]["tool"] == "parse_error"


def test_last_invalid_submission_is_not_replaced_by_an_earlier_attempt() -> None:
    replies = iter(
        [
            json.dumps({"tool": "submit", "args": {"dispatch": []}}),
            json.dumps(
                {
                    "tool": "submit",
                    "args": {"dispatch": [{"bess_id": "BESS_1", "p_mw": 99.0}]},
                }
            ),
        ]
    )
    output = LLMVoltageAgent(
        lambda _messages: next(replies),
        name="mock-agent",
        max_turns=2,
        recovery=True,
        verification=False,
    ).run("V0001")
    metrics = score_voltage_output("V0001", output)
    assert metrics["valid_action"] == 0.0
    assert metrics["success"] == 0.0
