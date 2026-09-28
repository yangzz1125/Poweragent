import copy
import json

import pytest

from poweragentbench.voltage_freeze import FREEZE_FIELDS, candidate_manifest, digest, environment_identity, validate_freeze
from scripts.run_voltage_agent_eval import model_request_settings
from scripts.run_voltage_experiment_matrix import run_matrix
from tests.test_voltage_matrix import options


def identity():
    result = {key: f"test-{key}" for key in FREEZE_FIELDS}
    result.update(split="test", repeats=3, model_settings={"reasoning_effort": "high", "max_output_tokens": 16384},
                  planned_tasks=[["I0-V0-R0", "T0001", 0]])
    return result


def test_candidate_cannot_authorize_main():
    current = identity()
    candidate = candidate_manifest(current)
    assert candidate["status"] == "candidate" and candidate["main_authorized"] is False
    with pytest.raises(ValueError, match="explicitly approved"):
        validate_freeze(candidate, current)
    candidate.update(status="approved", main_authorized=True)
    validate_freeze(candidate, current)


@pytest.mark.parametrize("key", FREEZE_FIELDS)
def test_every_frozen_field_is_checked(key):
    current = identity()
    frozen = candidate_manifest(current)
    frozen.update(status="approved", main_authorized=True)
    changed = copy.deepcopy(current)
    changed[key] = "changed"
    with pytest.raises(ValueError, match="freeze identity mismatch"):
        validate_freeze(frozen, changed)


def test_environment_and_model_settings_are_explicit(tmp_path):
    env = environment_identity()
    assert env["python"] and env["packages"]["pandapower"] and env["packages"]["numpy"]
    assert digest(env) == digest(environment_identity())
    args = options(tmp_path, url="https://api.deepseek.com", api_mode="responses", model="deepseek-flash")
    settings = model_request_settings(args)
    assert settings["reasoning_effort"] == "high"
    assert settings["temperature_policy"] == "ignored_in_thinking_mode"
    args.reasoning_effort = "none"
    assert model_request_settings(args)["temperature_policy"] == "requested"
    args.api_mode = "chat"
    with pytest.raises(ValueError, match="requires Responses"):
        model_request_settings(args)


def test_legacy_three_hash_manifest_cannot_start_test(tmp_path):
    freeze = tmp_path / "freeze.json"
    freeze.write_text(json.dumps({"dataset_sha256": "legacy", "prompt_sha256": "legacy", "benchmark_config_sha256": "legacy"}))
    args = options(tmp_path, split="test", freeze_manifest=freeze)
    with pytest.raises(ValueError, match="explicitly approved"):
        run_matrix(args, lambda _: pytest.fail("must not construct API client"))
    assert not args.output_dir.exists()
