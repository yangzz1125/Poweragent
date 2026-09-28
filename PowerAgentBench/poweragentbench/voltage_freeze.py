"""Offline, credential-free identities for explicit pre-freeze review."""
from __future__ import annotations

import hashlib
import json
import platform
from functools import lru_cache
from importlib.metadata import distributions


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@lru_cache(maxsize=1)
def environment_identity() -> dict:
    return {
        "python": platform.python_version(), "implementation": platform.python_implementation(),
        "system": platform.system(), "machine": platform.machine(),
        "packages": dict(sorted((dist.metadata["Name"].lower().replace("_", "-"), dist.version)
                                for dist in distributions() if dist.metadata.get("Name"))),
    }


FREEZE_FIELDS = (
    "provider", "model", "api_mode", "split", "dataset_sha256", "dataset_version", "split_manifest_sha256",
    "prompt_sha256", "benchmark_config_sha256", "conditions_sha256", "code_commit", "source_sha256",
    "environment_sha256", "model_settings", "model_settings_sha256", "task_order_version", "planned_tasks",
    "max_turns", "max_output_tokens", "max_preview_calls", "max_submission_attempts", "repeats",
    "pricing_sha256", "accounting_policy", "analysis_protocol_sha256",
)


def freeze_contract(identity: dict) -> dict:
    missing = [key for key in FREEZE_FIELDS if key not in identity or identity[key] is None]
    if missing:
        raise ValueError(f"freeze identity missing fields: {missing}")
    return {key: identity[key] for key in FREEZE_FIELDS}


def candidate_manifest(identity: dict) -> dict:
    contract = freeze_contract(identity)
    if contract["split"] != "test" or contract["repeats"] != 3:
        raise ValueError("main freeze candidate requires Test and three repeats")
    return {"schema_version": 1, "status": "candidate", "main_authorized": False,
            "benchmark_tag": "benchmark-v1.0", "contract": contract, "contract_sha256": digest(contract),
            "limitations": ["Model alias can change upstream; reported alias is not an immutable model version.",
                            "This file is a candidate only, not approval, a tag or paid Test authorization."]}


def validate_freeze(manifest: dict, identity: dict) -> None:
    if manifest.get("schema_version") != 1 or manifest.get("status") != "approved" or manifest.get("main_authorized") is not True:
        raise ValueError("Test requires an explicitly approved freeze and Main authorization")
    contract = manifest.get("contract")
    if not isinstance(contract, dict) or manifest.get("contract_sha256") != digest(contract):
        raise ValueError("freeze contract digest mismatch")
    current = freeze_contract(identity)
    mismatches = [key for key in FREEZE_FIELDS if contract.get(key) != current[key]]
    if mismatches:
        raise ValueError(f"freeze identity mismatch: {', '.join(mismatches)}")
