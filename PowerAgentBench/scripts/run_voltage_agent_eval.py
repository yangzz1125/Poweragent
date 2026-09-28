from __future__ import annotations

import argparse
import csv
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from poweragentbench.llm_agent_adapter import parse_json_command
from poweragentbench.ollama_client import OllamaGenerateClient
from poweragentbench.openai_client import OpenAIResponsesClient
from poweragentbench.openai_chat_client import OpenAIChatClient
from poweragentbench.voltage_agentic import (
    LLMVoltageAgent,
    aggregate_voltage_metrics,
    load_voltage_prompt,
    score_voltage_output,
)
from poweragentbench.voltage_case import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_SCENARIO_ROOT,
    scenario_ids,
    sha256_file,
)

DEFAULT_PROMPT = Path(
    "benchmarks/steady/voltage_control/prompts/voltage_agent_prompt.json"
)


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    flat = [
        {
            key: value
            for key, value in row.items()
            if not isinstance(value, (dict, list))
        }
        for row in rows
    ]
    keys = list(dict.fromkeys(key for row in flat for key in row))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(flat)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def parse_args() -> argparse.Namespace:
    load_env_file(Path(".env"))
    load_env_file(Path("benchmarks/steady/level_2/.env"))
    parser = argparse.ArgumentParser(
        description="Evaluate an LLM on IEEE 33-bus BESS voltage correction."
    )
    parser.add_argument("--provider", choices=["openai", "ollama"], required=True)
    parser.add_argument("--model", default=os.getenv("POWERAGENTBENCH_OPENAI_MODEL"))
    parser.add_argument("--api-mode", choices=["chat", "responses"], default=os.getenv("POWERAGENTBENCH_OPENAI_API_MODE", "responses"))
    parser.add_argument("--url")
    parser.add_argument("--api-key")
    parser.add_argument("--scenario-root", type=Path, default=DEFAULT_SCENARIO_ROOT)
    parser.add_argument("--prompt-template", type=Path, default=DEFAULT_PROMPT)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("results/voltage_control")
    )
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--max-output-tokens", type=int, default=16384)
    parser.add_argument("--reasoning-effort", choices=["none", "low", "high", "max"])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument(
        "--domain-interface", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--verification", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--recovery", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--continue-on-error", action="store_true")
    args = parser.parse_args()
    if not args.model:
        parser.error("set POWERAGENTBENCH_OPENAI_MODEL in .env or pass --model")
    return args


def model_request_settings(args: argparse.Namespace) -> dict[str, Any]:
    """Credential-free effective request settings, shared by execution and freeze."""
    mode = getattr(args, "api_mode", "responses")
    if args.provider == "ollama":
        if getattr(args, "reasoning_effort", None) is not None:
            raise ValueError("--reasoning-effort currently requires Responses")
        return {"provider": "ollama", "model": args.model, "temperature": args.temperature,
                "url": args.url or os.getenv("POWERAGENTBENCH_OLLAMA_URL"), "timeout": args.timeout,
                "think": False, "schema_format": True}
    url = (args.url or os.getenv("POWERAGENTBENCH_OPENAI_URL") or "https://api.openai.com/v1").rstrip("/")
    path = "chat/completions" if mode == "chat" else "responses"
    if url.endswith(("/chat/completions", "/responses")):
        if not url.endswith("/" + path):
            raise ValueError("API URL endpoint does not match --api-mode")
    else:
        url += "/" + path
    max_output_tokens = getattr(args, "max_output_tokens", 16384)
    if isinstance(max_output_tokens, bool) or not isinstance(max_output_tokens, int) or max_output_tokens < 1:
        raise ValueError("max_output_tokens must be a positive integer")
    effort = getattr(args, "reasoning_effort", None)
    if effort not in (None, "none", "low", "high", "max"):
        raise ValueError("unsupported reasoning effort")
    if effort is not None and mode != "responses":
        raise ValueError("--reasoning-effort currently requires Responses")
    deepseek = urlparse(url).hostname == "api.deepseek.com"
    if deepseek and mode == "responses" and effort is None:
        effort = "high"  # Explicitly preserve the documented DeepSeek default.
    return {"provider": "openai", "model": args.model, "api_mode": mode, "url": url,
            "temperature": args.temperature, "timeout": args.timeout, "max_output_tokens": max_output_tokens,
            "reasoning_effort": effort, "structured_outputs": mode == "responses",
            "max_retries": 3, "retry_backoff": 2.0,
            "temperature_policy": "ignored_in_thinking_mode" if deepseek and effort not in (None, "none") else "requested"}


def make_client(args: argparse.Namespace):
    settings = model_request_settings(args)
    if args.provider == "ollama":
        url = args.url or os.getenv("POWERAGENTBENCH_OLLAMA_URL")
        if not url:
            raise SystemExit("Ollama requires --url or POWERAGENTBENCH_OLLAMA_URL")
        return OllamaGenerateClient(
            url=url,
            model=args.model,
            temperature=args.temperature,
            timeout=args.timeout,
            schema_format=True,
            think=False,
        )
    api_key = args.api_key or os.getenv("POWERAGENTBENCH_OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OpenAI requires --api-key or POWERAGENTBENCH_OPENAI_API_KEY")
    client_class = OpenAIChatClient if settings["api_mode"] == "chat" else OpenAIResponsesClient
    return client_class(api_key=api_key, **{key: settings[key] for key in (
        "max_output_tokens", "model", "url", "temperature", "timeout", "reasoning_effort",
        "structured_outputs", "max_retries", "retry_backoff")})


def main() -> None:
    args = parse_args()
    client = make_client(args)
    prompt = load_voltage_prompt(args.prompt_template)
    condition = (
        f"I{int(args.domain_interface)}-V{int(args.verification)}-R{int(args.recovery)}"
    )
    agent_name = f"{args.model}-{args.provider}-{condition}"
    prefix = slug(agent_name)
    rows: list[dict[str, Any]] = []
    tool_log_path = args.output_dir / f"{prefix}_tool_logs.jsonl"
    attempt_path = args.output_dir / f"{prefix}_attempts.jsonl"
    debug_path = args.output_dir / f"{prefix}_api_debug.jsonl"
    error_path = args.output_dir / f"{prefix}_errors.jsonl"
    prompt_hash = sha256_file(args.prompt_template)
    config_hash = sha256_file(DEFAULT_CONFIG_PATH)

    probe = client(
        [
            {"role": "system", "content": "Return exactly one JSON command."},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "allowed_tools": ["case_summary"],
                        "example": {"tool": "case_summary", "args": {}},
                    }
                ),
            },
        ]
    )
    parse_json_command(probe)

    for repetition_index in range(args.repeats):
        for scenario_id in scenario_ids(args.scenario_root):
            try:
                agent = LLMVoltageAgent(
                    client,
                    name=agent_name,
                    system_prompt=prompt,
                    max_turns=args.max_turns,
                    domain_interface=args.domain_interface,
                    verification=args.verification,
                    recovery=args.recovery,
                    scenario_root=args.scenario_root,
                )
                output = agent.run(scenario_id)
                metrics = score_voltage_output(
                    scenario_id, output, scenario_root=args.scenario_root
                )
                run_metadata = {
                    "model": args.model,
                    "provider": args.provider,
                    "condition": condition,
                    "repetition_index": repetition_index,
                    "prompt_sha256": prompt_hash,
                    "benchmark_config_sha256": config_hash,
                    "max_output_tokens": args.max_output_tokens,
                    "reasoning_effort": model_request_settings(args).get("reasoning_effort"),
                    "temperature_policy": model_request_settings(args).get("temperature_policy"),
                }
                metrics.update(
                    {
                        **run_metadata,
                        "domain_specific_interface": float(args.domain_interface),
                        "verification_enabled": float(args.verification),
                        "recovery_enabled": float(args.recovery),
                    }
                )
                rows.append(metrics)
                append_jsonl(
                    tool_log_path,
                    {
                        **run_metadata,
                        "scenario_id": scenario_id,
                        "tool_log": output.tool_log,
                    },
                )
                append_jsonl(
                    attempt_path,
                    {
                        **run_metadata,
                        "scenario_id": scenario_id,
                        "attempts": output.attempts,
                        "final_dispatch": output.dispatch,
                    },
                )
                debug = (
                    client.sanitized_debug()
                    if hasattr(client, "sanitized_debug")
                    else {
                        "model": args.model,
                        "provider": args.provider,
                        "response_received": getattr(client, "last_debug", None)
                        is not None,
                    }
                )
                append_jsonl(
                    debug_path,
                    {**run_metadata, "scenario_id": scenario_id, "debug": debug},
                )
                write_csv(args.output_dir / f"{prefix}_per_case.csv", rows)
            except Exception as exc:
                append_jsonl(
                    error_path,
                    {
                        "scenario_id": scenario_id,
                        "repetition_index": repetition_index,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                if not args.continue_on_error:
                    raise

    if rows:
        summary = aggregate_voltage_metrics(rows)
        summary.update(
            {
                "model": args.model,
                "provider": args.provider,
                "condition": condition,
                "completed_runs": len(rows),
                "requested_runs": len(scenario_ids(args.scenario_root)) * args.repeats,
                "prompt_sha256": prompt_hash,
                "benchmark_config_sha256": config_hash,
            }
        )
        write_csv(args.output_dir / f"{prefix}_summary.csv", [summary])
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
