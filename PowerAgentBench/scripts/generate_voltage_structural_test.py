"""Offline v3 Test scout/build per docs/V3_TEST_GENERATION_PROTOCOL.md. No model API, no freeze."""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from collections import Counter, defaultdict, deque
from pathlib import Path

from poweragentbench.voltage_case import (DEFAULT_CONFIG_PATH, load_benchmark_config, read_json, sha256_file)
from poweragentbench.voltage_freeze import digest, environment_identity
from poweragentbench.voltage_storage import evaluator_output_root
from poweragentbench.voltage_structure import (BudgetExhausted, PFStore, identity, near_duplicate, verify_certificate)
from scripts.generate_voltage_structural_corpus import (VERSIONS, evaluate_candidate, independent, load_rows,
                                                        make_candidate, manifest, save_scenario, write_json)

CLASSES = ("S1", "S2", "S3", "S4")
DEV_ROOT = Path(__file__).resolve().parents[2] / ".local-data" / "voltage_structure_v3"
MAX_CANDIDATES_PER_ROUND, MAX_ROUNDS = 512, 6


def dev_exclusions(dev_root: Path):
    """Operating families, fingerprints and vectors of the 32 selected Dev scenarios."""
    manifest_path = dev_root / "dev" / "manifest.json"
    dev_ids = {e["candidate_id"] for e in read_json(manifest_path)["scenarios"]}
    rows = [r for r in load_rows(dev_root) if r["candidate_id"] in dev_ids]
    if len(rows) != len(dev_ids):
        raise ValueError("Dev candidate rows missing; cannot exclude Dev families")
    return ({r["operating_family_id"] for r in rows}, {r["physical_fingerprint"] for r in rows},
            [r["physical_vector"] for r in rows], sha256_file(manifest_path))


def select_test(rows, seed, per_class, exclusions):
    """Same rule as select_dev, pre-seeded with the Dev exclusions. No model scores."""
    families, fingerprints, vectors = set(exclusions[0]), set(exclusions[1]), list(exclusions[2])
    chosen, rejected = [], []
    for label in CLASSES:
        pool = sorted((r for r in rows if r.get("structure_class") == label),
                      key=lambda r: digest([seed, "selection", r["candidate_id"]]))
        buckets = defaultdict(list)
        for row in pool:
            buckets[(row["initial_voltage_condition"], row["spatial_family_id"])].append(row)
        directions = {c: deque(sorted(k for k in buckets if k[0] == c)) for c in sorted({k[0] for k in buckets})}
        ordered = []
        while any(directions.values()):
            for keys in directions.values():
                if keys:
                    key = keys[0]
                    ordered.append(buckets[key].pop())
                    if buckets[key]:
                        keys.rotate(-1)
                    else:
                        keys.popleft()
        count = 0
        for row in ordered:
            if (row["physical_fingerprint"] in fingerprints or row["operating_family_id"] in families
                    or any(near_duplicate(row["physical_vector"], v) for v in vectors)):
                rejected.append({"candidate_id": row["candidate_id"], "reason": "duplicate_family_or_near_state_or_dev"})
                continue
            if count >= per_class:
                continue
            chosen.append(row)
            count += 1
            families.add(row["operating_family_id"])
            vectors.append(row["physical_vector"])
            fingerprints.add(row["physical_fingerprint"])
    return chosen, rejected


def selectable_ok(chosen, per_class):
    counts = Counter(r["structure_class"] for r in chosen)
    s4_families = {r["spatial_family_id"] for r in chosen if r["structure_class"] == "S4"}
    return all(counts[k] >= per_class for k in CLASSES) and len(s4_families) >= 2


