import json
from urllib.error import HTTPError
from io import BytesIO
from types import SimpleNamespace

import pytest

from poweragentbench.openai_chat_client import OpenAIChatClient
from poweragentbench.openai_client import OpenAIResponsesClient
from poweragentbench.voltage_agentic import LLMVoltageAgent
from scripts.run_voltage_agent_eval import make_client


def test_deepseek_base_url_selects_endpoint(monkeypatch):
    monkeypatch.setenv("POWERAGENTBENCH_OPENAI_URL", "https://api.deepseek.com")
    monkeypatch.setenv("POWERAGENTBENCH_OPENAI_API_KEY", "test")
    args = SimpleNamespace(provider="openai", api_mode="chat", model="deepseek-flash", api_key=None,
                           url=None, temperature=0, timeout=10)
    assert make_client(args).url == "https://api.deepseek.com/chat/completions"
    args.api_mode = "responses"
    assert make_client(args).url == "https://api.deepseek.com/responses"
    assert make_client(args)._payload([])["max_output_tokens"] == 16384
    args.max_output_tokens = 8192
    assert make_client(args)._payload([])["max_output_tokens"] == 8192
    args.max_output_tokens = 0
    with pytest.raises(ValueError, match="positive integer"):
        make_client(args)
    args.max_output_tokens = 16384
    args.url = "https://api.deepseek.com/chat/completions"
    with pytest.raises(ValueError, match="does not match"):
        make_client(args)


def test_chat_payload_and_usage():
    client = OpenAIChatClient(api_key="test", model="local", url="http://localhost/v1/chat/completions", temperature=0)
    client._post_once = lambda payload: {"choices": [{"message": {"content": json.dumps({"tool": "submit", "args": {"dispatch": []}})}}], "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}}
    assert client._payload([{"role": "user", "content": "hello"}])["temperature"] == 0
    assert "messages" in client._payload([{"role": "user", "content": "hello"}])
    assert client([{"role": "user", "content": "hello"}])
    assert client.sanitized_debug()["usage"]["total_tokens"] == 20


def test_responses_payload_text_and_usage():
    client = OpenAIResponsesClient(api_key="test", model="deepseek-flash", temperature=0)
    assert client._payload([{"role": "user", "content": "hello"}])["store"] is False
    client._post_once = lambda _: {"output": [{"type": "message", "content": [{"type": "output_text", "text": '{"tool":"submit","args":{"dispatch":[]}}'}]}], "usage": {"input_tokens": 11, "output_tokens": 4, "total_tokens": 15}}
    assert 'submit' in client([{"role": "user", "content": "hello"}])
    assert client.sanitized_debug()["usage"]["total_tokens"] == 15


def test_provider_truncation_status_is_logged_separately_from_parse_error():
    requests, events = [], []
    client = OpenAIResponsesClient(api_key="test", model="deepseek-flash", max_output_tokens=16384, request_hook=requests.append)
    client._post_once = lambda _: {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
                                  "output": [], "usage": {"input_tokens": 10, "output_tokens": 16384}}
    result = LLMVoltageAgent(client, name="truncation-check", max_turns=1, event_sink=events.append).run("V0001")
    assert requests[-1]["response_status"] == "incomplete"
    assert requests[-1]["incomplete_reason"] == "max_output_tokens"
    assert requests[-1]["max_output_tokens_requested"] == 16384
    assert result.tool_log[0]["tool"] == "output_truncated"
    assert any(e["event"] == "output_truncated" for e in events)
    assert not any(e["event"] == "parse_error" for e in events)
    assert OpenAIResponsesClient.completion_metadata({"usage": {"output_tokens": 16384}})["incomplete_reason"] is None


def test_unsupported_temperature_fails_instead_of_silent_retry():
    client = OpenAIResponsesClient(api_key="test", temperature=0, max_retries=0)
    def fail(_payload):
        raise HTTPError("http://localhost", 400, "temperature unsupported", {}, BytesIO(b"temperature unsupported"))
    client._post_once = fail
    with pytest.raises(RuntimeError, match="400"):
        client([{"role": "user", "content": "hello"}])
    assert client.temperature == 0


def test_per_turn_usage_not_last_turn_only():
    class Fake:
        def __init__(self):
            self.calls = 0
            self.last_debug = None
            self.retry_count_last_call = 0

        def __call__(self, _messages):
            self.calls += 1
            self.last_debug = {"usage": {"prompt_tokens": 10 * self.calls, "completion_tokens": 2, "total_tokens": 10 * self.calls + 2}}
            return json.dumps({"tool": "submit", "args": {"dispatch": []}})

    output = LLMVoltageAgent(Fake(), name="fake", max_turns=2, recovery=True).run("V0001")
    assert output.n_llm_turns == 2
    assert (output.input_tokens, output.output_tokens, output.total_tokens) == (30, 4, 34)
    assert not output.usage_unavailable
