#!/usr/bin/env python3
"""
agent_scenario_ranker.py
========================
AI agent that ranks 10 new test scenarios using training experience stored
in semantic_memory.json (fault durations 2-12 cycles).

The agent:
  1. Loads the semantic memory (training KPIs per location per fault duration)
  2. For each of 10 test scenarios, retrieves the full training KPI history
  3. Builds a rich engineering context prompt
  4. Calls the SMART LLM (gemini-2.5-flash or llama-3.3-70b-versatile) to
     extrapolate severity and produce a ranked list
  5. Saves results as JSON + CSV

Requires an API key in the environment (never commit one):
  PowerShell : $env:GROQ_API_KEY = "gsk_..."
  bash       : export GROQ_API_KEY="gsk_..."

Usage
-----
  python agent_scenario_ranker.py                        # uses env vars + defaults
  python agent_scenario_ranker.py ranker_config.json     # uses config file
  python agent_scenario_ranker.py --list                 # print available memory scenarios

Config file format (ranker_config.json)
---------------------------------------
  {
    "llm": {
      "provider": "groq",
      "models_by_provider": {
        "gemini": {"fast": "gemini-2.5-flash-lite", "smart": "gemini-2.5-flash"},
        "groq":   {"fast": "llama-3.1-8b-instant",  "smart": "llama-3.3-70b-versatile"}
      }
    },
    "test_scenarios": [
      {"location": "Bus 10", "fault_type": "Bus",  "test_duration_cycles": 16},
      {"location": "Line 01-02", "fault_type": "Line", "test_duration_cycles": 16}
    ],
    "output_dir": "ranking_results"
  }

An optional "llm.api_keys" block is still honoured as a fallback, but the
environment variables take precedence and are the recommended way to supply
credentials.
"""

__author__ = "Andrea Pomarico"

import csv
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import REPO_DIR, SEM_METADATA_PATH, TEST_METADATA_PATH

# ── API keys ────────────────────────────────────────────────────────────────
# Never hardcode credentials here.  Keys are read from the environment and may
# be overridden by the "llm.api_keys" block of the config file.
#   PowerShell : $env:GROQ_API_KEY = "gsk_..."
#   bash       : export GROQ_API_KEY="gsk_..."
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")

# ── Constants ────────────────────────────────────────────────────────────────
SMART_MODELS = {
    "gemini": "gemini-2.5-flash",
    "groq":   "llama-3.3-70b-versatile",
}

MEMORY_JSON = SEM_METADATA_PATH
TEST_MEMORY_JSON = TEST_METADATA_PATH

# ── System prompt for the ranking LLM ────────────────────────────────────────
SYSTEM_PROMPT = """
You are a senior power systems engineer specializing in transient stability
analysis of the IEEE 39-Bus New England power system.

CONTEXT
You have been trained on short-circuit fault simulations at fault durations of
2 to 20 cycles (20–200 ms). Your task is to analyze the provided training-data
KPI history for all fault locations in the test set and RANK them from MOST
SEVERE to LEAST SEVERE.

RANKING CRITERIA (weighted, highest to lowest)
1. Stability collapse — scenarios already going unstable at low training
   durations are almost certainly catastrophic at test durations.
2. Severity score trend — monotonically increasing severity signals proximity
   to the stability boundary.
3. Voltage violation intensity — depth of voltage nadir during fault and
   breadth of post-fault under-/over-voltage violations.
4. Network criticality — proximity to generation buses and critical corridors.

OUTPUT FORMAT
Respond ONLY with a single valid JSON object matching this schema exactly
(no markdown, no explanation outside the JSON):
{
  "ranking": [
    {
      "rank": 1,
      "scenario": "Bus 10 @ 16 cycles",
      "location": "Bus 10",
      "fault_type": "Bus",
      "test_duration_cycles": 16,
      "expected_severity_level": "critical",
      "extrapolated_severity_score": 1.45,
      "confidence": 4,
      "training_unstable_from_cycle": 8,
      "vmin_aft_extrapolated": 0.7812,
      "vmin_aft_bus": "Bus 25",
      "vmax_aft_extrapolated": 1.0634,
      "vmax_aft_bus": "Bus 30",
      "reasoning": "Concise engineering explanation (2-3 sentences).",
      "key_indicators": ["went unstable at 8 cycles in training", "severity > 1.0 at 10 cycles"]
    }
  ],
  "summary": "Overall comparative analysis of top scenarios (3-5 sentences).",
  "methodology": "Brief description of extrapolation approach (1-2 sentences).",
  "caveats": "Important assumptions or limitations (1-2 sentences)."
}

Severity levels: critical (score > 1.0), high (0.5–1.0), medium (0.2–0.5), low (< 0.2).
Confidence 1 (very uncertain) to 5 (very confident).
""".strip()

