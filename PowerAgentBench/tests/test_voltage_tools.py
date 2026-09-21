from __future__ import annotations

import json

from poweragentbench.voltage_case import DEFAULT_SCENARIO_ROOT
from poweragentbench.voltage_tools import VoltageToolServer


def _witness(scenario_id: str):
    rows = json.loads(
        (DEFAULT_SCENARIO_ROOT / "private" / "witnesses.json").read_text(
            encoding="utf-8"
        )
    )
    return next(row["dispatch"] for row in rows if row["scenario_id"] == scenario_id)


def test_verification_tool_is_conditionally_exposed() -> None:
    server = VoltageToolServer("V0001", verification=False)
    assert "preview_bess_dispatch" not in server.allowed_tools
    observation, done = server.execute("preview_bess_dispatch", {"dispatch": []})
    assert "error" in observation
    assert done is False


def test_recovery_returns_failure_feedback_then_accepts_correction() -> None:
    server = VoltageToolServer("V0001", recovery=True, max_attempts=2)
    first, done = server.execute("submit", {"dispatch": []})
    assert done is False
    assert first["must_replan"] is True
    assert first["verification"]["remaining_undervoltage_buses"]

    second, done = server.execute("submit", {"dispatch": _witness("V0001")})
    assert done is True
    assert second["accepted"] is True


def test_without_recovery_first_submission_is_terminal() -> None:
    server = VoltageToolServer("V0001", recovery=False)
    observation, done = server.execute("submit", {"dispatch": []})
    assert done is True
    assert observation["accepted"] is False
