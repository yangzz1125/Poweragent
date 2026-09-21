# IEEE 39-Bus Transient Stability — Agent KPI Benchmark

A benchmark for measuring whether an LLM agent can **predict the severity of an
unseen short-circuit fault** on the IEEE 39-bus New England system by reasoning
over a memory of previously simulated faults — and then check that prediction
against a ground-truth RMS simulation run in DIgSILENT PowerFactory.

The whole benchmark is exposed to the agent as a single **MCP server**, so the
agent can retrieve past scenarios, commit to a numeric prediction, run the real
simulation, and be scored on the difference.

---

## 1. The idea

Every scenario is one short-circuit fault, identified by **where** it happens
(a bus or a line) and **how long** it lasts. Each simulated scenario is reduced
to a small set of KPIs and a scalar **severity score** in `[0, 1]`.

The dataset is split into a **training memory** (~584 scenarios) and a held-out
**test memory** (~146 scenarios). The agent may look at the training memory
freely; the test scenarios are what it has to predict.

```
                    ┌──────────────────────────┐
                    │  simulation CSVs         │   DATA_DIR
                    │  Bus 01/2.csv, 4.csv …   │   (not in this repo)
                    └───────────┬──────────────┘
                                │ compute_kpis.py
                                ▼
                    ┌──────────────────────────┐
                    │  KPIs + severity score   │
                    └───────────┬──────────────┘
                                │ semantic_memory.py build
                                ▼
        ┌────────────────────────────────────────────────┐
        │  semantic_memory.{json,npz}   ← training split  │
        │  test_memory.{json,npz}       ← held-out split  │
        │  memory_split.txt             ← which is which  │
        └───────────────────────┬────────────────────────┘
                                │ kpi_mcp_server.py  (MCP)
                                ▼
        ┌────────────────────────────────────────────────┐
        │  LLM agent                                     │
        │   1. read_memory_split   → pick a test case    │
        │   2. get_training_history / query_semantic_…   │
        │   3. save_predictions    → commit, then freeze  │
        │   4. run_simulation      → PowerFactory truth   │
        │   5. evaluate_predictions → scored              │
        └────────────────────────────────────────────────┘
```

Step 3 is the point of the whole design: the prediction is **written to disk
before** the ground truth is computed, so the agent cannot silently revise it.

---

## 2. The severity score

Computed by `severity_iov()` in [`compute_kpis.py`](compute_kpis.py) using an
**Integral of Violation (IoV)** over the post-fault recovery window (from
`fault_end + after_extra` to the end of the simulation).

For every bus and every timestep the voltage violation is normalised to `[0, 1]`:

| | violation starts at | saturates at 1.0 at |
|---|---|---|
| under-voltage | 0.95 pu | 0.90 pu |
| over-voltage | 1.05 pu | 1.10 pu |

Each is integrated over time, normalised by the window length, then averaged
across all buses, giving `s_undervolt` and `s_overvolt`. Then:

```
if any generator speed > 1.05 pu   →  score = 1.0        (loss of synchronism)
else                               →  score = 0.5 · s_undervolt + 0.5 · s_overvolt
```

So **1.0 means unstable**, and anything below is a graded voltage-quality
penalty. `stable` is reported separately as a 0/1 flag.

---

## 3. Repository layout

| Path | Role |
|---|---|
| [`kpi_mcp_server.py`](kpi_mcp_server.py) | **Entry point.** MCP server exposing all 22 tools (KPI + PowerFactory). |
| [`compute_kpis.py`](compute_kpis.py) | KPI engine and severity score. Importable and runnable as a CLI. |
| [`semantic_memory.py`](semantic_memory.py) | Builds and queries the embedded scenario memory; also produces the train/test split. |
| [`Agent_DIgSILENT.py`](Agent_DIgSILENT.py) | PowerFactory driver: study cases, fault events, RMS run, CSV export. |
| [`config.py`](config.py) | Single place where all paths are resolved. |
| [`batch_kpi_analysis.py`](batch_kpi_analysis.py) | Offline: KPIs for every bus-fault CSV → `all_kpis.json`. |
| [`analyze_results.py`](analyze_results.py) | Offline: ranks the most vulnerable buses from `all_kpis.json`. |
| [`agent_scenario_ranker.py`](agent_scenario_ranker.py) | Standalone baseline: one-shot LLM ranking of 10 test scenarios, no MCP. |
| `semantic_memory.{json,npz}` | Prebuilt training memory — **shipped**, so you can use the benchmark without the raw dataset. |
| `test_memory.{json,npz}` | Prebuilt held-out test memory. |
| [`memory_split.txt`](memory_split.txt) | Human-readable listing of the split. |
| [`simulation_config.json`](simulation_config.json) | PowerFactory project, study case and fault cases. |
| [`ranker_config.json`](ranker_config.json) | Provider/model and test scenarios for the standalone ranker. |
| [`examples/`](examples/) | Sample `kpi_report.json` and `predictions.json` showing the output shapes. |
| [`data/`](data/README.md) | Where the simulation CSVs go — see that README for the expected format. |

---

## 4. Setup

### 4.1 Requirements

- **Python 3.11+** (developed on 3.13).
- **DIgSILENT PowerFactory** — *only* if you want to run new simulations.
  All KPI analysis and memory querying works on existing CSVs without it.