# ═══════════════════════════════════════════════════════════════════════════════
# Memory helpers
# ═══════════════════════════════════════════════════════════════════════════════

def load_memory() -> list[dict]:
    """Load semantic_memory.json and return training entries (cycles 2–20)."""
    if not MEMORY_JSON.exists():
        raise FileNotFoundError(
            f"semantic_memory.json not found at {MEMORY_JSON}\n"
            "Run: python semantic_memory.py build"
        )
    with open(MEMORY_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [e for e in data if 2 <= e.get("duration_cycles", 0) <= 20]


def load_test_scenarios_from_memory(limit: int = 10) -> list[dict]:
    """Load test_memory.json and extract unique (location, fault_type, duration) scenarios.
    Only returns scenarios that exist in the dataset.
    
    Args:
        limit: Maximum number of scenarios to return (random sample if > scenarios)
    """
    if not TEST_MEMORY_JSON.exists():
        raise FileNotFoundError(
            f"test_memory.json not found at {TEST_MEMORY_JSON}\n"
            "Run: python semantic_memory.py build --test-fraction 0.2"
        )
    with open(TEST_MEMORY_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Extract unique (location, fault_type, duration_cycles) scenarios that actually exist
    seen = {}
    scenarios = []
    for e in data:
        location = e.get("location", "").strip()
        fault_type = e.get("fault_type", "").strip()
        duration = e.get("duration_cycles")
        
        if not location or not fault_type or duration is None:
            continue
            
        key = (location, fault_type, duration)
        if key not in seen:
            seen[key] = True
            scenarios.append({
                "location": location,
                "fault_type": fault_type,
                "test_duration_cycles": duration,
            })
    
    # Apply limit with random sampling
    if limit and len(scenarios) > limit:
        import random
        scenarios = random.sample(scenarios, limit)
    
    return sorted(scenarios, key=lambda x: (x["fault_type"], x["location"], x["test_duration_cycles"]))


def get_location_history(
    memory: list[dict], location: str, fault_type: str
) -> list[dict]:
    """Return all training entries for a given location, sorted by duration."""
    hits = [
        e for e in memory
        if e.get("location") == location and e.get("fault_type") == fault_type
    ]
    return sorted(hits, key=lambda e: e["duration_cycles"])


def list_available_scenarios(memory: list[dict]) -> None:
    """Print all unique (location, fault_type) pairs in the memory."""
    seen: dict[tuple, list[int]] = defaultdict(list)
    for e in memory:
        key = (e.get("fault_type", "?"), e.get("location", "?"))
        seen[key].append(e["duration_cycles"])
    print(f"\n{'TYPE':<6}  {'LOCATION':<14}  TRAINING CYCLES")
    print("-" * 50)
    for (ft, loc), cycles in sorted(seen.items()):
        cyc_str = ", ".join(str(c) for c in sorted(cycles))
        print(f"{ft:<6}  {loc:<14}  {cyc_str}")
    print(f"\n{len(seen)} unique scenarios in training memory.\n")

# ═══════════════════════════════════════════════════════════════════════════════
# Prompt building
# ═══════════════════════════════════════════════════════════════════════════════

def _kpi_value(kpi: dict, key: str, fmt: str = ".4f") -> str:
    val = kpi.get(key, None)
    if val is None:
        return "?"
    if isinstance(val, float):
        return format(val, fmt)
    return str(val)


def format_history_table(history: list[dict]) -> str:
    """Format training KPI history as a compact ASCII table."""
    from collections import Counter
    header = "  cyc | sev_score | stable | vmin_aft | vmax_aft"
    sep = "  " + "-" * (len(header) - 2)
    rows = [header, sep]
    all_vlo: list[str] = []
    all_vhi: list[str] = []
    for e in history:
        kpi = e.get("kpi", {})
        sev = kpi.get("severity_score", kpi.get("severity", {}).get("score", None))
        sev_str = f"{sev:.3f}" if isinstance(sev, float) else "?"
        stable = "YES" if kpi.get("stable", 1) else "NO "
        rows.append(
            f"  {e['duration_cycles']:>3} | {sev_str:>9} | {stable}   "
            f"| {_kpi_value(kpi,'vmin_aft','.3f'):>7} "
            f"| {_kpi_value(kpi,'vmax_aft','.3f'):>7}"
        )
        all_vlo.extend(kpi.get("buses_vlo_aft_names", []))
        all_vhi.extend(kpi.get("buses_vhi_aft_names", []))
    # Compact bus-frequency summary (most persistent buses across training cycles)
    if all_vlo:
        vlo_str = ", ".join(f"{b}({c})" for b, c in Counter(all_vlo).most_common(5))
        rows.append(f"  Under-V buses (freq): {vlo_str}")
    if all_vhi:
        vhi_str = ", ".join(f"{b}({c})" for b, c in Counter(all_vhi).most_common(5))
        rows.append(f"  Over-V  buses (freq): {vhi_str}")
    return "\n".join(rows)


def _severity_trend(history: list[dict]) -> tuple[float, float, str, Optional[int]]:
    """
    Returns (min_sev, max_sev, trend_label, first_unstable_cycle).
    """
    severities: list[tuple[int, float]] = []
    first_unstable: Optional[int] = None

    for e in history:
        kpi = e.get("kpi", {})
        sev = kpi.get("severity_score", kpi.get("severity", {}).get("score", None))
        if isinstance(sev, float):
            severities.append((e["duration_cycles"], sev))
        if not kpi.get("stable", True) and first_unstable is None:
            first_unstable = e["duration_cycles"]

    if not severities:
        return 0.0, 0.0, "unknown", first_unstable

    values = [s for _, s in severities]
    min_s, max_s = min(values), max(values)
    if severities[-1][1] > severities[0][1] * 1.1:
        trend = "strongly increasing"
    elif severities[-1][1] > severities[0][1]:
        trend = "increasing"
    else:
        trend = "flat/non-monotonic"
    return min_s, max_s, trend, first_unstable


def build_user_message(scenarios: list[dict], memory: list[dict]) -> str:
    """Build the detailed user message for the ranking agent."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    scenario_word = "scenario" if len(scenarios) == 1 else "scenarios"
    lines = [
        f"RANKING REQUEST  |  {now}",
        "=" * 72,
        "",
        f"Rank the following {len(scenarios)} test {scenario_word} from MOST SEVERE to LEAST SEVERE.",
        "Each scenario shows training KPI history at fault durations 2–20 cycles.",
        "The test fault duration (unseen during training) is shown for each.",
        "",
    ]

    missing: list[str] = []

    for i, sc in enumerate(scenarios, 1):
        loc  = sc["location"]
        ft   = sc["fault_type"]
        cyc  = sc["test_duration_cycles"]
        label = f"SCENARIO {i:02d}: {loc}  ({ft} fault)  —  Test duration: {cyc} cycles ({cyc * 10} ms)"
        lines.append(label)
        lines.append("-" * len(label))

        history = get_location_history(memory, loc, ft)

        if not history:
            lines.append(f"  [WARNING] No training data found for '{loc}' ({ft}).")
            missing.append(f"{loc} ({ft})")
        else:
            min_s, max_s, trend, first_unstable = _severity_trend(history)
            unstable_str = (
                f"{first_unstable} cycles" if first_unstable else "never in training"
            )
            lines.append(
                f"  Training severity range : {min_s:.3f}  →  {max_s:.3f}  ({trend})"
            )
            lines.append(f"  First instability at    : {unstable_str}")
            lines.append("")
            lines.append(format_history_table(history))

        lines.append("")

    if missing:
        lines.append(
            f"NOTE: No training data found for {len(missing)} scenario(s): "
            + "; ".join(missing)
        )
        lines.append("These must still be ranked — use network knowledge to estimate severity.")
        lines.append("")

    lines.append("=" * 72)
    lines.append(
        f"Now produce the JSON ranking of all {len(scenarios)} scenarios "
        "from most to least severe based on the above training data."
    )
    return "\n".join(lines)

# ═══════════════════════════════════════════════════════════════════════════════
# LLM layer (mirrors Gemini/code/llm_client.py style)
# ═══════════════════════════════════════════════════════════════════════════════

def _build_clients(provider: str, api_keys: dict):
    """
    Return (gemini_client, groq_client) — only the active one is initialised.

    The provider SDKs are imported lazily so that only the one actually in use
    needs to be installed.
    """
    gemini_client = None
    groq_client   = None
    if provider == "gemini":
        key = api_keys.get("gemini", "")
        if not key or key.startswith("YOUR_"):
            raise ValueError(
                "Missing Gemini API key. Set 'llm.api_keys.gemini' in the config "
                "file or the GEMINI_API_KEY environment variable."
            )
        try:
            from google import genai
        except ImportError as exc:
            raise ImportError(
                "The Gemini provider requires the google-genai package: "
                "pip install google-genai"
            ) from exc
        gemini_client = genai.Client(api_key=key)
    elif provider == "groq":
        key = api_keys.get("groq", "")
        if not key or key.startswith("YOUR_"):
            raise ValueError(
                "Missing Groq API key. Set 'llm.api_keys.groq' in the config "
                "file or the GROQ_API_KEY environment variable."
            )
        try:
            from groq import Groq
        except ImportError as exc:
            raise ImportError(
                "The Groq provider requires the groq package: pip install groq"
            ) from exc
        groq_client = Groq(api_key=key)
    else:
        raise ValueError(f"Unknown LLM provider: '{provider}'. Use 'gemini' or 'groq'.")
    return gemini_client, groq_client


def call_llm(
    provider: str,
    model: str,
    system_prompt: str,
    user_message: str,
    gemini_client,
    groq_client,
    max_tokens: int = 8192,
) -> str:
    if provider == "gemini":
        from google.genai import types

        response = gemini_client.models.generate_content(
            model=model,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=max_tokens,
                temperature=0.1,
            ),
        )
        return response.text or ""
    else:
        response = groq_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ],
            max_tokens=max_tokens,
            temperature=0.1,
        )
        return response.choices[0].message.content

# ═══════════════════════════════════════════════════════════════════════════════
# Response parsing
# ═══════════════════════════════════════════════════════════════════════════════

def parse_json_response(raw: str) -> dict:
    """Extract and parse JSON from the LLM response (handles markdown fences)."""
    text = raw.strip()
    # Strip markdown code fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text.strip())

# ═══════════════════════════════════════════════════════════════════════════════
# Output
# ═══════════════════════════════════════════════════════════════════════════════

def print_ranking(result: dict, provider: str, model: str) -> None:
    width = 72
    print()
    print("=" * width)
    print(f"  SCENARIO RANKING  |  {provider.upper()}  ({model})")
    print("=" * width)

    ranking = result.get("ranking", [])
    if not ranking:
        print("  [No ranking returned by the model]")
        return

    severity_icons = {
        "critical": "🔴",
        "high":     "🟠",
        "medium":   "🟡",
        "low":      "🟢",
    }

    for item in ranking:
        rank     = item.get("rank", "?")
        scenario = item.get("scenario", item.get("location", "?"))
        level    = str(item.get("expected_severity_level", "?")).lower()
        score    = item.get("extrapolated_severity_score", "?")
        conf     = item.get("confidence", "?")
        unstable = item.get("training_unstable_from_cycle")
        reason   = item.get("reasoning", "")
        icons    = item.get("key_indicators", [])

        icon  = severity_icons.get(level, "⚪")
        stars = "★" * conf + "☆" * (5 - conf) if isinstance(conf, int) else str(conf)
        score_str = f"{score:.3f}" if isinstance(score, float) else str(score)

        vmin_val = item.get("vmin_aft_extrapolated")
        vmin_bus = item.get("vmin_aft_bus", "?")
        vmax_val = item.get("vmax_aft_extrapolated")
        vmax_bus = item.get("vmax_aft_bus", "?")
        vmin_str = f"{vmin_val:.4f}" if isinstance(vmin_val, float) else str(vmin_val or "?")
        vmax_str = f"{vmax_val:.4f}" if isinstance(vmax_val, float) else str(vmax_val or "?")

        print(f"\n  #{rank:<2}  {icon} [{level.upper():<8}]  sev≈{score_str:<6}  conf:{stars}")
        print(f"       {scenario}")
        if unstable:
            print(f"       ⚡ Unstable from cycle {unstable} in training")
        print(f"       Vmin_aft≈{vmin_str} pu @ {vmin_bus}  |  Vmax_aft≈{vmax_str} pu @ {vmax_bus}")
        if reason:
            wrapped = _wrap(reason, 65, "       ")
            print(f"       {wrapped}")
        for ind in icons[:3]:
            print(f"         • {ind}")

    print()
    print("-" * width)
    print("SUMMARY")
    print(_wrap(result.get("summary", "N/A"), 68, "  "))
    print()
    print("METHODOLOGY")
    print(_wrap(result.get("methodology", "N/A"), 68, "  "))
    if result.get("caveats"):
        print()
        print("CAVEATS")
        print(_wrap(result["caveats"], 68, "  "))
    print("=" * width)


def _wrap(text: str, width: int, indent: str) -> str:
    """Simple word-wrap helper."""
    words = text.split()
    lines, current = [], []
    length = 0
    for w in words:
        if length + len(w) + 1 > width and current:
            lines.append(indent + " ".join(current))
            current, length = [w], len(w)
        else:
            current.append(w)
            length += len(w) + 1
    if current:
        lines.append(indent + " ".join(current))
    return "\n".join(lines)


def save_results(
    result: dict,
    scenarios: list[dict],
    provider: str,
    model: str,
    output_dir: Path,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Full JSON
    json_path = output_dir / f"ranking_{provider}_{ts}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "metadata": {
                    "provider": provider,
                    "model": model,
                    "timestamp": ts,
                    "test_scenarios": scenarios,
                    "memory_file": str(MEMORY_JSON),
                },
                "result": result,
            },
            f,
            indent=2,
        )

    # Summary CSV
    csv_path = output_dir / f"ranking_{provider}_{ts}.csv"
    ranking = result.get("ranking", [])
    if ranking:
        fieldnames = [
            "rank",
            "location",
            "fault_type",
            "test_duration_cycles",
            "expected_severity_level",
            "extrapolated_severity_score",
            "confidence",
            "training_unstable_from_cycle",
            "vmin_aft_extrapolated",
            "vmin_aft_bus",
            "vmax_aft_extrapolated",
            "vmax_aft_bus",
            "reasoning",
        ]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(ranking)

    print(f"\n  Saved JSON : {json_path}")
    print(f"  Saved CSV  : {csv_path}")
    return json_path, csv_path

# ═══════════════════════════════════════════════════════════════════════════════
# Config loading
# ═══════════════════════════════════════════════════════════════════════════════

def load_config(config_path: Optional[str]) -> dict:
    """
    Load a JSON config file.  A relative path is looked up in the CWD first,
    then in the repository directory.  Returns {} when no path is given.
    """
    if not config_path:
        return {}

    candidate = Path(config_path)
    if not candidate.exists() and not candidate.is_absolute():
        candidate = REPO_DIR / config_path
    if not candidate.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(candidate, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_llm_settings(cfg: dict) -> tuple[str, dict, dict]:
    """
    Returns (provider, api_keys, models_by_alias).
    models_by_alias: {"smart": "<model_name>"}
    """
    llm = cfg.get("llm", {})
    provider = llm.get("provider", os.getenv("LLM_PROVIDER", "groq")).strip().lower()

    api_keys = {
        "gemini": (
            GEMINI_API_KEY
            or llm.get("api_keys", {}).get("gemini")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY", "")
        ),
        "groq": (
            GROQ_API_KEY
            or llm.get("api_keys", {}).get("groq")
            or os.getenv("GROQ_API_KEY", "")
        ),
    }

    mbp = llm.get("models_by_provider", {})
    smart_model = (
        mbp.get(provider, {}).get("smart")
        or SMART_MODELS.get(provider, SMART_MODELS["gemini"])
    )
    return provider, api_keys, {"smart": smart_model}

# ═══════════════════════════════════════════════════════════════════════════════
# Main agent entry point
# ═══════════════════════════════════════════════════════════════════════════════

def run_ranking_agent(config_path: Optional[str] = None) -> dict:
    cfg       = load_config(config_path)
    # A relative output_dir is resolved against the repository, not the CWD.
    output_dir = Path(cfg.get("output_dir", "ranking_results"))
    if not output_dir.is_absolute():
        output_dir = REPO_DIR / output_dir

    # Load 10 random test scenarios from test_memory.json
    print("\n[0/4] Loading 10 random test scenarios from test_memory.json …")
    scenarios = load_test_scenarios_from_memory(limit=10)
    print(f"      {len(scenarios)} scenarios loaded.")

    provider, api_keys, models = resolve_llm_settings(cfg)
    smart_model = models["smart"]

    print("=" * 72)
    print("  SCENARIO RANKING AGENT  —  IEEE 39-Bus Transient Stability")
    print(f"  Provider : {provider.upper()}")
    print(f"  Model    : {smart_model}")
    print(f"  Scenarios: {len(scenarios)}")
    print("=" * 72)

    # Step 1 — load memory
    print("\n[1/4] Loading training semantic memory …")
    memory = load_memory()
    print(f"      {len(memory)} training entries loaded (cycles 2–20).")

    # Step 2 — validate scenarios against memory
    print("\n[2/4] Validating test scenarios against training memory …")
    for sc in scenarios:
        hist = get_location_history(memory, sc["location"], sc["fault_type"])
        status = f"  {len(hist)} training entries" if hist else "  [WARNING] not found in memory"
        print(f"      {sc['location']:<14} ({sc['fault_type']:<4}){status}")

    # Step 3 — build prompt and call LLM
    print("\n[3/4] Building prompt and calling LLM …")
    user_msg = build_user_message(scenarios, memory)
    print(f"      Prompt: {len(user_msg):,} characters")
    
    print(f"\n[4/4] Calling {provider} smart model ({smart_model}) …")
    gemini_client, groq_client = _build_clients(provider, api_keys)
    
    try:
        raw_response = call_llm(
            provider, smart_model, SYSTEM_PROMPT, user_msg,
            gemini_client, groq_client, max_tokens=4096
        )
        result = parse_json_response(raw_response)
    except json.JSONDecodeError as exc:
        print(f"\n[ERROR] Could not parse LLM response as JSON: {exc}")
        print("Raw response (first 3000 chars):")
        print(raw_response[:3000])
        sys.exit(1)
    except Exception as exc:
        print(f"\n[ERROR] {exc}")
        sys.exit(1)

    # Display and save
    print_ranking(result, provider, smart_model)
    save_results(result, scenarios, provider, smart_model, output_dir)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        mem = load_memory()
        list_available_scenarios(mem)
        sys.exit(0)

    config_file = sys.argv[1] if len(sys.argv) > 1 else None
    run_ranking_agent(config_file)
