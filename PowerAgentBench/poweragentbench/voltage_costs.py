"""CNY usage estimates and durable request accounting (not a provider invoice)."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

PRICING_PATH = Path(__file__).resolve().parent.parent / "benchmarks/steady/voltage_control/config/pricing.json"
BEIJING = timezone(timedelta(hours=8))


def append_event(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def read_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    # Never silently discard a truncated ledger: it could contain billable usage.
    text = path.read_text(encoding="utf-8")
    if text and not text.endswith("\n"):
        raise ValueError("request ledger has an incomplete tail; manual reconciliation required")
    return [json.loads(line) for line in text.splitlines()]


def _count(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("usage counts must be nonnegative integers")
    return value


def normalize_usage(raw: Any) -> dict:
    """Accept Responses and Chat usage; reject conflicting/malformed counts."""
    empty = dict(input_tokens=None, cached_input_tokens=None, output_tokens=None, total_tokens=None)
    if not isinstance(raw, dict):
        return {**empty, "usage_status": "unknown"}
    try:
        def aliases(*keys):
            values = [_count(raw[k]) for k in keys if k in raw]
            if not values or len(set(values)) != 1:
                raise ValueError("missing or conflicting usage")
            return values[0]
        inp = aliases("input_tokens", "prompt_tokens")
        out = aliases("output_tokens", "completion_tokens")
        if "total_tokens" in raw and _count(raw["total_tokens"]) != inp + out:
            raise ValueError("total usage mismatch")
        cached = []
        if "prompt_cache_hit_tokens" in raw:
            cached.append(_count(raw["prompt_cache_hit_tokens"]))
        for key in ("input_tokens_details", "prompt_tokens_details"):
            details = raw.get(key)
            if details is not None and not isinstance(details, dict):
                raise ValueError("invalid usage details")
            if isinstance(details, dict) and "cached_tokens" in details:
                cached.append(_count(details["cached_tokens"]))
        if "prompt_cache_miss_tokens" in raw:
            cached.append(inp - _count(raw["prompt_cache_miss_tokens"]))
        if cached and (len(set(cached)) != 1 or not 0 <= cached[0] <= inp):
            raise ValueError("cache usage mismatch")
        hit = cached[0] if cached else (0 if inp == 0 else None)
        return dict(input_tokens=inp, cached_input_tokens=hit, output_tokens=out,
                    total_tokens=inp + out, usage_status="known" if hit is not None else "cache_unknown")
    except ValueError:
        return {**empty, "usage_status": "invalid"}


def _aware(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("timezone-aware request timestamp required")
    return moment.astimezone(BEIJING)


def peak_during(start: datetime, end: datetime, pricing: dict) -> bool:
    start, end = _aware(start), _aware(end)
    if end < start:
        raise ValueError("request end precedes start")
    day = start.date()
    while day <= end.date():
        if day.weekday() in pricing["schedule"]["peak_weekdays"]:
            for first, last in pricing["schedule"]["peak_intervals"]:
                lower = datetime.combine(day, time.fromisoformat(first), BEIJING)
                upper = datetime.combine(day, time.fromisoformat(last), BEIJING)
                if start < upper and end >= lower:
                    return True
        day += timedelta(days=1)
    return False


def estimate_cost(raw_usage: Any, start: datetime, end: datetime, pricing: dict) -> dict:
    usage = normalize_usage(raw_usage)
    tier = "peak" if peak_during(start, end, pricing) else "offpeak"
    base = {**usage, "price_tier": tier, "price_version": pricing["price_version"],
            "currency": "CNY", "cost_cny": None, "cost_upper_bound_cny": None, "cost_status": "unknown"}
    if usage["input_tokens"] is None:
        return base
    prices = pricing["rates"][tier]
    hit = usage["cached_input_tokens"] or 0
    amount = (Decimal(hit) * Decimal(prices["input_cached"]) +
              Decimal(usage["input_tokens"] - hit) * Decimal(prices["input_uncached"]) +
              Decimal(usage["output_tokens"]) * Decimal(prices["output"])) / Decimal(pricing["unit_tokens"])
    # Spanning a tariff boundary is conservatively charged at the higher tariff.
    start_peak = peak_during(start, start, pricing)
    end_peak = peak_during(end, end, pricing)
    upper = usage["usage_status"] == "cache_unknown" or (tier == "peak" and not (start_peak and end_peak))
    if upper:
        base.update(cost_status="upper_bound", cost_upper_bound_cny=str(amount))
    else:
        base.update(cost_status="estimated", cost_cny=str(amount))
    return base


def ledger_totals(path: Path, *, run_id: str | None = None, episode_key: str | None = None) -> dict:
    starts, ends = {}, {}
    for event in read_events(path):
        request_id = event["request_id"]
        if event["event"] == "started":
            if request_id in starts:
                raise ValueError("duplicate request start")
            starts[request_id] = event
        elif event["event"] in ("finished", "error"):
            if request_id not in starts or request_id in ends:
                raise ValueError("request terminal event without unique start")
            if event.get("context") != starts[request_id].get("context"):
                raise ValueError("request context changed")
            ends[request_id] = event
        else:
            raise ValueError("unsupported request event")
    selected = {key: value for key, value in starts.items()
                if (run_id is None or value.get("context", {}).get("run_id") == run_id)
                and (episode_key is None or value.get("context", {}).get("episode_key") == episode_key)}
    reservations = {}
    for reservation in read_events(path.with_name("reservations.jsonl")):
        key = reservation["request_id"]
        if key not in starts or key in reservations:
            raise ValueError("reservation requires a unique existing request")
        terminal = ends.get(key, {})
        if terminal.get("cost_status") in ("estimated", "upper_bound"):
            raise ValueError("cannot reserve already accounted usage")
        if reservation.get("approved_by") != "user" or not reservation.get("reason"):
            raise ValueError("unverified charge reserve requires explicit user approval")
        amount = Decimal(reservation["reserve_cny"])
        if not amount.is_finite() or amount <= 0:
            raise ValueError("invalid unverified charge reserve")
        reservations[key] = amount
    total = Decimal("0")
    reserved = Decimal("0")
    unknown = 0
    unreserved = 0
    for key in selected:
        event = ends.get(key, {})
        amount = event.get("cost_cny") if event.get("cost_status") == "estimated" else event.get("cost_upper_bound_cny")
        if amount is None:
            unknown += 1
            if key in reservations:
                reserved += reservations[key]
            else:
                unreserved += 1
        else:
            cost = Decimal(amount)
            if not cost.is_finite() or cost < 0:
                raise ValueError("invalid ledger cost")
            total += cost
    return {"accounted_cost_cny": str(total), "unknown_requests": unknown,
            "reserved_unknown_cost_cny": str(reserved), "budget_consumed_cny": str(total + reserved),
            "unreserved_unknown_requests": unreserved,
            "request_count": len(selected), "orphan_requests": sum(key not in ends for key in selected)}


class BudgetStop(RuntimeError):
    """Control signal, never an API or JSON error."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(tmp, path)


