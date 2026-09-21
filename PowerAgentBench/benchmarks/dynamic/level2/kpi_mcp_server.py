"""
MCP server — KPI Benchmark + DIgSILENT PowerFactory Control

KPI Tools:
  list_csv_files        — discover all CSVs available in the benchmark directory
  run_kpis              — run compute_kpis.py for a chosen CSV and save kpi_report.json
  read_kpi_report       — return the last saved kpi_report.json
  query_semantic_memory — search the semantic memory with natural language
  read_ranker_config    — read ranker_config.json (or any JSON config in the benchmark dir)
  get_training_history  — return all training KPI entries for a location (durations 2-12)
  get_location_history  — return ALL semantic memory entries for a location (any duration)
  lookup_scenarios      — return semantic memory entries for specific CSV paths
  read_memory_split     — parse memory_split.txt and return train/test path lists
  save_predictions      — persist agent KPI predictions to predictions.json before simulation
  evaluate_predictions  — compute actual KPIs from a simulation CSV and compare with saved predictions

PowerFactory Tools:
  ping              — connectivity check
  close_digsilent   — close the PowerFactory API session
  get_config        — return simulation_config.json as a JSON string
  import_project    — import a .pfd file and activate it in PowerFactory
  create_study_case — create/activate a study case by name (no simulation run)
  modify_parameter  — modify an object attribute by object query + variable name
  run_loadflow      — run a load flow calculation (ComLdf)
  run_short_circuit — run a short-circuit calculation (ComShc)
  run_simulation    — run the full pipeline from simulation_config.json
  run_custom_case   — run a one-off case with parameters supplied at call-time
  read_results_csv  — read the latest (or a specific) RMS results CSV
"""

__author__ = "Andrea Pomarico"

import os
import sys
import json
import concurrent.futures
import math
from datetime import datetime
from typing import Optional, Any

# ── Windows UTF-8 fix ──────────────────────────────────────────────
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ── Redirect print() → stderr so output never corrupts MCP frames ──
import builtins as _bt

def _stderr_print(*args, _p=_bt.print, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    _p(*args, **kwargs)

_bt.print = _stderr_print
del _bt

# ── Make compute_kpis importable from the same directory ───────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compute_kpis import compute_kpis

from fastmcp import FastMCP

# ── Paths ──────────────────────────────────────────────────────────
# BENCHMARK_DIR holds the simulation CSVs (configurable via BENCHMARK_DATA_DIR);
# CONFIG_DIR holds the code, the memory artifacts and the JSON configs.
from config import DATA_DIR, REPO_DIR

BENCHMARK_DIR    = str(DATA_DIR)
CONFIG_DIR       = str(REPO_DIR)
REPORT_PATH      = os.path.join(CONFIG_DIR, "kpi_report.json")
MEMORY_JSON_PATH = REPO_DIR / "semantic_memory.json"
_DEFAULT_CFG     = os.path.join(CONFIG_DIR, "simulation_config.json")

# ── MCP server ─────────────────────────────────────────────────────
mcp = FastMCP(
    name="KPI Benchmark + DIgSILENT PowerFactory",
    instructions=(
        "Provides KPI benchmark computation tools and controls DIgSILENT PowerFactory "
        "RMS transient-stability simulations. Runs simulations and saves results "
        "(CSV, plots) to disk."
    ),
)

# ── Single dedicated thread for ALL PowerFactory API calls ─────────
# PowerFactory's Python API requires every call to originate from the
# same thread that called GetApplicationExt().  FastMCP dispatches tool
# handlers on whatever thread the async runtime provides, so every PF
# operation is funnelled through this one persistent thread.
_pf_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="pf_thread"
)


def _pf(fn, *args, **kwargs):
    """Run fn(*args, **kwargs) on the dedicated PowerFactory thread."""
    return _pf_executor.submit(fn, *args, **kwargs).result()


def _load_modules():
    """Deferred import — avoids startup crash when PowerFactory is not running."""
    from Agent_DIgSILENT import SimulationConfig, DIgSILENTAgent
    return SimulationConfig, DIgSILENTAgent


