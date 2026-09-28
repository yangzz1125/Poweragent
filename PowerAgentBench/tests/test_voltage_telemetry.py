import json

from poweragentbench.voltage_agentic import LLMVoltageAgent, score_voltage_output
from poweragentbench.voltage_tools import VoltageToolServer


def test_only_real_power_flows_count():
    server = VoltageToolServer("V0001", max_previews=1, max_attempts=1)
    bad = {"dispatch": [{"bess_id": "BESS_1", "p_mw": 99}]}
    server.execute("preview_bess_dispatch", bad)
    server.execute("preview_bess_dispatch", bad)  # exhausted, no evaluator call
    server.execute("submit", bad)
    server.execute("submit", bad)  # exhausted, no evaluator call
    assert (server.state.preview_requests, server.state.preview_calls) == (2, 1)
    assert (server.state.submit_requests, len(server.state.attempts)) == (2, 1)
    assert server.state.evaluator_calls == 2
    assert server.state.actual_power_flows == 0
    assert server.state.attempts[0]["n_actual_power_flows"] == 0


def test_final_replay_count_and_recovery():
    commands = iter([{"tool": "preview_bess_dispatch", "args": {"dispatch": []}}, {"tool": "submit", "args": {"dispatch": []}}])
    output = LLMVoltageAgent(lambda _: json.dumps(next(commands)), name="mock", max_turns=2, recovery=False).run("V0001")
    report = score_voltage_output("V0001", output)
    assert report["n_llm_turns"] == 2
    assert report["n_preview_calls"] == 1
    assert report["n_submit_calls"] == 1
    assert report["n_evaluator_calls"] == 3
    assert report["n_actual_power_flows"] == 3
    assert report["first_submit_failed"] == 1
    assert report["recovered"] == 0
    assert report["input_tokens"] is None


def test_no_submission_not_valid_action():
    output = LLMVoltageAgent(lambda _: "not-json", name="mock", max_turns=1).run("V0001")
    report = score_voltage_output("V0001", output)
    assert report["n_submit_calls"] == 0
    assert report["valid_action"] == 0.0
    assert report["success"] == 0.0
    assert report["first_submit_failed"] == 0
