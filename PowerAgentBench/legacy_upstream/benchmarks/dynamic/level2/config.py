"""
Central path configuration for the IEEE 39-bus transient-stability KPI benchmark.

Two directories matter and they are deliberately kept separate:

  REPO_DIR   the checked-out repository — holds the code and the prebuilt
             memory artifacts (semantic_memory.json/.npz, memory_split.txt).

  DATA_DIR   the simulation dataset — holds one folder per fault location
             ("Bus 01" … "Bus 39", "Line 01 - 02" …), each containing CSVs
             named after the fault duration in cycles ("2.csv", "4.csv", …).
             The dataset is large and is NOT shipped with the repository.

Resolution order for DATA_DIR:
  1. the BENCHMARK_DATA_DIR environment variable, if set;
  2. <REPO_DIR>/data, if it already contains Bus */Line * folders;
  3. REPO_DIR itself — the original layout, where the CSV folders sit
     directly next to the scripts.
"""

import os
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent

__author__ = "Andrea Pomarico"

#: Prefixes of the per-location folders that hold the simulation CSVs.
LOCATION_PREFIXES = ("Bus", "Line")


def _looks_like_dataset(path: Path) -> bool:
    """True if *path* contains at least one 'Bus …' or 'Line …' sub-folder."""
    if not path.is_dir():
        return False
    return any(
        child.is_dir() and child.name.startswith(LOCATION_PREFIXES)
        for child in path.iterdir()
    )


def resolve_data_dir() -> Path:
    """Return the directory holding the simulation CSV folders."""
    env = os.environ.get("BENCHMARK_DATA_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()

    local = REPO_DIR / "data"
    if _looks_like_dataset(local):
        return local

    return REPO_DIR


DATA_DIR = resolve_data_dir()

# ── Memory artifacts (always alongside the code, never in the dataset) ──
SEM_EMBEDDINGS_PATH = REPO_DIR / "semantic_memory.npz"
SEM_METADATA_PATH = REPO_DIR / "semantic_memory.json"
TEST_EMBEDDINGS_PATH = REPO_DIR / "test_memory.npz"
TEST_METADATA_PATH = REPO_DIR / "test_memory.json"
SPLIT_TXT_PATH = REPO_DIR / "memory_split.txt"

# ── Runtime outputs ────────────────────────────────────────────────────
REPORT_PATH = REPO_DIR / "kpi_report.json"
PREDICTIONS_PATH = REPO_DIR / "predictions.json"

#: Sentence-transformers model used to embed the KPI summaries.
EMBEDDING_MODEL = "all-MiniLM-L6-v2"


def describe() -> str:
    """Human-readable summary of the resolved paths — used by `--paths` flags."""
    return (
        f"REPO_DIR : {REPO_DIR}\n"
        f"DATA_DIR : {DATA_DIR}"
        f"{'' if _looks_like_dataset(DATA_DIR) else '   (no Bus */Line * folders found!)'}"
    )


if __name__ == "__main__":
    print(describe())
