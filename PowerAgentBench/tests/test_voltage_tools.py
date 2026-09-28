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


def test_voltage_observation_does_not_repeat_static_network() -> None:
    from poweragentbench.voltage_case import public_scenario_card

    for domain in (False, True):
        server = VoltageToolServer("V0001", domain_interface=domain)
        summary, _ = server.execute("case_summary", {})
        state, _ = server.execute("inspect_voltage_state", {})
        capabilities, _ = server.execute("get_bess_capabilities", {})
        assert summary["network"] == server.metadata["network"]
        assert capabilities["bess"] == server.metadata["bess"]
        assert "network" not in state and "bess" not in state
        assert state == public_scenario_card(server.metadata, domain_specific=domain)
        old_state = {**state, "network": server.metadata["network"], "bess": server.metadata["bess"]}
        assert len(json.dumps(state)) < len(json.dumps(old_state)) / 2
        assert ("raw_bus_voltages_pu" in state) != domain
        assert ("operating_state" in state) == domain


def test_without_recovery_first_submission_is_terminal() -> None:
    server = VoltageToolServer("V0001", recovery=False)
    observation, done = server.execute("submit", {"dispatch": []})
    assert done is True
    assert observation["accepted"] is False
