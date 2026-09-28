"""OpenAI Responses API client used by the PowerAgentBench-SS LLM adapter.

This client intentionally keeps deployment details outside the code. API keys,
model names, reasoning settings, timeouts, and output limits can be supplied by
command-line flags or environment variables loaded by the runner script.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List

Message = Dict[str, str]

TOOL_COMMAND_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "tool": {
            "type": "string",
            "description": "One public benchmark tool name.",
        },
        "args": {
            "type": "object",
            "description": "Arguments for the selected tool.",
            "additionalProperties": True,
        },
    },
    "required": ["tool", "args"],
    "additionalProperties": False,
}

TRANSIENT_HTTP_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class OpenAIResponsesClient:
    """Small dependency-free callable client for the OpenAI Responses API.

    The class follows the same callable interface as OllamaGenerateClient:
        client(messages: list[dict[str, str]]) -> str

    It returns the model's visible text output only. Debug logs should use
    sanitized_debug() so API keys, raw outputs, and model-internal reasoning are
    not written to benchmark artifacts.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5.5",
        url: str = "https://api.openai.com/v1/responses",
        temperature: float | None = None,
        max_output_tokens: int | None = 4096,
        structured_outputs: bool = True,
        reasoning_effort: str | None = None,
        reasoning_summary: str | None = None,
        timeout: float = 300.0,
        max_retries: int = 3,
        retry_backoff: float = 2.0,
        request_hook: Callable[[dict], None] | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAI API key is required.")
        self.api_key = api_key
        self.model = model
        self.url = url
        self.temperature = None if temperature is None else float(temperature)
        self.max_output_tokens = None if max_output_tokens is None else int(max_output_tokens)
        self.structured_outputs = bool(structured_outputs)
        self.reasoning_effort = reasoning_effort or None
        self.reasoning_summary = reasoning_summary or None
        self.timeout = float(timeout)
        self.max_retries = max(0, int(max_retries))
        self.retry_backoff = max(0.0, float(retry_backoff))
        self.last_debug: Dict[str, Any] | None = None
        self.last_client_warning: str | None = None
        self.last_error: str | None = None
        self.retry_count_last_call: int = 0
        self.request_hook = request_hook
        self.request_context: Dict[str, Any] = {}
        self.last_request_id: str | None = None

    def __call__(self, messages: List[Message]) -> str:
        payload = self._payload(messages)
        out = self._post(payload)
        return self._extract_text(out)

    def _payload(self, messages: List[Message]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self.model,
            "input": [
                {
                    "role": m["role"],
                    "content": m["content"],
                }
                for m in messages
            ],
            "store": False,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.max_output_tokens is not None:
            payload["max_output_tokens"] = self.max_output_tokens
        if self.structured_outputs:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "poweragentbench_tool_command",
                    "description": "A single PowerAgentBench public tool command.",
                    "schema": TOOL_COMMAND_SCHEMA,
                    "strict": False,
                }
            }
        else:
            payload["text"] = {"format": {"type": "json_object"}}
        reasoning: Dict[str, Any] = {}
        if self.reasoning_effort:
            reasoning["effort"] = self.reasoning_effort
        if self.reasoning_summary:
            reasoning["summary"] = self.reasoning_summary
        if reasoning:
            payload["reasoning"] = reasoning
        return payload

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.retry_count_last_call = 0
        self.last_error = None
        self.last_debug = None
        self.last_request_id = None
        for attempt in range(self.max_retries + 1):
            self.retry_count_last_call = attempt
            started_at = datetime.now(timezone.utc).isoformat()
            started = time.monotonic()
            request_id = str(uuid.uuid4())
            self.last_request_id = request_id
            context_keys = ("campaign_id", "run_id", "episode_key", "episode_attempt_id", "turn")
            base = {"request_id": request_id, "started_at": started_at, "retry_index": attempt,
                    "model": self.model, "context": {k: self.request_context[k] for k in context_keys if k in self.request_context},
                    "max_output_tokens_requested": payload.get("max_output_tokens", payload.get("max_tokens")),
                    "temperature_requested": payload.get("temperature"),
                    "reasoning_effort_requested": (payload.get("reasoning") or {}).get("effort", "provider_default")}
            # Hooks run outside the HTTP exception handler: accounting/policy
            # failures must not be mistaken for transport errors and retried.
            if self.request_hook:
                self.request_hook({**base, "event": "started", "timeout_seconds": self.timeout})
            failure = None
            try:
                out = self._post_once(payload)
                if not isinstance(out, dict):
                    raise ValueError("API response must be an object")
            except Exception as exc:
                failure = exc
            ended_at = datetime.now(timezone.utc).isoformat()
            terminal = {**base, "ended_at": ended_at, "latency_seconds": time.monotonic() - started}
            if failure is None:
                self.last_debug = out
                if self.request_hook:
                    visible = self._extract_text(out).replace(self.api_key, "[REDACTED]")
                    self.request_hook({**terminal, "event": "finished", "http_status": 200,
                                       "response_id": out.get("id"), "response_model": out.get("model"),
                                       **self.completion_metadata(out),
                                       "usage": out.get("usage"), "visible_text": visible})
                return out
            status = failure.code if isinstance(failure, urllib.error.HTTPError) else None
            self.last_error = f"HTTP {status}" if status is not None else type(failure).__name__
            if self.request_hook:
                self.request_hook({**terminal, "event": "error", "http_status": status,
                                   "error_type": type(failure).__name__, "usage": None})
            transient = status in TRANSIENT_HTTP_STATUS if status is not None else isinstance(failure, (TimeoutError, ConnectionError, urllib.error.URLError))
            if not transient or attempt >= self.max_retries:
                raise RuntimeError(f"OpenAI API request failed: {self.last_error}") from failure
            self._sleep_before_retry(attempt)
        raise RuntimeError("API retry loop exhausted")

    def _post_once(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _sleep_before_retry(self, attempt: int) -> None:
        if self.retry_backoff <= 0:
            return
        delay = self.retry_backoff * (2 ** attempt)
        time.sleep(delay)

    @staticmethod
    def completion_metadata(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Provider-declared stop status only; never infer truncation from token count."""
        status = payload.get("status")
        details = payload.get("incomplete_details")
        reason = details.get("reason") if isinstance(details, dict) else None
        choices = payload.get("choices") or []
        finish = choices[0].get("finish_reason") if choices and isinstance(choices[0], dict) else None
        return {
            "response_status": status if status in ("completed", "incomplete", "failed", "cancelled", "queued", "in_progress") else "unknown",
            "incomplete_reason": reason if reason in ("max_output_tokens", "content_filter") else ("unknown" if reason is not None else None),
            "finish_reason": finish if finish in ("stop", "length", "tool_calls", "function_call", "content_filter") else ("unknown" if finish is not None else None),
        }

    @staticmethod
    def _extract_text(payload: Dict[str, Any]) -> str:
        if isinstance(payload.get("output_text"), str):
            return payload["output_text"]

        chunks: List[str] = []
        for item in payload.get("output", []) or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "message":
                for content in item.get("content", []) or []:
                    if isinstance(content, dict) and content.get("type") == "output_text":
                        text = content.get("text")
                        if isinstance(text, str):
                            chunks.append(text)
            elif item.get("type") == "output_text":
                text = item.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "\n".join(chunks).strip()

    def sanitized_debug(self) -> Dict[str, Any]:
        """Return API diagnostics without raw output text or reasoning content."""
        raw = self.last_debug or {}
        out: Dict[str, Any] = {}
        for key in (
            "id",
            "model",
            "created_at",
            "status",
            "error",
            "incomplete_details",
        ):
            if key in raw:
                out[key] = raw[key]
        usage = raw.get("usage")
        if isinstance(usage, dict):
            out["usage"] = usage
        out["output_text_chars"] = len(self._extract_text(raw))
        out["structured_outputs"] = self.structured_outputs
        out["temperature"] = self.temperature
        out["max_output_tokens"] = self.max_output_tokens
        out["reasoning_effort"] = self.reasoning_effort
        out["reasoning_summary"] = self.reasoning_summary
        out["timeout"] = self.timeout
        out["max_retries"] = self.max_retries
        out["retry_backoff"] = self.retry_backoff
        out["retry_count_last_call"] = self.retry_count_last_call
        if self.last_client_warning:
            out["client_warning"] = self.last_client_warning
        if self.last_error:
            out["last_error"] = self.last_error
        return out
