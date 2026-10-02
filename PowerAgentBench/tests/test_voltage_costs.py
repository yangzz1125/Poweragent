import json
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from urllib.error import HTTPError

import pytest

from poweragentbench.openai_client import OpenAIResponsesClient
from poweragentbench.voltage_costs import (
    PRICING_PATH, RequestRecorder, estimate_cost, ledger_totals, normalize_usage,
    peak_during, read_events,
)

PRICE = json.loads(PRICING_PATH.read_text(encoding="utf-8"))
START = datetime.fromisoformat("2026-09-28T18:10:00+08:00")


def test_cost_decimal_cache_and_missing_values():
    usage = {"input_tokens": 1000000, "input_tokens_details": {"cached_tokens": 250000},
             "output_tokens": 100000, "output_tokens_details": {"reasoning_tokens": 50000}}
    cost = estimate_cost(usage, START, START, PRICE)
    assert Decimal(cost["cost_cny"]) == Decimal("1.155")
    assert cost["cost_status"] == "estimated"
    assert normalize_usage({"prompt_tokens": 100, "completion_tokens": 10, "prompt_cache_hit_tokens": 30, "prompt_cache_miss_tokens": 70})["cached_input_tokens"] == 30
    upper = estimate_cost({"input_tokens": 1000000, "output_tokens": 0}, START, START, PRICE)
    assert upper["cost_cny"] is None and Decimal(upper["cost_upper_bound_cny"]) == 1
    assert estimate_cost(None, START, START, PRICE)["cost_status"] == "unknown"
    zero = estimate_cost({"input_tokens": 0, "output_tokens": 0}, START, START, PRICE)
    assert Decimal(zero["cost_cny"]) == 0


@pytest.mark.parametrize("usage", [
    {"input_tokens": -1, "output_tokens": 1},
    {"input_tokens": True, "output_tokens": 1},
    {"input_tokens": 10.0, "output_tokens": 1},
    {"input_tokens": 10, "output_tokens": 1, "total_tokens": 99},
    {"input_tokens": 10, "prompt_tokens": 11, "output_tokens": 1},
    {"input_tokens": 10, "output_tokens": 1, "input_tokens_details": {"cached_tokens": 11}},
    {"input_tokens": 10, "output_tokens": 1, "prompt_cache_hit_tokens": 2, "prompt_cache_miss_tokens": 9},
])
def test_bad_usage_is_unknown_never_zero(usage):
    assert estimate_cost(usage, START, START, PRICE)["cost_status"] == "unknown"


@pytest.mark.parametrize("stamp,peak", [
    ("2026-09-28T08:59:00+08:00", False), ("2026-09-28T09:00:00+08:00", True),
    ("2026-09-28T12:00:00+08:00", False), ("2026-09-28T14:00:00+08:00", True),
    ("2026-09-28T18:00:00+08:00", False), ("2026-10-03T10:00:00+08:00", False),
    # Statutory holiday listed in the pricing schedule is off-peak; the next weekday is peak again.
    ("2026-10-01T10:00:00+08:00", False), ("2026-10-02T10:00:00+08:00", False),
    ("2026-10-05T10:00:00+08:00", False), ("2026-10-07T15:00:00+08:00", False),
    ("2026-10-08T10:00:00+08:00", True),
])
def test_price_windows(stamp, peak):
    moment = datetime.fromisoformat(stamp)
    assert peak_during(moment, moment, PRICE) == peak
    assert peak_during(moment.astimezone(timezone.utc), moment, PRICE) == peak


def test_cross_window_is_upper_bound():
    cost = estimate_cost({"input_tokens": 1000000, "output_tokens": 0, "input_tokens_details": {"cached_tokens": 0}},
                         datetime.fromisoformat("2026-09-28T08:59:00+08:00"), datetime.fromisoformat("2026-09-28T09:01:00+08:00"), PRICE)
    assert cost["cost_status"] == "upper_bound"
    assert Decimal(cost["cost_upper_bound_cny"]) == 2


def test_request_events_retries_and_no_secret(tmp_path):
    path = tmp_path / "requests.jsonl"
    client = OpenAIResponsesClient(api_key="secret-test", model="deepseek-flash", retry_backoff=0,
                                   request_hook=RequestRecorder(path))
    client.request_context = {"run_id": "r", "episode_key": "e", "turn": 1, "api_key": "secret-test"}
    calls = []
    def post(_):
        events = read_events(path)
        assert events[-1]["event"] == "started"  # durable before network send
        calls.append(1)
        if len(calls) == 1:
            raise HTTPError("http://host", 429, "secret-test", {}, BytesIO(b"secret-test"))
        return {"output_text": "secret-test visible", "usage": {"input_tokens": 10, "output_tokens": 2},
                "output": [{"type": "reasoning", "content": "HIDDEN_REASONING"}]}
    client._post_once = post
    assert client([]) == "secret-test visible"
    events = read_events(path)
    assert [e["event"] for e in events] == ["started", "error", "started", "finished"]
    assert len({e["request_id"] for e in events}) == 2
    assert events[-1]["retry_index"] == 1
    assert ledger_totals(path)["unknown_requests"] == 1
    assert Decimal(ledger_totals(path)["accounted_cost_cny"]) > 0
    assert "secret-test" not in path.read_text()
    assert "HIDDEN_REASONING" not in path.read_text()
    client._post_once = lambda _: (_ for _ in ()).throw(ValueError("private failure"))
    with pytest.raises(RuntimeError):
        client([])
    assert client.last_debug is None
    assert "private failure" not in path.read_text()


def test_orphan_and_corrupt_tail_fail_closed(tmp_path):
    path = tmp_path / "requests.jsonl"
    recorder = RequestRecorder(path)
    recorder({"event": "started", "model": "deepseek-flash", "request_id": "a", "context": {}})
    assert ledger_totals(path)["orphan_requests"] == 1
    assert ledger_totals(path)["unknown_requests"] == 1
    with path.open("a") as stream:
        stream.write('{"request_id":')
    with pytest.raises(ValueError, match="incomplete tail"):
        ledger_totals(path)
