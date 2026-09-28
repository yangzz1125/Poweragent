from collections import Counter
import json

import pytest

from scripts.generate_voltage_corpus import generate
from poweragentbench.voltage_agentic import LLMVoltageAgent
from poweragentbench.voltage_case import DEFAULT_CONFIG_PATH, REPO_ROOT, load_manifest, read_json, sha256_file
from poweragentbench.voltage_evaluator import evaluate_voltage_dispatch


def test_corpus_generation(tmp_path):
    root = tmp_path / "corpus"
    corpus = generate(2026, 120, 6, 6, root, DEFAULT_CONFIG_PATH)
    assert corpus["dataset_sha256"]
    assert corpus["split_policy"] == "seeded-within-severity-stratum-v2"
    assert corpus["generator_sha256"]
    assert corpus["generator_version"] == "spatial-coordinate-v2"
    assert len(read_json(root / "candidate_audit.json")) == 120
    witnesses = read_json(root / "evaluator_private" / "witnesses.json")
    assert len(witnesses) == 12
    for split in ("dev", "test"):
        entries = load_manifest(root / split)["scenarios"]
        assert len(entries) == 6
        assert Counter((e["condition"], e["difficulty"]) for e in entries) == Counter({(c, d): 1 for c in ("UNDERVOLTAGE", "OVERVOLTAGE") for d in ("easy", "medium", "hard")})
        assert sha256_file(root / split / "manifest.json") == corpus["split_manifest_sha256"][split]
    for row in witnesses:
        assert evaluate_voltage_dispatch(row["scenario_id"], row["dispatch"], scenario_root=root / row["split"])["success"] == 1.0
    with pytest.raises(ValueError, match="outside PowerAgentBench"):
        generate(2026, 120, 6, 6, REPO_ROOT / "scenarios" / "bad", DEFAULT_CONFIG_PATH)

    witness = next(row["dispatch"] for row in witnesses if row["scenario_id"] == "D0001")
    for domain in (False, True):
        for verification in (False, True):
            for recovery in (False, True):
                commands = ["case_summary", "inspect_voltage_state", "get_bess_capabilities"]
                if verification:
                    commands.append("preview_bess_dispatch")
                commands.append("submit")
                seen = []

                def llm(messages):
                    seen.append(json.dumps(messages))
                    tool = commands[len(seen) - 1]
                    return json.dumps({"tool": tool, "args": {"dispatch": witness} if tool in ("submit", "preview_bess_dispatch") else {}})

                result = LLMVoltageAgent(
                    llm, name="leak-check", scenario_root=root / "dev",
                    domain_interface=domain, verification=verification, recovery=recovery,
                ).run("D0001")
                assert result.attempts[-1]["success"] == 1.0
                visible = "".join(seen) + json.dumps(result.tool_log)
                for secret in (str(root), "full_path", "full_sha256", "witnesses", "candidate_index", "generation_seed"):
                    assert secret not in visible
                assert ("operating_state" in visible) == domain
                assert ("raw_bus_voltages_pu" in visible) != domain
                assert any(row["tool"] == "preview_bess_dispatch" for row in result.tool_log) == verification
                assert ("preview_bess_dispatch" in json.loads(seen[0])[1]["content"]) == verification


def test_witness_search_can_find_nonuniform_dispatch(monkeypatch):
    import scripts.generate_voltage_corpus as generator
    config = {"bess": [{"bess_id": k, "step_mw": .25, "p_min_mw": -.5, "p_max_mw": .5} for k in ("A", "B")], "solver": {}}
    monkeypatch.setattr(generator, "apply_bess_dispatch", lambda net, dispatch, _: net.update({d["bess_id"]: d["p_mw"] for d in dispatch}))
    monkeypatch.setattr(generator, "run_locked_power_flow", lambda *_: (True, None))
    def metrics(net, *_args, **_kwargs):
        magnitude = abs(net["A"] - .5) + abs(net["B"] + .25)
        return {"voltage_violation_magnitude": magnitude, "voltage_violation_count": int(magnitude > 0)}
    monkeypatch.setattr(generator, "state_metrics", metrics)
    witness, calls = generator.find_witness({"A": 0, "B": 0}, config, {"voltage_violation_magnitude": .75})
    assert {d["bess_id"]: d["p_mw"] for d in witness} == {"A": .5, "B": -.25}
    assert 0 < calls <= 48 * 4


def test_tool_failure_is_not_sent_to_model(monkeypatch):
    from poweragentbench.voltage_tools import VoltageToolServer

    def fail(*_args):
        raise RuntimeError("SECRET_EVALUATOR_PATH")

    monkeypatch.setattr(VoltageToolServer, "execute", fail)
    received = []

    def llm(messages):
        received.append(json.dumps(messages))
        return '{"tool":"case_summary","args":{}}'

    with pytest.raises(RuntimeError, match="SECRET_EVALUATOR_PATH"):
        LLMVoltageAgent(llm, name="test").run("V0001")
    assert len(received) == 1
    assert "SECRET_EVALUATOR_PATH" not in received[0]