class RequestRecorder:
    """Optional client hook: append sanitized start/end events synchronously."""

    def __init__(self, path: Path, pricing_path: Path = PRICING_PATH):
        self.path = Path(path)
        self.pricing = json.loads(pricing_path.read_text(encoding="utf-8"))
        self.pricing_sha256 = hashlib.sha256(pricing_path.read_bytes()).hexdigest()
        if self.pricing.get("currency") != "CNY" or self.pricing.get("unit_tokens") != 1000000:
            raise ValueError("CNY prices must be per million tokens")
        for tier in ("offpeak", "peak"):
            for field in ("input_cached", "input_uncached", "output"):
                price = Decimal(self.pricing["rates"][tier][field])
                if not price.is_finite() or price < 0:
                    raise ValueError("invalid price snapshot")

    def __call__(self, event: dict) -> None:
        event = dict(event)
        if event["model"] != self.pricing["model"]:
            raise ValueError("no approved pricing for requested model")
        event["pricing_sha256"] = self.pricing_sha256
        if event["event"] != "started":
            usage = event.pop("usage", None)
            event.update(estimate_cost(usage, datetime.fromisoformat(event["started_at"]),
                                       datetime.fromisoformat(event["ended_at"]), self.pricing))
        append_event(self.path, event)


class Campaign(RequestRecorder):
    """One locked, append-only CNY account shared by all Pilot runs."""

    def __init__(self, root: Path, *, episode_limit: str = "0.20", campaign_limit: str = "10",
                 pricing_path: Path = PRICING_PATH, stage: str = "smoke", clock=None):
        self.root = Path(root)
        super().__init__(self.root / "requests.jsonl", pricing_path)
        self.episode_limit, self.campaign_limit = Decimal(episode_limit), Decimal(campaign_limit)
        for amount, maximum in ((self.episode_limit, Decimal("0.20")), (self.campaign_limit, Decimal("22"))):
            if not amount.is_finite() or not 0 < amount <= maximum:
                raise ValueError("CNY limits must be positive and within approved 0.20/22 limits")
        if stage not in ("smoke", "pilot"):
            raise ValueError("invalid campaign stage")
        self.stage = stage
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.campaign_id = None
        self.last_stop_reason = None
        self.lock_fd = None

    def __enter__(self):
        self.root.mkdir(parents=True, exist_ok=True)
        # No automatic stale-lock removal: the owner/in-flight usage must be checked.
        self.lock_fd = os.open(self.root / "campaign.lock", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            os.write(self.lock_fd, f"pid={os.getpid()}\n".encode())
            os.fsync(self.lock_fd)
            metadata = {"schema_version": 1, "model": self.pricing["model"], "pricing_sha256": self.pricing_sha256,
                        "episode_limit_cny": str(self.episode_limit), "campaign_limit_cny": str(self.campaign_limit),
                        "offpeak_only": True}
            config = self.root / "campaign.json"
            if config.exists():
                old = json.loads(config.read_text(encoding="utf-8"))
                if any(old.get(k) != value for k, value in metadata.items()):
                    raise ValueError("campaign identity/limits changed; cannot silently reset spending")
                self.campaign_id = old["campaign_id"]
            else:
                if self.path.exists():
                    raise ValueError("request ledger exists without campaign metadata")
                self.campaign_id = str(uuid.uuid4())
                atomic_json(config, {**metadata, "campaign_id": self.campaign_id})
                atomic_json(self.root / "pricing_snapshot.json", self.pricing)
            ledger_totals(self.path)  # validate history before allowing work
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None
            (self.root / "campaign.lock").unlink()

    def reason(self, context: dict, *, timeout: float = 0, check_window: bool = True) -> str | None:
        # ponytail: single-writer linear ledger scan; index only if large campaigns need it.
        totals = ledger_totals(self.path)
        if totals["unreserved_unknown_requests"]:
            return "usage_unknown"
        # A user-approved precautionary reserve consumes the campaign budget,
        # but is not asserted to be an actual charge or episode model usage.
        spent = Decimal(totals["budget_consumed_cny"])
        if spent >= self.campaign_limit:
            return "campaign_cost_limit"
        if self.stage == "smoke" and spent >= Decimal("1"):
            return "smoke_cost_limit"
        episode = ledger_totals(self.path, run_id=context.get("run_id"), episode_key=context.get("episode_key"))
        if Decimal(episode["accounted_cost_cny"]) >= self.episode_limit:
            return "episode_cost_limit"
        if check_window:
            now = self.clock()
            if peak_during(now, now + timedelta(seconds=max(0, timeout)), self.pricing):
                return "offpeak_pause"
        return None

    def next_offpeak(self, timeout: float = 0) -> str:
        moment = _aware(self.clock())
        for _ in range(7 * 24 * 60):
            if not peak_during(moment, moment + timedelta(seconds=max(0, timeout)), self.pricing):
                return moment.isoformat()
            moment = moment.replace(second=0, microsecond=0) + timedelta(minutes=1)
        raise ValueError("no safe window within seven days for configured timeout")

    def __call__(self, event: dict) -> None:
        if self.lock_fd is None:
            raise RuntimeError("campaign must hold its single-writer lock")
        context = event.get("context", {})
        if context.get("campaign_id") != self.campaign_id or not context.get("run_id") or not context.get("episode_key"):
            raise ValueError("request missing campaign/run/episode identity")
        if event["event"] == "started":
            reason = self.reason(context, timeout=event.get("timeout_seconds", 0))
            if reason:
                raise BudgetStop(reason)
        super().__call__(event)
        if event["event"] != "started":
            policy_path = self.root / "reservation_policy.json"
            if policy_path.exists():
                policy = json.loads(policy_path.read_text(encoding="utf-8"))
                if policy.get("approved_by") != "user" or policy.get("reserve_per_unknown_request_cny") != "0.20":
                    raise ValueError("invalid approved unknown-charge reservation policy")
                terminal = read_events(self.path)[-1]
                if terminal.get("cost_status") == "unknown":
                    append_event(self.root / "reservations.jsonl", {
                        "request_id": event["request_id"], "reserve_cny": "0.20", "approved_by": "user",
                        "approved_at": policy["approved_at"], "reason": policy["reason"],
                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                    })
            self.last_stop_reason = self.reason(context)
            # A paid successful response can be processed once; the agent checks
            # last_stop_reason before asking for another response. Unknown-cost
            # errors stop immediately, before the client's automatic retry loop.
            if event["event"] == "error" and self.last_stop_reason:
                raise BudgetStop(self.last_stop_reason)