def _to_json(obj: Any) -> str:
    """Recursively sanitise and serialise a result dict to a JSON string."""
    try:
        import numpy as np
        _np = np
    except ImportError:
        _np = None

    def _clean(o):
        if _np is not None:
            if isinstance(o, _np.ndarray):
                return [_clean(v) for v in o.tolist()]
            if isinstance(o, _np.integer):
                return int(o)
            if isinstance(o, _np.floating):
                v = float(o)
                return None if (math.isnan(v) or math.isinf(v)) else v
            if isinstance(o, _np.bool_):
                return bool(o)
        if isinstance(o, dict):
            return {(str(k) if not isinstance(k, str) else k): _clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [_clean(v) for v in o]
        if isinstance(o, float):
            return None if (math.isnan(o) or math.isinf(o)) else o
        return o

    return json.dumps(_clean(obj), indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════
# KPI TOOLS
# ══════════════════════════════════════════════════════════════════

@mcp.tool()
def read_memory_split(split: str = "test") -> dict:
    """
    Parse memory_split.txt and return the scenario paths for the requested split.

    Parameters
    ----------
    split : str
        Which split to return: "test" (default), "semantic" (training), or "all".

    Returns
    -------
    dict
        {
          "semantic": ["Bus 01\\2.csv", ...],   # 584 training entries
          "test":     ["Bus 38\\10.csv", ...],  # 146 test entries
        }
        When split="test" only the "test" key is present; "semantic" for training only.
        "all" returns both keys.
    """
    path = os.path.join(CONFIG_DIR, "memory_split.txt")
    if not os.path.exists(path):
        return {"error": f"memory_split.txt not found in {CONFIG_DIR}"}

    semantic: list[str] = []
    test: list[str] = []
    current: list[str] | None = None

    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("Semantic memory:"):
                current = semantic
            elif stripped.startswith("Test memory:"):
                current = test
            elif current is not None:
                current.append(stripped)

    if split == "test":
        return {"test": test}
    if split == "semantic":
        return {"semantic": semantic}
    return {"semantic": semantic, "test": test}

@mcp.tool()
def lookup_scenarios(rel_paths: list[str]) -> list[dict]:
    """
    Return the semantic memory entries for the given list of relative CSV paths.

    Parameters
    ----------
    rel_paths : list[str]
        Relative paths exactly as they appear in memory_split.txt,
        e.g. ["Bus 12\\16.csv", "Line 03 - 04\\18.csv"].
        Both forward- and back-slash separators are accepted.

    Returns
    -------
    list[dict]
        One dict per input path, each containing the full semantic memory entry
        (rel_path, fault_type, location, duration_cycles, duration_ms, kpi,
        summary) plus a "found" flag.  If a path is not in the memory the entry
        will be {"rel_path": <path>, "found": False}.
    """
    if not MEMORY_JSON_PATH.exists():
        return [{"error": "semantic_memory.json not found. Run: python semantic_memory.py build"}]

    with open(MEMORY_JSON_PATH, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    # Build lookup index normalising separators
    index = {e["rel_path"].replace("/", "\\").replace("\\\\", "\\"): e for e in data}

    results = []
    for path in rel_paths:
        key = path.replace("/", "\\").replace("\\\\", "\\")
        entry = index.get(key)
        if entry:
            results.append({**entry, "found": True})
        else:
            results.append({"rel_path": path, "found": False})
    return results


@mcp.tool()
def list_csv_files() -> list[str]:
    """List all available CSV files in the benchmark directory (relative paths)."""
    result = []
    for root, _dirs, files in os.walk(BENCHMARK_DIR):
        for fname in sorted(files):
            if fname.lower().endswith(".csv"):
                rel = os.path.relpath(os.path.join(root, fname), BENCHMARK_DIR)
                result.append(rel)
    return sorted(result)


@mcp.tool()
def run_kpis(
    csv_path: str,
    short_start: Optional[float] = None,
    short_end: Optional[float] = None,
    underv_threshold: float = 0.9,
    after_extra: float = 0.02,
) -> dict:
    """
    Compute KPIs for a CSV file and save the result to kpi_report.json.

    Parameters
    ----------
    csv_path : str
        Relative path from the benchmark directory, e.g. 'Bus 01\\10.csv'
        or 'Bus 01/10.csv'. Use list_csv_files() to see all options.
    short_start : float, optional
        Start of the short-circuit window in seconds (default 1.0).
    short_end : float, optional
        End of the short-circuit window in seconds (inferred from filename if omitted).
    underv_threshold : float
        Under-voltage threshold in pu (default 0.9).
    after_extra : float
        Duration after the short-circuit window to evaluate (default 0.02 s).

    Returns
    -------
    dict
        KPI results (also persisted to kpi_report.json).
    """
    csv_path = csv_path.replace("/", os.sep).replace("\\", os.sep)
    full_path = csv_path if os.path.isabs(csv_path) else os.path.join(BENCHMARK_DIR, csv_path)

    if not os.path.exists(full_path):
        raise FileNotFoundError(f"CSV not found: {full_path}")

    result = compute_kpis(
        full_path,
        short_start=short_start,
        short_end=short_end,
        underv_threshold=underv_threshold,
        after_extra=after_extra,
    )

    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)

    return result


@mcp.tool()
def read_kpi_report() -> dict:
    """Return the contents of the last saved kpi_report.json."""
    if not os.path.exists(REPORT_PATH):
        return {"error": "No report found. Call run_kpis() first."}
    with open(REPORT_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


@mcp.tool()
def query_semantic_memory(query: str, top_k: int = 5) -> list:
    """
    Search the pre-built semantic memory for simulations matching a natural
    language query.  Build the memory first with:

        python semantic_memory.py build

    Parameters
    ----------
    query : str
        Natural language description of the scenario you are looking for.
        Examples:
          "buses with voltage collapse after a long fault"
          "unstable simulation with many over-voltage buses"
          "short fault with minimal impact on generator speed"
    top_k : int
        Number of results to return (default 5).

    Returns
    -------
    list[dict]
        Top-k most similar simulation entries, each containing:
          rel_path, fault_type, location, duration_ms, kpi, summary,
          similarity_score (cosine similarity, 0-1).
    """
    from semantic_memory import query_memory
    try:
        return query_memory(query, top_k=top_k)
    except FileNotFoundError as exc:
        return [{"error": str(exc)}]


@mcp.tool()
def read_ranker_config(filename: str = "ranker_config.json") -> dict:
    """
    Read a JSON config file from the benchmark directory.

    Parameters
    ----------
    filename : str
        Name of the JSON file inside the benchmark directory (default: ranker_config.json).

    Returns
    -------
    dict
        Parsed JSON content, or an error dict if the file does not exist.
    """
    path = os.path.join(CONFIG_DIR, filename)
    if not os.path.exists(path):
        return {"error": f"File not found: {filename}", "config_dir": CONFIG_DIR}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


@mcp.tool()
def get_location_history(location: str, fault_type: str) -> list:
    """
    Return ALL semantic memory entries for a given fault location, regardless
    of fault duration.  Use this when the train/test split is random and the
    known entries may span any duration.

    Parameters
    ----------
    location : str
        Location name as stored in semantic_memory.json,
        e.g. 'Bus 12' or 'Line 01 - 39'.
    fault_type : str
        'Bus' or 'Line'.

    Returns
    -------
    list[dict]
        All known entries for that location, sorted by duration_cycles.
        Each entry contains the full kpi sub-dict including:
        severity_score, stable, vmax_aft, vmin_aft, buses_vlo_sc,
        buses_vlo_aft, buses_vhi_aft, spmax_aft, spmin_aft.
    """
    if not MEMORY_JSON_PATH.exists():
        return [{"error": "semantic_memory.json not found. Run: python semantic_memory.py build"}]
    with open(MEMORY_JSON_PATH, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    entries = [
        e for e in data
        if e.get("location") == location
        and e.get("fault_type") == fault_type
    ]
    return sorted(entries, key=lambda e: e.get("duration_cycles", 0))


@mcp.tool()
def get_training_history(location: str, fault_type: str) -> list:
    """
    Return all training KPI entries (fault durations 2-12 cycles) for a given
    fault location, sorted by duration.

    Parameters
    ----------
    location : str
        Location name as stored in semantic_memory.json, e.g. 'Bus 12' or 'Line 01 - 39'.
    fault_type : str
        'Bus' or 'Line'.

    Returns
    -------
    list[dict]
        Training entries sorted by duration_cycles, each with kpi sub-dict.
    """
    if not MEMORY_JSON_PATH.exists():
        return [{"error": "semantic_memory.json not found. Run: python semantic_memory.py build"}]
    with open(MEMORY_JSON_PATH, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    entries = [
        e for e in data
        if e.get("location") == location
        and e.get("fault_type") == fault_type
        and 2 <= e.get("duration_cycles", 0) <= 12
    ]
    return sorted(entries, key=lambda e: e["duration_cycles"])


_PREDICTIONS_PATH = os.path.join(CONFIG_DIR, "predictions.json")


@mcp.tool()
def save_predictions(predictions: list[dict]) -> dict:
    """
    Persist the agent's KPI predictions to predictions.json before running
    simulations.  Call this once after Step 3 (estimation) so the predictions
    are available for comparison after the simulations complete.

    Parameters
    ----------
    predictions : list[dict]
        One dict per scenario.  Required fields per entry:

            scenario_path   str   — relative path, e.g. "Bus 12\\16.csv"
            severity_score  float — estimated severity (0–1+)
            stable          bool  — True = predicted stable
            vmax_aft        float — estimated max bus voltage after fault (pu)
            vmin_aft        float — estimated min bus voltage after fault (pu)
            bus_vmax        str   — predicted bus with highest voltage, e.g. "Bus 30"
            bus_vmin        str   — predicted bus with lowest voltage, e.g. "Bus 12"

        Any extra fields are stored as-is.

    Returns
    -------
    dict
        {"saved": <n>, "path": "<absolute path to predictions.json>"}
    """
    from datetime import datetime as _dt
    record = {
        "created_at": _dt.now().isoformat(timespec="seconds"),
        "predictions": predictions,
    }
    with open(_PREDICTIONS_PATH, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False)
    return {"saved": len(predictions), "path": _PREDICTIONS_PATH}


@mcp.tool()
def evaluate_predictions(csv_path: str, scenario_path: str) -> dict:
    """
    Compute actual KPIs from a simulation CSV, load the matching prediction
    from predictions.json, and return a side-by-side comparison.

    Parameters
    ----------
    csv_path : str
        Absolute path to the *_RMS.csv produced by run_custom_case / run_simulation.
    scenario_path : str
        The relative scenario path used as key in predictions.json,
        e.g. "Bus 12\\16.csv".  Must match what was passed to save_predictions.

    Returns
    -------
    dict  with keys:
        scenario_path   str
        actual          dict  — KPIs computed by compute_kpis()
        predicted       dict  — values stored by save_predictions()
        comparison       dict  — per-field error / correctness metrics:
            severity_score:  {actual, predicted, abs_error, rel_error_pct}
            stable:          {actual, predicted, correct}
            vmax_aft:        {actual, predicted, abs_error_pu}
            vmin_aft:        {actual, predicted, abs_error_pu}
            bus_vmax:        {actual, predicted, correct}
            bus_vmin:        {actual, predicted, correct}

        'actual' for bus_vmax/bus_vmin is a list, because several buses can tie
        for the extreme value; 'correct' is True when the predicted bus is one
        of them, and None when either side is unavailable.
        error           str   — set if anything went wrong, other keys absent
    """
    # ── load predictions ──────────────────────────────────────────
    if not os.path.exists(_PREDICTIONS_PATH):
        return {"error": "predictions.json not found. Call save_predictions() first."}
    with open(_PREDICTIONS_PATH, "r", encoding="utf-8") as fh:
        record = json.load(fh)

    key = scenario_path.replace("/", "\\").replace("\\\\", "\\")
    pred = next(
        (p for p in record.get("predictions", [])
         if p.get("scenario_path", "").replace("/", "\\").replace("\\\\", "\\") == key),
        None,
    )
    if pred is None:
        return {"error": f"No prediction found for '{scenario_path}' in predictions.json"}

    # ── compute actual KPIs ───────────────────────────────────────
    if not os.path.exists(csv_path):
        return {"error": f"CSV not found: {csv_path}"}
    try:
        actual = compute_kpis(csv_path)
    except Exception as exc:
        return {"error": f"compute_kpis failed: {exc}"}

    # ── build comparison ──────────────────────────────────────────
    def _rel_err(actual_val, pred_val):
        if actual_val and actual_val != 0:
            return round(abs(actual_val - pred_val) / abs(actual_val) * 100, 2)
        return None

    def _bus_match(actual_buses, predicted_bus):
        """
        True if the predicted bus name is among the buses that actually hit the
        extreme. compute_kpis returns a list because several buses can tie.
        """
        if not actual_buses or not predicted_bus:
            return None
        norm = lambda s: " ".join(str(s).split()).casefold()
        return norm(predicted_bus) in {norm(b) for b in actual_buses}

    a_sev   = actual.get("severity_score") or actual.get("severity", {}).get("score")
    a_stable = int(actual.get("stable", 1))
    a_vmax  = actual.get("vmax_aft")
    a_vmin  = actual.get("vmin_aft")
    a_bvmax = actual.get("vmax_aft_bus", [])
    a_bvmin = actual.get("vmin_aft_bus", [])

    p_sev   = pred.get("severity_score")
    p_stable = pred.get("stable")
    p_vmax  = pred.get("vmax_aft")
    p_vmin  = pred.get("vmin_aft")
    p_bvmax = pred.get("bus_vmax", "unknown")
    p_bvmin = pred.get("bus_vmin", "unknown")

    comparison = {
        "severity_score": {
            "actual": a_sev,
            "predicted": p_sev,
            "abs_error": round(abs(a_sev - p_sev), 4) if (a_sev is not None and p_sev is not None) else None,
            "rel_error_pct": _rel_err(a_sev, p_sev),
        },
        "stable": {
            "actual": bool(a_stable),
            "predicted": bool(p_stable),
            "correct": bool(a_stable) == bool(p_stable),
        },
        "vmax_aft": {
            "actual": a_vmax,
            "predicted": p_vmax,
            "abs_error_pu": round(abs(a_vmax - p_vmax), 4) if (a_vmax is not None and p_vmax is not None) else None,
        },
        "vmin_aft": {
            "actual": a_vmin,
            "predicted": p_vmin,
            "abs_error_pu": round(abs(a_vmin - p_vmin), 4) if (a_vmin is not None and p_vmin is not None) else None,
        },
        "bus_vmax": {
            "actual": a_bvmax,
            "predicted": p_bvmax,
            "correct": _bus_match(a_bvmax, p_bvmax),
        },
        "bus_vmin": {
            "actual": a_bvmin,
            "predicted": p_bvmin,
            "correct": _bus_match(a_bvmin, p_bvmin),
        },
    }

    return {
        "scenario_path": scenario_path,
        "actual": actual,
        "predicted": pred,
        "comparison": comparison,
    }


# ══════════════════════════════════════════════════════════════════
# POWERFACTORY TOOLS
# ══════════════════════════════════════════════════════════════════

@mcp.tool()
def ping() -> str:
    """Returns pong. Use this to verify the MCP server is reachable."""
    return "pong"


@mcp.tool()
def close_digsilent() -> str:
    """
    Close the DIgSILENT PowerFactory API session.

    Calls DIgSILENTAgent.close(), which executes app.Exit() and clears
    shared handles in the current Python process.

    Returns
    -------
    str
        JSON string with success flag and message.
    """
    _, DIgSILENTAgent = _load_modules()

    def _impl():
        DIgSILENTAgent.close()
        return {"success": True, "message": "DIgSILENT API closed"}

    return _to_json(_pf(_impl))


@mcp.tool()
def get_config(cfg_path: str = "") -> str:
    """Return the active simulation_config.json as a JSON string."""
    path = cfg_path or _DEFAULT_CFG
    with open(path, "r", encoding="utf-8") as fh:
        return json.dumps(json.load(fh), indent=2, ensure_ascii=False)


@mcp.tool()
def import_project(
    file_path: str,
    open_digsilent: bool = True,
) -> str:
    """
    Import a DIgSILENT PowerFactory project from a .pfd file and activate it.

    PowerFactory must be running before calling this tool. After a successful
    import the project is immediately active and ready for simulation.

    Parameters
    ----------
    file_path : str
        Absolute path to the .pfd export file.
    open_digsilent : bool
        If True (default), requests the PowerFactory GUI window via app.Show().

    Returns
    -------
    str
        JSON string with success flag and message.
    """
    _, DIgSILENTAgent = _load_modules()
    ok, msg = _pf(DIgSILENTAgent.import_project, file_path, open_digsilent)
    return json.dumps({"success": ok, "message": msg})


@mcp.tool()
def create_study_case(
    case_name: str,
    base_study_case: str = "0. Base",
    open_digsilent: bool = True,
    request_id: str = "",
    cfg_path: str = "",
) -> str:
    """
    Create and activate a study case without running RMS simulation.

    Parameters
    ----------
    case_name : str
        Name of the target study case to create/activate.
    base_study_case : str
        Name of the source study case used when case_name does not exist (default: "0. Base").
    open_digsilent : bool
        If True (default), requests the PowerFactory GUI window via app.Show().
    request_id : str
        Optional idempotency key. If repeated, the server returns the
        cached result and does not execute the action again.
    cfg_path : str, optional
        Path to simulation_config.json used to read project_path.

    Returns
    -------
    str
        JSON string with success flag and message.
    """
    SimulationConfig, DIgSILENTAgent = _load_modules()
    path = cfg_path or _DEFAULT_CFG
    cfg = SimulationConfig.from_json(path)
    ok, msg = _pf(
        DIgSILENTAgent.create_study_case,
        cfg.project_path,
        case_name,
        base_study_case,
        open_digsilent,
        request_id,
    )
    return json.dumps({"success": ok, "message": msg})


@mcp.tool()
def modify_parameter(
    object_name: str,
    variable: str,
    new_value: Any,
    open_digsilent: bool = True,
) -> str:
    """
    Modify a PowerFactory attribute for all objects matching object_name.

    Parameters
    ----------
    object_name : str
        Query passed to app.GetCalcRelevantObjects (example: "G 10.ElmSym").
    variable : str
        Attribute name to update (example: "e:outserv").
    new_value : Any
        New value to write with SetAttribute.
    open_digsilent : bool
        If True (default), requests the PowerFactory GUI window via app.Show().

    Returns
    -------
    str
        JSON string with success flag and message.
    """
    _, DIgSILENTAgent = _load_modules()
    ok, msg = _pf(DIgSILENTAgent.modify_parameter, object_name, variable, new_value, open_digsilent)
    return json.dumps({"success": ok, "message": msg})


@mcp.tool()
def run_loadflow(
    open_digsilent: bool = True,
    save_csv: bool = False,
    cfg_path: str = "",
) -> str:
    """
    Run a load flow calculation (ComLdf) on the currently active study case.

    Parameters
    ----------
    open_digsilent : bool
        If True (default), requests the PowerFactory GUI window via app.Show().
    save_csv : bool
        If True, exports a load-flow snapshot CSV (buses, generators, loads, lines).
        Default: False.
    cfg_path : str, optional
        Path to simulation_config.json used for output_dir/run_label when save_csv=True.

    Returns
    -------
    str
        JSON string with success flag and message.
    """
    SimulationConfig, DIgSILENTAgent = _load_modules()

    output_dir = r"C:\RMS_Results"
    run_label = "run_001"
    if save_csv:
        path = cfg_path or _DEFAULT_CFG
        try:
            cfg = SimulationConfig.from_json(path)
            output_dir = getattr(cfg, "output_dir", output_dir) or output_dir
            run_label = getattr(cfg, "run_label", run_label) or run_label
        except Exception as e:
            return json.dumps({"success": False, "message": f"Could not read config for CSV export: {e}"})

    ok, msg = _pf(DIgSILENTAgent.load_flow, open_digsilent, save_csv, output_dir, run_label)
    return json.dumps({"success": ok, "message": msg})


@mcp.tool()
def run_short_circuit(open_digsilent: bool = True) -> str:
    """
    Run a short-circuit calculation (ComShc) on the currently active study case.

    Parameters
    ----------
    open_digsilent : bool
        If True (default), requests the PowerFactory GUI window via app.Show().

    Returns
    -------
    str
        JSON string with success flag and message.
    """
    _, DIgSILENTAgent = _load_modules()
    ok, msg = _pf(DIgSILENTAgent.short_circuit, open_digsilent)
    return json.dumps({"success": ok, "message": msg})


@mcp.tool()
def run_simulation(
    cfg_path: str = "",
    export_pfd: bool = False,
    open_digsilent: bool = True,
) -> str:
    """
    Run the full DIgSILENT PowerFactory RMS simulation pipeline.

    Steps: connect → activate study case → load flow → RMS simulation
           → CSV export → standard plots → optional PFD export.

    All parameters are read from simulation_config.json.

    Parameters
    ----------
    cfg_path : str, optional
        Absolute path to simulation_config.json. Defaults to the file
        next to this server script.
    export_pfd : bool, optional
        If True, a .pfd export is created in output_dir after CSV export.
    open_digsilent : bool, optional
        If True (default), requests the PowerFactory GUI window via app.Show().

    Returns
    -------
    str
        JSON string with success flag, csv_path, optional pfd_path,
        and per-step status.
    """
    SimulationConfig, DIgSILENTAgent = _load_modules()
    path = cfg_path or _DEFAULT_CFG
    cfg = SimulationConfig.from_json(path)
    cfg.export_pfd = 1 if export_pfd else 0
    cfg.open_digsilent = 1 if open_digsilent else 0

    def _impl():
        agent = DIgSILENTAgent(cfg)
        return agent.run_pipeline()

    return _to_json(_pf(_impl))


@mcp.tool()
def run_custom_case(
    fault_type: str,
    fault_element: str,
    t_fault: float,
    t_clear: float,
    t_end: float = 10.0,
    dt_rms: float = 0.01,
    case_name: str = "Custom_Case",
    switch_element: str = "",
    t_switch: float = 0.0,
    switch_state: int = 0,
    create_new_study_case: bool = False,
    export_pfd: bool = False,
    open_digsilent: bool = True,
    cfg_path: str = "",
) -> str:
    """
    Run a single custom fault case with parameters supplied at call-time.

    Network settings (project path, output directory, signals) are read from
    simulation_config.json; only the fault scenario parameters are overridden
    by the arguments provided here.

    Parameters
    ----------
    fault_type : str
        One of: "bus", "line", "gen_switch" (alias: "generator").
    fault_element : str
        Name of the faulted bus or line element in PowerFactory.
    t_fault : float
        Fault inception time in seconds.
    t_clear : float
        Fault clearing time in seconds.
    t_end : float
        Simulation end time in seconds (default 10.0).
    dt_rms : float
        RMS simulation step size in seconds (default 0.01).
    case_name : str
        Label used for output files and sub-folder name.
    switch_element : str
        Circuit-breaker or switch to operate for gen_switch faults.
    t_switch : float
        Time to operate the switch (defaults to t_fault when 0).
    switch_state : int
        Target switch state: 0 = open/trip, 1 = close.
    create_new_study_case : bool
        If True, creates a new timestamped study case on each call.
        If False (default), reuses case_name as the study case name.
    export_pfd : bool
        If True, a .pfd export is created in output_dir after CSV export.
    open_digsilent : bool
        If True (default), requests the PowerFactory GUI window via app.Show().
    cfg_path : str, optional
        Absolute path to simulation_config.json for network settings.

    Returns
    -------
    str
        JSON string with pipeline result (same schema as run_simulation).
    """
    SimulationConfig, DIgSILENTAgent = _load_modules()
    path = cfg_path or _DEFAULT_CFG
    cfg = SimulationConfig.from_json(path)

    if create_new_study_case:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        cfg.study_case = f"{case_name}_{ts}"
    else:
        cfg.study_case = case_name

    cfg.fault_type     = fault_type
    cfg.fault_element  = fault_element
    cfg.t_fault        = t_fault
    cfg.t_clear        = t_clear
    cfg.t_end          = t_end
    cfg.dt_rms         = dt_rms
    cfg.run_label      = case_name
    cfg.switch_element = switch_element
    cfg.t_switch       = t_switch or t_fault
    cfg.switch_state   = switch_state
    cfg.export_pfd     = 1 if export_pfd else 0
    cfg.open_digsilent = 1 if open_digsilent else 0

    def _impl():
        agent = DIgSILENTAgent(cfg)
        return agent.run_pipeline()

    return _to_json(_pf(_impl))


@mcp.tool()
def read_results_csv(
    csv_path: str = "",
    max_rows: int = 2000,
    as_path: bool = False,
    max_bytes: int = 900_000,
) -> str:
    """
    Read the RMS simulation results CSV and return its contents.

    If csv_path is not provided, the most recently modified *_RMS.csv file
    found anywhere inside the configured output_dir is used automatically.

    Parameters
    ----------
    csv_path : str, optional
        Absolute path to a specific _RMS.csv file. If omitted, the latest
        file in output_dir is used.
    max_rows : int, optional
        Maximum number of data rows to return (default 2000).
    as_path : bool, optional
        If True, return a small JSON object containing the absolute file
        path instead of the file contents.
    max_bytes : int, optional
        If > 0, the returned CSV text will be truncated to at most
        max_bytes bytes (UTF-8 encoded). Truncation happens at row
        boundaries when possible.

    Returns
    -------
    str
        CSV text (header + up to max_rows rows) followed by metadata lines
        with file path, total rows, and truncation flag.
    """
    if csv_path:
        target = csv_path
    else:
        with open(_DEFAULT_CFG, "r", encoding="utf-8") as fh:
            cfg_data = json.load(fh)
        base_dir = cfg_data.get("output_dir", BENCHMARK_DIR)
        # A relative output_dir in the config is relative to the repository.
        if not os.path.isabs(base_dir):
            base_dir = os.path.join(CONFIG_DIR, base_dir)

        candidates = []
        for root, _, files in os.walk(base_dir):
            for fname in files:
                if fname.endswith("_RMS.csv"):
                    full = os.path.join(root, fname)
                    candidates.append((os.path.getmtime(full), full))

        if not candidates:
            return json.dumps({"error": f"No *_RMS.csv files found under {base_dir}"})
        candidates.sort(reverse=True)
        target = candidates[0][1]

    if not os.path.exists(target):
        return json.dumps({"error": f"File not found: {target}"})

    if as_path:
        return json.dumps({"file_path": target})

    with open(target, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()

    header_idx = 0
    for i, line in enumerate(lines):
        if ";" in line or "," in line:
            header_idx = i
            break

    header_line = lines[header_idx] if lines else ""
    data_lines = lines[header_idx + 1:]
    total_rows = len(data_lines)

    data_lines = data_lines[:max_rows]
    rows_returned = len(data_lines)
    truncated = total_rows > rows_returned

    if max_bytes and max_bytes > 0:
        out_bytes = bytearray()
        hb = header_line.encode("utf-8", errors="replace")
        if len(hb) >= max_bytes:
            out_bytes.extend(hb[:max_bytes])
            csv_text = out_bytes.decode("utf-8", errors="replace")
            meta = (
                f"\n# file: {target}\n"
                f"# total_data_rows: {total_rows}\n"
                f"# rows_returned: 0\n"
                f"# truncated_by_size: True\n"
            )
            return csv_text + meta
        out_bytes.extend(hb)

        rows_emitted = 0
        for line in data_lines:
            lb = line.encode("utf-8", errors="replace")
            if len(out_bytes) + len(lb) > max_bytes:
                break
            out_bytes.extend(lb)
            rows_emitted += 1

        csv_text = out_bytes.decode("utf-8", errors="replace")
        meta = (
            f"\n# file: {target}\n"
            f"# total_data_rows: {total_rows}\n"
            f"# rows_returned: {rows_emitted}\n"
            f"# truncated_by_size: {len(out_bytes) >= max_bytes}\n"
        )
        return csv_text + meta

    csv_text = header_line + "".join(data_lines)
    meta = (
        f"\n# file: {target}\n"
        f"# total_data_rows: {total_rows}\n"
        f"# rows_returned: {rows_returned}\n"
        f"# truncated: {truncated}\n"
    )
    return csv_text + meta


# ── Entry point ────────────────────────────────────────────────────

if __name__ == "__main__":
    transport = "stdio"
    if "--transport" in sys.argv:
        idx = sys.argv.index("--transport")
        if idx + 1 < len(sys.argv):
            transport = sys.argv[idx + 1]
    print(f"[MCP] Starting server (transport={transport})", file=sys.stderr)
    mcp.run(transport=transport)
