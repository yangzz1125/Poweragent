"""Run the eight voltage Harness conditions with a durable, resumable episode ledger."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from poweragentbench.voltage_costs import Campaign, BudgetStop, PRICING_PATH, ledger_totals, append_event

from poweragentbench.voltage_agentic import LLMVoltageAgent, load_voltage_prompt, score_voltage_output
from poweragentbench.voltage_case import DEFAULT_CONFIG_PATH, BENCHMARK_DIR, REPO_ROOT, load_manifest, read_json, sha256_file
from scripts.run_voltage_agent_eval import load_env_file, make_client

EXPERIMENTS = BENCHMARK_DIR / "config" / "experiments.json"
PROMPT = BENCHMARK_DIR / "prompts" / "voltage_agent_prompt.json"
FIELDS = (
    "run_id provider model api_mode split condition domain_interface verification recovery repetition_index scenario_id difficulty voltage_condition "
    "status error_type success valid_action first_pass_success first_submit_failed recovered initial_violation_count final_violation_count "
    "initial_violation_magnitude final_violation_magnitude action_l1_mw n_llm_turns n_preview_calls n_preview_requests "
    "n_submit_calls n_evaluator_calls n_actual_power_flows input_tokens output_tokens total_tokens usage_unavailable api_retries "
    "latency_seconds prompt_sha256 benchmark_config_sha256 dataset_sha256 dataset_version code_commit source_sha256 temperature "
    "max_turns max_output_tokens max_preview_calls max_submission_attempts campaign_id episode_attempt termination_reason "
    "accounted_cost_cny unknown_cost_requests cost_status no_submission n_api_requests"
).split()
KEYS = ("condition", "scenario_id", "repetition_index")


def atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def append_jsonl(path: Path, item: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, sort_keys=True, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def load_ledger(path: Path) -> dict[tuple, dict]:
    rows = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        key = tuple(row[field] for field in KEYS)
        if key in rows:
            raise ValueError(f"duplicate episode in ledger: {key}")
        rows[key] = row
    return rows


def ordered_tasks(entries: list[dict], conditions: list[dict], repeats: int) -> list[tuple[dict, dict, int]]:
    entries = list(entries)
    random.Random(2026).shuffle(entries)
    tasks = []
    rng = random.Random(2027)
    for repeat in range(repeats):
        for entry in entries:
            order = list(conditions)
            rng.shuffle(order)
            tasks.extend((entry, condition, repeat) for condition in order)
    return tasks


def source_identity() -> str:
    """Hash tracked implementation inputs, including dirty/untracked Python files.

    Excludes secrets, local results, caches and nested git metadata.
    """
    paths = [REPO_ROOT / "pyproject.toml"]
    for folder in ("poweragentbench", "scripts"):
        paths.extend(sorted((REPO_ROOT / folder).glob("*.py")))
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(REPO_ROOT).as_posix().encode() + b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def run_matrix(args: argparse.Namespace, client_factory=make_client) -> dict[str, Any]:
    campaign_dir = getattr(args, "campaign_dir", None)
    if campaign_dir is None or args.dry_run:
        return _run_matrix(args, client_factory)
    if args.max_total_tokens is not None or args.max_cost_usd is not None:
        raise ValueError("CNY campaign cannot be combined with token/USD gates")
    if args.provider != "openai" or args.model != "deepseek-flash" or args.api_mode != "responses":
        raise ValueError("approved CNY campaign requires DeepSeek Flash Responses")
    url = args.url or os.getenv("POWERAGENTBENCH_OPENAI_URL", "")
    if urlparse(url).hostname != "api.deepseek.com" or urlparse(url).scheme != "https":
        raise ValueError("CNY price snapshot applies only to the official DeepSeek HTTPS endpoint")
    with Campaign(Path(campaign_dir), episode_limit=getattr(args, "max_episode_cost_cny", "0.20"),
                  campaign_limit=getattr(args, "max_campaign_cost_cny", "10"),
                  pricing_path=getattr(args, "pricing_file", PRICING_PATH),
                  stage=getattr(args, "campaign_stage", "smoke")) as campaign:
        return _run_matrix(args, client_factory, campaign=campaign)


def _run_matrix(args: argparse.Namespace, client_factory=make_client, *, campaign=None) -> dict[str, Any]:
    config = read_json(DEFAULT_CONFIG_PATH)
    experiments = read_json(EXPERIMENTS)
    conditions = experiments["conditions"]
    if len(conditions) != 8 or len({tuple(bool(row[x]) for x in experiments["factors"]) for row in conditions}) != 8:
        raise ValueError("experiments.json must contain all eight unique I/V/R conditions")
    if args.repeats < 1 or args.max_turns < 1 or (args.max_episodes is not None and args.max_episodes < 1):
        raise ValueError("invalid repeats/turn/episode limit")
    root = args.scenario_root.resolve()
    manifest = load_manifest(root)
    if manifest["benchmark_config_sha256"] != sha256_file(DEFAULT_CONFIG_PATH):
        raise ValueError("frozen benchmark config hash mismatch")
    corpus_path = root.parent / "corpus_manifest.json"
    corpus = read_json(corpus_path) if corpus_path.exists() else None
    split_hash = sha256_file(root / "manifest.json")
    if corpus and (corpus["split_manifest_sha256"].get(args.split) != split_hash or corpus["benchmark_config_sha256"] != manifest["benchmark_config_sha256"]):
        raise ValueError("corpus manifest hash mismatch")
    if args.split == "test" and not args.dry_run:
        if not args.freeze_manifest:
            raise ValueError("Test requires --freeze-manifest after the Dev pilot")
        freeze = read_json(args.freeze_manifest)
        if freeze.get("dataset_sha256") != corpus["dataset_sha256"] or freeze.get("prompt_sha256") != sha256_file(args.prompt_template) or freeze.get("benchmark_config_sha256") != manifest["benchmark_config_sha256"]:
            raise ValueError("freeze manifest does not match dataset/prompt/config")
    selected_scenarios = getattr(args, "scenario_ids", None)
    selected_conditions = getattr(args, "condition_ids", None)
    diagnostic = bool(selected_scenarios or selected_conditions)
    if diagnostic and args.split != "dev":
        raise ValueError("subset diagnostics are allowed only on Dev")
    entries = manifest["scenarios"]
    if selected_scenarios:
        if set(selected_scenarios) - {e["scenario_id"] for e in entries}:
            raise ValueError("unknown diagnostic scenario")
        entries = [e for e in entries if e["scenario_id"] in selected_scenarios]
    if selected_conditions:
        if set(selected_conditions) - {c["id"] for c in conditions}:
            raise ValueError("unknown diagnostic condition")
        conditions = [c for c in conditions if c["id"] in selected_conditions]
    tasks = ordered_tasks(entries, conditions, args.repeats)
    if args.dry_run:
        return {"split": args.split, "tasks": len(tasks), "conditions": [row["id"] for row in conditions], "dataset_sha256": corpus["dataset_sha256"] if corpus else split_hash}
    if args.max_cost_usd is not None and (args.max_cost_usd <= 0 or args.input_usd_per_million <= 0 or args.output_usd_per_million <= 0):
        raise ValueError("cost gate requires a positive limit and both positive input/output prices")
    if args.max_total_tokens is not None and args.max_total_tokens < 1:
        raise ValueError("token gate must be positive")
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    ledger_path = out / "episodes.jsonl"
    existing = load_ledger(ledger_path)
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT.parent, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    identity = {
        "provider": args.provider, "model": args.model, "api_mode": args.api_mode, "split": args.split,
        "prompt_sha256": sha256_file(args.prompt_template), "benchmark_config_sha256": manifest["benchmark_config_sha256"],
        "dataset_sha256": corpus["dataset_sha256"] if corpus else split_hash,
        "dataset_version": manifest["dataset_version"], "code_commit": commit, "source_sha256": source_identity(), "temperature": args.temperature,
        "task_order_version": "seeded-case-and-condition-v2",
        "run_scope": "dev_diagnostic_subset" if diagnostic else "full_matrix",
        "planned_tasks": [[c["id"], e["scenario_id"], r] for e, c, r in tasks],
        "max_turns": args.max_turns, "max_output_tokens": getattr(args, "max_output_tokens", 16384),
        "max_preview_calls": config["agent"]["max_preview_calls"],
        "max_submission_attempts": config["agent"]["max_submission_attempts"], "repeats": args.repeats,
        "conditions_sha256": sha256_file(EXPERIMENTS), "api_url_sha256": hashlib.sha256((args.url or os.getenv("POWERAGENTBENCH_OPENAI_URL") or "default").encode()).hexdigest(),
    }
    if campaign:
        identity.update(schema_version=2, campaign_id=campaign.campaign_id, pricing_sha256=campaign.pricing_sha256)
    run_path = out / "run.json"
    if run_path.exists():
        old = read_json(run_path)
        if any(old.get(key) != value for key, value in identity.items()):
            raise ValueError("run metadata mismatch; use a new output directory")
        run_id = old["run_id"]
    else:
        if existing:
            raise ValueError("episode ledger exists without run metadata")
        run_id = str(uuid.uuid4())
        run_path.write_text(json.dumps({**identity, "run_id": run_id}, indent=2) + "\n", encoding="utf-8")
    planned = {(c["id"], e["scenario_id"], r) for e, c, r in tasks}
    if set(existing) - planned or any(row["run_id"] != run_id for row in existing.values()):
        raise ValueError("ledger contains episodes from a different run")
    atomic_csv(out / "episodes.csv", list(existing.values()))
    client = None
    new = 0
    total_tokens = sum(int(row["total_tokens"] or 0) for row in existing.values() if row["status"] == "complete")
    cost = sum((int(row["input_tokens"] or 0) * args.input_usd_per_million + int(row["output_tokens"] or 0) * args.output_usd_per_million) / 1_000_000 for row in existing.values() if row["status"] == "complete") if args.max_cost_usd is not None else 0.0
    for entry, condition, repetition in tasks:
        key = condition["id"], entry["scenario_id"], repetition
        if key in existing and (existing[key]["status"] == "complete" or (existing[key]["status"] != "paused" and not args.retry_errors)):
            continue
        if args.max_episodes is not None and new >= args.max_episodes:
            break
        if args.max_total_tokens is not None and total_tokens >= args.max_total_tokens:
            break
        if args.max_cost_usd is not None and cost >= args.max_cost_usd:
            break
        if client is None:
            client = client_factory(args)
            if campaign:
                client.request_hook = campaign
        attempt = int(existing.get(key, {}).get("episode_attempt") or 1)
        if key in existing and existing[key]["status"] == "error" and args.retry_errors:
            attempt += 1
        episode_key = json.dumps(key, separators=(",", ":"))
        if campaign:
            client.request_context = {"campaign_id": campaign.campaign_id, "run_id": run_id,
                                      "episode_key": episode_key, "episode_attempt_id": f"{episode_key}:{attempt}"}
        row = {**{k: identity.get(k) for k in FIELDS}, "run_id": run_id, "condition": condition["id"],
               "domain_interface": int(condition["domain_specific_interface"]), "verification": int(condition["verification"]),
               "recovery": int(condition["recovery"]), "scenario_id": entry["scenario_id"],
               "difficulty": entry.get("difficulty"), "voltage_condition": entry["condition"], "repetition_index": repetition,
               "episode_attempt": attempt}
        checkpoint_path = (out / "checkpoints" / (hashlib.sha256(episode_key.encode()).hexdigest() + f"-{attempt}.json")) if campaign else None
        def event_sink(event):
            payload = {"schema_version": 1, "event_id": str(uuid.uuid4()), "timestamp": datetime.now(timezone.utc).isoformat(),
                       "run_id": run_id, "campaign_id": campaign.campaign_id if campaign else None,
                       "episode_key": episode_key, "episode_attempt": attempt, "scenario_id": entry["scenario_id"],
                       "condition": condition["id"], "repetition_index": repetition, **event}
            secret = args.api_key or os.getenv("POWERAGENTBENCH_OPENAI_API_KEY")
            if secret:
                payload = json.loads(json.dumps(payload).replace(secret, "[REDACTED]"))
            append_event(out / "events.jsonl", payload)
        started = time.monotonic()
        try:
            agent = LLMVoltageAgent(client, name=args.model, system_prompt=load_voltage_prompt(args.prompt_template),
                                    max_turns=args.max_turns, domain_interface=condition["domain_specific_interface"],
                                    verification=condition["verification"], recovery=condition["recovery"], scenario_root=root,
                                    checkpoint_path=checkpoint_path, event_sink=event_sink)
            output = agent.run(entry["scenario_id"])
            if output.paused:
                result = {"n_llm_turns": output.n_llm_turns, "latency_seconds": output.latency_seconds}
            else:
                event_sink({"event": "evaluation_started", "tool": "independent_evaluator"})
                result = score_voltage_output(entry["scenario_id"], output, scenario_root=root)
                event_sink({"event": "evaluation_finished", "success": result["success"], "valid_action": result["valid_action"],
                            "n_actual_power_flows": result["n_actual_power_flows"] - output.n_actual_power_flows,
                            "n_evaluator_calls": 1, "final_violation_magnitude": result.get("final_violation_magnitude")})
            row.update({field: result.get(field) for field in FIELDS if field in result})
            row["termination_reason"] = output.termination_reason
            row["latency_seconds"] = output.latency_seconds if campaign else time.monotonic() - started
            row["status"] = "paused" if output.paused else "complete"
            row["no_submission"] = int(not output.attempts)
            append_jsonl(out / "traces.jsonl", {"run_id": run_id, "key": key, "tool_log": output.tool_log, "attempts": output.attempts, "final_dispatch": output.dispatch})
        except Exception as exc:
            row["status"] = "error"
            row["error_type"] = type(exc).__name__
            row["termination_reason"] = "infrastructure_error"
            event_sink({"event": "episode_error", "error_type": type(exc).__name__})
            if checkpoint_path and checkpoint_path.exists():
                partial = read_json(checkpoint_path)
                row.update(n_llm_turns=partial["completed_turns"], n_submit_calls=len(partial["state"]["attempts"]),
                           n_preview_calls=partial["state"]["preview_calls"], n_actual_power_flows=partial["state"]["actual_power_flows"],
                           n_evaluator_calls=partial["state"]["evaluator_calls"], no_submission=int(not partial["state"]["attempts"]))
            row["latency_seconds"] = time.monotonic() - started
            secret = args.api_key or os.getenv("POWERAGENTBENCH_OPENAI_API_KEY")
            message = str(exc).replace(secret, "[REDACTED]") if secret else str(exc)
            append_jsonl(out / "errors.jsonl", {"run_id": run_id, "key": key, "error_type": type(exc).__name__, "error": message})
        if campaign:
            totals = ledger_totals(campaign.path, run_id=run_id, episode_key=episode_key)
            row.update(accounted_cost_cny=totals["accounted_cost_cny"], unknown_cost_requests=totals["unknown_requests"], n_api_requests=totals["request_count"],
                       cost_status="unknown" if totals["unknown_requests"] else "accounted_estimate_or_upper_bound")
        if key in existing:
            # Preserve the old failure and its audit log; only replace the active
            # record when explicitly asked to retry errors.
            append_jsonl(out / "retries.jsonl", {"run_id": run_id, "key": key, "previous": existing[key]})
            # A replacement ledger is written atomically, so retries remain resumable.
            existing[key] = row
            tmp = ledger_path.with_suffix(".tmp")
            tmp.write_text("".join(json.dumps(item, default=str) + "\n" for item in existing.values()), encoding="utf-8")
            os.replace(tmp, ledger_path)
        else:
            append_jsonl(ledger_path, row)
            existing[key] = row
        atomic_csv(out / "episodes.csv", list(existing.values()))
        new += 1
        if row["status"] == "complete":
            if args.max_total_tokens is not None and row.get("total_tokens") is None:
                raise ValueError("token usage unavailable: cannot enforce token gate")
            if args.max_cost_usd is not None and (row.get("input_tokens") is None or row.get("output_tokens") is None):
                raise ValueError("token usage unavailable: cannot enforce cost gate")
            total_tokens += row.get("total_tokens") or 0
            if args.max_cost_usd is not None:
                cost += (row["input_tokens"] * args.input_usd_per_million + row["output_tokens"] * args.output_usd_per_million) / 1_000_000
        elif row["status"] == "paused":
            break
        elif not args.continue_on_error:
            raise RuntimeError(f"episode {key} failed; see {out / 'errors.jsonl'}")
        if campaign and campaign.reason(client.request_context) in ("campaign_cost_limit", "smoke_cost_limit", "usage_unknown", "offpeak_pause"):
            break
    summary = {"run_id": run_id, "planned": len(tasks), "complete": sum(row["status"] == "complete" for row in existing.values()), "errors": sum(row["status"] == "error" for row in existing.values()), "paused": sum(row["status"] == "paused" for row in existing.values()), "remaining": len(tasks) - len(existing), "new": new, "total_tokens": total_tokens}
    if campaign:
        summary.update(campaign_id=campaign.campaign_id, **ledger_totals(campaign.path))
        if client is not None:
            reason = campaign.reason(client.request_context, timeout=args.timeout)
            summary["stop_reason"] = reason
            if reason == "offpeak_pause":
                summary["next_offpeak_at"] = campaign.next_offpeak(args.timeout)
    return summary


def main() -> None:
    load_env_file(Path(".env"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=["openai", "ollama"], default="openai")
    parser.add_argument("--model", default=os.getenv("POWERAGENTBENCH_OPENAI_MODEL"))
    parser.add_argument("--api-mode", choices=["chat", "responses"], default=os.getenv("POWERAGENTBENCH_OPENAI_API_MODE", "responses"))
    parser.add_argument("--split", choices=["dev", "test"], required=True)
    parser.add_argument("--scenario-root", type=Path, required=True, help="Evaluator-only split root")
    parser.add_argument("--scenario-id", dest="scenario_ids", action="append", help="Dev-only diagnostic subset; recorded in planned_tasks")
    parser.add_argument("--condition", dest="condition_ids", action="append", help="Dev-only diagnostic condition, e.g. I1-V0-R1")
    parser.add_argument("--output-dir", type=Path, default=Path("results/voltage_control"))
    parser.add_argument("--prompt-template", type=Path, default=PROMPT)
    parser.add_argument("--freeze-manifest", type=Path)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--max-output-tokens", type=int, default=16384)
    parser.add_argument("--max-episodes", type=int)
    parser.add_argument("--campaign-dir", type=Path, default=Path("results/voltage_control/cny_pilot_campaign"))
    parser.add_argument("--max-episode-cost-cny", default="0.20")
    parser.add_argument("--max-campaign-cost-cny", default="10")
    parser.add_argument("--pricing-file", type=Path, default=PRICING_PATH)
    parser.add_argument("--campaign-stage", choices=["smoke", "pilot"], default="smoke")
    parser.add_argument("--max-total-tokens", type=int)
    parser.add_argument("--max-cost-usd", type=float)
    parser.add_argument("--input-usd-per-million", type=float, default=0.0)
    parser.add_argument("--output-usd-per-million", type=float, default=0.0)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--url")
    parser.add_argument("--api-key")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.model:
        parser.error("set POWERAGENTBENCH_OPENAI_MODEL in .env or pass --model")
    print(json.dumps(run_matrix(args), indent=2))


if __name__ == "__main__":
    main()
