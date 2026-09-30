"""Provider-agnostic helpers for parsing LLM JSON tool commands."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict


def _strip_wrappers(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"\s*```$", "", text).strip()
    return text


def _first_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for idx, ch in enumerate(text[start:], start=start):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return None


def _normalize_command(obj: Dict[str, Any]) -> Dict[str, Any]:
    if "tool" in obj:
        obj.setdefault("args", {})
        return obj
    if "function" in obj and isinstance(obj["function"], dict):
        fn = obj["function"]
        return {"tool": fn.get("name", ""), "args": fn.get("arguments", {}) or {}}
    if "name" in obj and "arguments" in obj:
        return {"tool": obj.get("name", ""), "args": obj.get("arguments", {}) or {}}
    if "tool_call" in obj and isinstance(obj["tool_call"], dict):
        tc = obj["tool_call"]
        return {"tool": tc.get("tool", tc.get("name", "")), "args": tc.get("args", tc.get("arguments", {})) or {}}
    raise ValueError("JSON object did not contain a tool command")


def parse_json_command(text: str) -> Dict[str, Any]:
    cleaned = _strip_wrappers(text)
    if not cleaned:
        raise ValueError("empty model response")
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        js = _first_json_object(cleaned)
        if js is None:
            raise ValueError(f"model response did not contain JSON: {cleaned[:300]}")
        obj = json.loads(js)
    if not isinstance(obj, dict):
        raise ValueError("tool command must be a JSON object")
    return _normalize_command(obj)


def load_prompt_template(path: str | Path | None) -> str | None:
    if path is None:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return str(payload.get("system", "")).strip() or None
    return str(payload).strip() or None
