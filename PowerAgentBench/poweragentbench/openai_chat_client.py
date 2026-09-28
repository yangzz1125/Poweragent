"""OpenAI-compatible chat/completions adapter; reuses the Responses HTTP transport."""

from __future__ import annotations

from typing import Any

from poweragentbench.openai_client import OpenAIResponsesClient


class OpenAIChatClient(OpenAIResponsesClient):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("url", "https://api.openai.com/v1/chat/completions")
        kwargs.setdefault("structured_outputs", False)
        super().__init__(*args, **kwargs)

    def _payload(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.max_output_tokens is not None:
            payload["max_tokens"] = self.max_output_tokens
        return payload

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        choices = payload.get("choices") or []
        if not choices:
            return ""
        return str((choices[0].get("message") or {}).get("content") or "")
