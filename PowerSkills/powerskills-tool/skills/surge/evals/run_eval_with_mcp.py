#!/usr/bin/env python3
"""Surge-specific skill-trigger eval with the surge MCP server live.

Differences from skill-creator's run_eval.py:
  * Passes --mcp-config + --dangerously-skip-permissions to `claude -p`
    so surge MCP tools are visible to the subprocess.
  * Counts `mcp__surge__*` calls as valid triggers alongside Skill/Read.

Prerequisite: copy evals/mcp_config.example.json to evals/mcp_config.json
and fill in the local Python interpreter and surge_mcp.py paths.
"""

from __future__ import annotations

import argparse
import json
import os
import select
import subprocess
import sys
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# skill-creator lives as a sibling skill in the same PowerSkills tree.
# This file is at PowerSkills/surge/evals/run_eval_with_mcp.py, so walk up
# three levels to reach PowerSkills/ and then into skill-creator/.
SKILL_CREATOR = Path(__file__).resolve().parents[2] / "skill-creator"
sys.path.insert(0, str(SKILL_CREATOR))
from scripts.utils import parse_skill_md  # noqa: E402

MCP_CONFIG = Path(__file__).parent / "mcp_config.json"
MCP_CONFIG_EXAMPLE = Path(__file__).parent / "mcp_config.example.json"


def find_project_root() -> Path:
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / ".claude").is_dir():
            return parent
    return current


def run_single_query(
    query: str,
    skill_name: str,
    skill_description: str,
    timeout: int,
    project_root: str,
    model: str | None,
) -> bool:
    unique_id = uuid.uuid4().hex[:8]
    clean_name = f"{skill_name}-skill-{unique_id}"
    project_commands_dir = Path(project_root) / ".claude" / "commands"
    command_file = project_commands_dir / f"{clean_name}.md"

    try:
        project_commands_dir.mkdir(parents=True, exist_ok=True)
        indented_desc = "\n  ".join(skill_description.split("\n"))
        command_file.write_text(
            f"---\ndescription: |\n  {indented_desc}\n---\n\n"
            f"# {skill_name}\n\nThis skill handles: {skill_description}\n"
        )

        cmd = [
            "claude",
            "-p", query,
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--mcp-config", str(MCP_CONFIG),
            "--dangerously-skip-permissions",
        ]
        if model:
            cmd.extend(["--model", model])

        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=project_root,
            env=env,
        )

        triggered = False
        start_time = time.time()
        buffer = ""
        pending_tool_name: str | None = None
        accumulated_json = ""

        def is_accepted_tool(name: str) -> bool:
            return name in ("Skill", "Read") or name.startswith("mcp__surge__")

        try:
            while time.time() - start_time < timeout:
                if process.poll() is not None:
                    remaining = process.stdout.read()
                    if remaining:
                        buffer += remaining.decode("utf-8", errors="replace")
                    break

                ready, _, _ = select.select([process.stdout], [], [], 1.0)
                if not ready:
                    continue

                chunk = os.read(process.stdout.fileno(), 8192)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if event.get("type") == "stream_event":
                        se = event.get("event", {})
                        se_type = se.get("type", "")

                        if se_type == "content_block_start":
                            cb = se.get("content_block", {})
                            if cb.get("type") == "tool_use":
                                tool_name = cb.get("name", "")
                                if tool_name.startswith("mcp__surge__"):
                                    return True
                                if tool_name in ("Skill", "Read", "ToolSearch"):
                                    pending_tool_name = tool_name
                                    accumulated_json = ""
                                else:
                                    return False

                        elif se_type == "content_block_delta" and pending_tool_name:
                            delta = se.get("delta", {})
                            if delta.get("type") == "input_json_delta":
                                accumulated_json += delta.get("partial_json", "")
                                if clean_name in accumulated_json:
                                    return True
                                if "mcp__surge__" in accumulated_json:
                                    return True

                        elif se_type in ("content_block_stop", "message_stop"):
                            if pending_tool_name == "ToolSearch":
                                if "mcp__surge__" in accumulated_json:
                                    return True
                                pending_tool_name = None
                                accumulated_json = ""
                                continue
                            if pending_tool_name:
                                return clean_name in accumulated_json
                            if se_type == "message_stop":
                                continue

                    elif event.get("type") == "assistant":
                        message = event.get("message", {})
                        for content_item in message.get("content", []):
                            if content_item.get("type") != "tool_use":
                                continue
                            tool_name = content_item.get("name", "")
                            tool_input = content_item.get("input", {})
                            if tool_name.startswith("mcp__surge__"):
                                return True
                            if tool_name == "Skill" and clean_name in tool_input.get("skill", ""):
                                return True
                            if tool_name == "Read" and clean_name in tool_input.get("file_path", ""):
                                return True
                            if tool_name == "ToolSearch":
                                q = tool_input.get("query", "") if isinstance(tool_input, dict) else ""
                                if "mcp__surge__" in q:
                                    return True
                                continue
                            return False

                    elif event.get("type") == "result":
                        return triggered
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()

        return triggered
    finally:
        if command_file.exists():
            command_file.unlink()