- An **LLM provider key** — only for `agent_scenario_ranker.py`. The MCP
  workflow uses whatever agent you connect (e.g. Claude Code), so it needs no
  key of its own.

### 4.2 Install

```bash
git clone <your-repo-url>
cd <repo>
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux / macOS
pip install -r requirements.txt
```

> `sentence-transformers` pulls in PyTorch (~2 GB). It is required to **build**
> the memory and to use the `query_semantic_memory` tool. If you only need the
> KPI tools and the structured lookups (`get_training_history`,
> `lookup_scenarios`, `read_memory_split`), you can skip it — those read the
> shipped JSON directly and do not import it.

### 4.3 Configure

Copy `.env.example` and export the variables you need in your shell — the
project reads plain environment variables and does not auto-load `.env`:

```powershell
# PowerShell
$env:BENCHMARK_DATA_DIR = "C:\path\to\IEEE39_dataset"
$env:POWERFACTORY_PYTHON_PATH = "C:\Program Files\DIgSILENT\PowerFactory 2025 SP1\Python\3.13"
```

```bash
# bash
export BENCHMARK_DATA_DIR="/path/to/IEEE39_dataset"
```

| Variable | Needed for | Default |
|---|---|---|
| `BENCHMARK_DATA_DIR` | anything touching the raw CSVs | `./data`, else the repo root |
| `POWERFACTORY_PYTHON_PATH` | running simulations | the PowerFactory 2025 SP1 / Python 3.13 path |
| `GROQ_API_KEY` / `GEMINI_API_KEY` | `agent_scenario_ranker.py` only | — |
| `LLM_PROVIDER` | `agent_scenario_ranker.py` only | `groq` |

Check what got resolved:

```bash
python config.py
```

`POWERFACTORY_PYTHON_PATH` must point at the Python folder matching **the
interpreter you run this project with** — PowerFactory ships one subfolder per
supported Python version, and importing the wrong one fails.

---

## 5. Running it

### Path A — KPI analysis only (no PowerFactory, no LLM)

```bash
python compute_kpis.py "Bus 01/10.csv"       # one scenario
python batch_kpi_analysis.py                 # all bus faults → all_kpis.json
python analyze_results.py                    # most vulnerable buses
```

### Path B — the agent benchmark (the main use)

1. Start your MCP client in this directory. [`.mcp.json`](.mcp.json) already
   declares the server:

   ```json
   { "mcpServers": { "kpi-benchmark": {
       "type": "stdio", "command": "python", "args": ["kpi_mcp_server.py"] } } }
   ```

   With Claude Code, `cd` into the repo and start it — the server is picked up
   automatically. If your client launches servers from a different working
   directory, replace `"kpi_mcp_server.py"` with an absolute path.

2. Verify the connection with the `ping` tool.

3. Drive the agent through the five steps in
   [`CLAUDE.md`](CLAUDE.md), which is the operating protocol for the benchmark
   (pick a test scenario → study the training history → commit predictions →
   simulate → evaluate).

### Path C — standalone LLM ranker (no MCP)

```bash
export GROQ_API_KEY="gsk_..."
python agent_scenario_ranker.py ranker_config.json
python agent_scenario_ranker.py --list        # what's in the memory
```

Writes a timestamped JSON + CSV ranking into `ranking_results/`.

### Rebuilding the memory

Only needed if you change the KPI definition or use your own dataset:

```bash
python semantic_memory.py build --min-cycles 2 --max-cycles 20 --step 2 \
                                --test-fraction 0.2 --seed 42
python semantic_memory.py query "voltage collapse after a long fault" --top-k 5
```

This **overwrites** `semantic_memory.*`, `test_memory.*` and `memory_split.txt`,
which invalidates any earlier results. Pass `--seed` to make the split
reproducible.

---

## 6. MCP tool reference

**Benchmark / KPI**

| Tool | Purpose |
|---|---|
| `read_memory_split` | Train/test scenario lists from `memory_split.txt`. |
| `lookup_scenarios` | Full memory entries for specific CSV paths. |
| `get_training_history` | All training KPIs for one location, ordered by duration. |
| `get_location_history` | All memory entries for one location, any duration. |
| `query_semantic_memory` | Natural-language similarity search (needs sentence-transformers). |
| `list_csv_files` | Every CSV in the dataset. |
| `run_kpis` | Compute KPIs for a CSV → `kpi_report.json`. |
| `read_kpi_report` | Last saved report. |
| `save_predictions` | **Commit** predictions before simulating. |
| `evaluate_predictions` | Predicted vs. actual, per scenario. |
| `read_ranker_config` | Read a JSON config from the repo. |

**PowerFactory**

| Tool | Purpose |
|---|---|
| `ping` / `close_digsilent` | Connectivity, session teardown. |
| `get_config` | Active `simulation_config.json`. |
| `import_project` | Import and activate a `.pfd`. |
| `create_study_case` | Create/activate a study case. |
| `modify_parameter` | Set an attribute on a PF object. |
| `run_loadflow` / `run_short_circuit` | Steady-state calculations. |
| `run_simulation` | Full pipeline from `simulation_config.json`. |
| `run_custom_case` | One-off case with call-time parameters. |
| `read_results_csv` | Read the latest (or a named) RMS result CSV. |

All PowerFactory calls are funnelled through one dedicated thread, because the
PowerFactory API requires every call to come from the thread that created the
session.