def summarize(root, store, protocol, exclusions):
    rows = load_rows(root)
    chosen, rejected = select_test(rows, protocol["seed"], protocol["test_per_structure"], exclusions)
    summary = {"candidates_completed": len(rows), "actual_pf_calls": store.count, "pf_by_phase": store.totals(),
               "certified_counts": dict(Counter(r["structure_class"] for r in rows if r.get("structure_class"))),
               "selectable_counts": dict(Counter(r["structure_class"] for r in chosen)),
               "target_per_structure": protocol["test_per_structure"],
               "s4_spatial_families": len({r["spatial_family_id"] for r in chosen if r["structure_class"] == "S4"}),
               "selection_rejections": len(rejected), "model_api_requests": 0, "test_generated": False,
               "feasible": selectable_ok(chosen, protocol["test_per_structure"]), "by_recipe": {}}
    for recipe in "ABCD":
        subset = [r for r in rows if r["recipe_id"] == recipe]
        summary["by_recipe"][recipe] = {"candidates": len(subset),
                                        "status_counts": dict(Counter(r["classification_status"] for r in subset))}
    write_json(root / "exploration" / "summary.json", summary)
    with (root / "exploration" / "candidate_audit.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    return summary, chosen


def build_test(root, chosen, protocol, config, store, ident):
    if (root / "corpus_manifest.json").exists():
        return read_json(root / "corpus_manifest.json")
    entries, witnesses = [], []
    chosen = sorted(chosen, key=lambda r: digest([protocol["seed"], "opaque-id", r["candidate_id"]]))
    for i, row in enumerate(chosen, 1):
        sid = f"T{i:04d}"
        net, _ = make_candidate(row["candidate_index"], protocol, config)
        old = root / "evaluator_private" / "candidates" / row["candidate_id"]
        old_public = read_json(old / "public" / f"{row['candidate_id']}.json")
        entry = save_scenario(root / "test", sid, net, old_public["initial_state"], config)
        if entry["full_sha256"] != row["snapshot_sha256"]:
            raise ValueError("rebuilt Test snapshot differs from certified candidate")
        cert = read_json(root / row["certificate_path"])
        verify_certificate(cert, ident, row["snapshot_sha256"])
        entry.update({k: row[k] for k in ("structure_class", "recipe_id", "operating_family_id", "spatial_family_id",
                                          "physical_fingerprint", "witness_voltage_margin", "certificate_path",
                                          "certificate_sha256", "all_full_feasible")})
        entry["candidate_id"] = row["candidate_id"]
        entry["difficulty"] = "unstratified"
        entry["fragile"] = row["witness_voltage_margin"] < 1e-4
        entries.append(entry)
        write_json(root / "test" / "manifest.json", manifest(entries, config))
        replay = independent(store, [sid, entry["full_sha256"], "test_witness"], sid, cert["witness"], root / "test", config, "test_replay")
        if not replay["success"]:
            raise RuntimeError("selected Test witness failed independent replay")
        from poweragentbench.voltage_structure import dispatch
        witnesses.append({"scenario_id": sid, "candidate_id": row["candidate_id"],
                          "dispatch": dispatch(cert["witness"], config["bess"]), "replay": replay})
    write_json(root / "evaluator_private" / "witnesses.json", witnesses)
    counts = Counter(r["structure_class"] for r in chosen)
    evidence_hash = digest({r["candidate_id"]: r["certificate_sha256"] for r in chosen})
    test_manifest = read_json(root / "test" / "manifest.json")
    test_manifest["structure_evidence_sha256"] = evidence_hash
    write_json(root / "test" / "manifest.json", test_manifest)
    corpus = {**VERSIONS, "dataset_version": config["dataset_version"], "benchmark_config_sha256": sha256_file(DEFAULT_CONFIG_PATH),
              "generation_protocol_sha256": digest(protocol), "structure_evidence_sha256": evidence_hash,
              "numerical_identity": ident, "split_manifest_sha256": {"test": sha256_file(root / "test" / "manifest.json")},
              "witnesses_sha256": sha256_file(root / "evaluator_private" / "witnesses.json"),
              "num_dev": 0, "num_test": len(entries), "status": "TEST_BUILT", "structure_counts": dict(counts),
              "main_authorized": False}
    corpus["dataset_sha256"] = digest(corpus)
    write_json(root / "corpus_manifest.json", corpus)
    return corpus


def build_protocol(seed, candidates, rounds, pf_limit, search_calls, scans, per_class, dev_manifest_sha, ident):
    return {**VERSIONS, "seed": seed, "candidates_per_round": candidates, "rounds": rounds,
            "pf_per_round_limit": pf_limit, "total_pf_limit": pf_limit * rounds, "search_calls": search_calls,
            "full_scan_candidates_per_round": scans, "test_per_structure": per_class,
            "protocol_document": "docs/V3_TEST_GENERATION_PROTOCOL.md", "dev_manifest_sha256": dev_manifest_sha,
            "recipes": "A v2 envelope; B branch-correlated; C PV in one electrical group; D low-load PV group/high-load other groups",
            "envelope": {"global_load_scale": [.3, 1.5], "local_multiplier": [.3, 2.5], "pv_buses": [5, 32], "pv_count": [0, 4], "pv_mw": [.1, 3.5]},
            "initial_acceptance": "finite/converged, nonzero pure under OR pure over; no severity or margin acceptance cutoff",
            "selection": "seeded priorities, direction/spatial-family round-robin; one per operating family; exclude Dev families/fingerprints/near-duplicates",
            "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "generator_sha256": sha256_file(__file__), "numerical_identity": ident, "api_calls_allowed": False,
            "test_model_runs_allowed": False}


def run(root, mode, seed=2041, candidates=512, rounds=6, pf_limit=250000, search_calls=384, scans=2, per_class=24,
        dev_root=DEV_ROOT):
    root = evaluator_output_root(root)
    if not (0 < candidates <= MAX_CANDIDATES_PER_ROUND and candidates % 4 == 0 and 1 <= rounds <= MAX_ROUNDS
            and 0 < pf_limit <= 250000 and 0 <= scans <= 12 and 0 < search_calls <= 512 and 0 < per_class <= 24):
        raise ValueError("invalid or excessive offline bounds")
    config = load_benchmark_config()
    ident = identity(config)
    exclusions = dev_exclusions(Path(dev_root))
    protocol = build_protocol(seed, candidates, rounds, pf_limit, search_calls, scans, per_class, exclusions[3], ident)
    protocol_path = root / "exploration" / "protocol.json"
    if protocol_path.exists():
        if read_json(protocol_path) != protocol:
            raise ValueError("resume protocol/source/limits mismatch")
    else:
        if root.exists() and any(root.iterdir()):
            raise ValueError("new evaluator root must be empty")
        write_json(protocol_path, protocol)
        write_json(root / "exploration" / "environment.json", environment_identity())
    store = PFStore(root / "exploration" / "pf_ledger.sqlite", ident, protocol["total_pf_limit"])
    try:
        if mode in ("scout", "build-test"):
            for round_i in range(rounds):
                store.limit = min(protocol["total_pf_limit"], (round_i + 1) * pf_limit)
                try:
                    for i in range(round_i * candidates, (round_i + 1) * candidates):
                        path = root / "exploration" / "checkpoint" / f"N{i:05d}.json"
                        if path.exists():
                            continue
                        start = time.monotonic()
                        try:
                            row = evaluate_candidate(i, root, protocol, config, store, ident)
                        except BudgetExhausted:
                            _, partial = make_candidate(i, protocol, config)
                            partial.update(classification_status="budget_partial", structure_class=None, identity=ident,
                                           rejection_or_unresolved_reason="PF budget exhausted; cached partial evidence is not certification",
                                           actual_total_pf_calls=store.candidate_count(partial["candidate_id"]))
                            write_json(path, partial)
                            raise
                        row["actual_total_pf_calls"] = store.candidate_count(row["candidate_id"])
                        row["elapsed_seconds"] = time.monotonic() - start
                        write_json(path, row)
                        if (i + 1) % 16 == 0:
                            summary, _ = summarize(root, store, protocol, exclusions)
                            print(json.dumps({"completed": i + 1, "pf": store.count, "certified": summary["certified_counts"],
                                              "selectable": summary["selectable_counts"]}), flush=True)
                    rows = load_rows(root)
                    queue = sorted([r for r in rows if round_i * candidates <= r["candidate_index"] < (round_i + 1) * candidates
                                    and r["classification_status"] == "search_unresolved"],
                                   key=lambda r: digest([seed, "scan", r["candidate_id"]]))[:scans]
                    queue_path = root / "exploration" / f"scan_queue_{round_i}.json"
                    if queue_path.exists():
                        by_id = {r["candidate_id"]: r for r in rows}
                        queue = [by_id[sid] for sid in read_json(queue_path)]
                    else:
                        write_json(queue_path, [r["candidate_id"] for r in queue])
                    for old in queue:
                        if "+full_grid_scan" in old.get("search_method", ""):
                            continue
                        row = evaluate_candidate(old["candidate_index"], root, protocol, config, store, ident, scan=True)
                        row["actual_total_pf_calls"] = store.candidate_count(row["candidate_id"])
                        write_json(root / "exploration" / "checkpoint" / f"{row['candidate_id']}.json", row)
                except BudgetExhausted as exc:
                    write_json(root / "exploration" / f"budget_stop_{round_i}.json", {"reason": str(exc), "actual_pf_calls": store.count})
                summary, chosen = summarize(root, store, protocol, exclusions)
                if summary["feasible"]:
                    break
        store.limit = protocol["total_pf_limit"]
        summary, chosen = summarize(root, store, protocol, exclusions)
        if mode == "build-test":
            if not summary["feasible"]:
                raise ValueError(f"Test not feasible; refusing to build with a shortfall: {summary['selectable_counts']}")
            build_test(root, chosen, protocol, config, store, ident)
            summary, _ = summarize(root, store, protocol, exclusions)
            summary["test_generated"] = True
        return summary
    finally:
        store.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=("scout", "build-test"), required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--seed", type=int, default=2041)
    p.add_argument("--candidates", type=int, default=512)
    p.add_argument("--rounds", type=int, default=6)
    p.add_argument("--pf-limit", type=int, default=250000)
    p.add_argument("--search-calls", type=int, default=384)
    p.add_argument("--scans", type=int, default=2)
    p.add_argument("--test-per-structure", type=int, default=24)
    p.add_argument("--dev-root", type=Path, default=DEV_ROOT)
    a = p.parse_args()
    print(json.dumps(run(a.output_dir, a.mode, a.seed, a.candidates, a.rounds, a.pf_limit, a.search_calls, a.scans,
                         a.test_per_structure, a.dev_root), indent=2))


if __name__ == "__main__":
    main()
