"""Frozen IEEE 33-bus voltage-control scenario construction and loading."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_DIR = REPO_ROOT / "benchmarks" / "steady" / "voltage_control"
DEFAULT_SCENARIO_ROOT = BENCHMARK_DIR / "scenarios" / "ieee33"
DEFAULT_CONFIG_PATH = BENCHMARK_DIR / "config" / "benchmark.json"


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_pandapower_json(net: Any, path: str | Path) -> None:
    """Write a pandapower JSON artifact, including on Python 3.13.

    pandapower 3.1's custom encoder passes an integer indentation value into an
    encoder path that Python 3.13 expects to be a string. A string indentation
    value is accepted by all supported Python versions and preserves the native
    pandapower JSON format consumed by ``pp.from_json``.
    """
    from pandapower.io_utils import PPJSONEncoder

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(net, cls=PPJSONEncoder, indent="  "), encoding="utf-8")


def load_benchmark_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    config = read_json(path)
    if config.get("benchmark_id") != "ieee33_bess_voltage_control_v1":
        raise ValueError("unsupported voltage benchmark configuration")
    return config


def load_manifest(scenario_root: str | Path = DEFAULT_SCENARIO_ROOT) -> dict[str, Any]:
    root = Path(scenario_root)
    manifest = read_json(root / "manifest.json")
    if manifest.get("dataset_version") != "ieee33-bess-voltage-v1":
        raise ValueError("unsupported voltage scenario dataset version")
    return manifest


def scenario_ids(scenario_root: str | Path = DEFAULT_SCENARIO_ROOT) -> list[str]:
    return [
        str(entry["scenario_id"]) for entry in load_manifest(scenario_root)["scenarios"]
    ]


def load_scenario_metadata(
    scenario_id: str,
    scenario_root: str | Path = DEFAULT_SCENARIO_ROOT,
    *,
    verify_hashes: bool = True,
) -> dict[str, Any]:
    root = Path(scenario_root)
    manifest = load_manifest(root)
    entry = next(
        (row for row in manifest["scenarios"] if row["scenario_id"] == scenario_id),
        None,
    )
    if entry is None:
        raise ValueError(f"unknown voltage scenario {scenario_id!r}")
    public_path = root / entry["public_path"]
    full_path = root / entry["full_path"]
    if verify_hashes:
        for path, field in ((public_path, "public_sha256"), (full_path, "full_sha256")):
            if not path.is_file() or sha256_file(path) != entry[field]:
                raise ValueError(f"scenario artifact hash mismatch: {path}")
    metadata = read_json(public_path)
    metadata["full_path"] = str(full_path.resolve())
    metadata["dataset_version"] = manifest["dataset_version"]
    metadata["artifact_hash"] = entry["full_sha256"]
    metadata["benchmark_config_sha256"] = manifest.get("benchmark_config_sha256")
    return metadata


def load_scenario_network(
    scenario_id: str,
    scenario_root: str | Path = DEFAULT_SCENARIO_ROOT,
    *,
    verify_hashes: bool = True,
) -> Any:
    import pandapower as pp

    metadata = load_scenario_metadata(
        scenario_id, scenario_root, verify_hashes=verify_hashes
    )
    return pp.from_json(metadata["full_path"])


def public_scenario_card(
    metadata: dict[str, Any], *, domain_specific: bool
) -> dict[str, Any]:
    """Render information-equivalent generic/domain-specific scenario interfaces."""
    common = {
        "scenario_id": metadata["scenario_id"],
        "network": metadata["network"],
        "voltage_limits_pu": metadata["voltage_limits_pu"],
        "bess": metadata["bess"],
    }
    state = metadata["initial_state"]
    if domain_specific:
        common["operating_state"] = {
            "condition": state["condition"],
            "minimum_voltage_pu": state["min_vm_pu"],
            "maximum_voltage_pu": state["max_vm_pu"],
            "undervoltage_buses": state["undervoltage_buses"],
            "overvoltage_buses": state["overvoltage_buses"],
            "interface_note": (
                "Positive benchmark BESS p_mw means discharge/injection; negative means charging/withdrawal."
            ),
        }
    else:
        common["raw_bus_voltages_pu"] = state["bus_voltages_pu"]
        common["sign_convention"] = {
            "positive_p_mw": "power injected into the grid",
            "negative_p_mw": "power withdrawn from the grid",
        }
    return common


def build_ieee33_network(
    *,
    load_scale: float,
    pv_injections: Iterable[tuple[int, float]],
    bess_specs: Iterable[dict[str, Any]],
) -> Any:
    """Build one deterministic snapshot. Generation is used only to construct the corpus."""
    import pandapower as pp
    import pandapower.networks as pn

    net = pn.case33bw()
    net.name = "IEEE 33-bus BESS voltage-control snapshot"
    net.load.loc[:, "p_mw"] *= float(load_scale)
    net.load.loc[:, "q_mvar"] *= float(load_scale)
    for bus, p_mw in pv_injections:
        pp.create_sgen(
            net, bus=int(bus), p_mw=float(p_mw), q_mvar=0.0, name=f"PV_bus_{bus}"
        )
    for spec in bess_specs:
        # pandapower storage convention is positive=charging. The benchmark-facing
        # convention is translated in voltage_evaluator.apply_bess_dispatch.
        pp.create_storage(
            net,
            bus=int(spec["bus"]),
            p_mw=0.0,
            max_e_mwh=1.0,
            min_e_mwh=0.0,
            soc_percent=50.0,
            name=str(spec["bess_id"]),
            controllable=True,
        )
    return net