def run_eval(eval_set, skill_name, description, num_workers, timeout,
             project_root, runs_per_query, trigger_threshold, model):
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        future_to_info = {}
        for item in eval_set:
            for _ in range(runs_per_query):
                fut = executor.submit(
                    run_single_query, item["query"], skill_name, description,
                    timeout, str(project_root), model,
                )
                future_to_info[fut] = item

        query_triggers: dict[str, list[bool]] = {}
        query_items: dict[str, dict] = {}
        for fut in as_completed(future_to_info):
            item = future_to_info[fut]
            query_items[item["query"]] = item
            query_triggers.setdefault(item["query"], [])
            try:
                query_triggers[item["query"]].append(fut.result())
            except Exception as e:
                print(f"Warning: query failed: {e}", file=sys.stderr)
                query_triggers[item["query"]].append(False)

    results = []
    for query, triggers in query_triggers.items():
        item = query_items[query]
        rate = sum(triggers) / len(triggers)
        should_trigger = item["should_trigger"]
        did_pass = (rate >= trigger_threshold) if should_trigger else (rate < trigger_threshold)
        results.append({
            "query": query,
            "should_trigger": should_trigger,
            "trigger_rate": rate,
            "triggers": sum(triggers),
            "runs": len(triggers),
            "pass": did_pass,
        })

    passed = sum(1 for r in results if r["pass"])
    return {
        "skill_name": skill_name,
        "description": description,
        "results": results,
        "summary": {"total": len(results), "passed": passed, "failed": len(results) - passed},
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--eval-set", required=True)
    p.add_argument("--skill-path", required=True)
    p.add_argument("--description", default=None)
    p.add_argument("--num-workers", type=int, default=10)
    p.add_argument("--timeout", type=int, default=60)
    p.add_argument("--runs-per-query", type=int, default=3)
    p.add_argument("--trigger-threshold", type=float, default=0.5)
    p.add_argument("--model", default=None)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    if not MCP_CONFIG.exists():
        print(
            f"error: {MCP_CONFIG} not found. Copy {MCP_CONFIG_EXAMPLE.name} to "
            f"mcp_config.json and edit the two paths to match your local checkout.",
            file=sys.stderr,
        )
        sys.exit(2)

    eval_set = json.loads(Path(args.eval_set).read_text())
    skill_path = Path(args.skill_path)
    name, original_description, _ = parse_skill_md(skill_path)
    description = args.description or original_description
    project_root = find_project_root()

    if args.verbose:
        print(f"Project root: {project_root}", file=sys.stderr)
        print(f"MCP config: {MCP_CONFIG}", file=sys.stderr)
        print(f"Description ({len(description)} chars): {description}", file=sys.stderr)

    out = run_eval(
        eval_set=eval_set, skill_name=name, description=description,
        num_workers=args.num_workers, timeout=args.timeout,
        project_root=project_root, runs_per_query=args.runs_per_query,
        trigger_threshold=args.trigger_threshold, model=args.model,
    )

    if args.verbose:
        s = out["summary"]
        print(f"Results: {s['passed']}/{s['total']} passed", file=sys.stderr)
        for r in out["results"]:
            status = "PASS" if r["pass"] else "FAIL"
            print(f"  [{status}] rate={r['triggers']}/{r['runs']} expected={r['should_trigger']}: {r['query'][:70]}", file=sys.stderr)

    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
