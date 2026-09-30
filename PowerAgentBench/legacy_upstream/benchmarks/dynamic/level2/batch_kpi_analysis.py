"""
Batch KPI analysis: run compute_kpis for every 'Bus XX / YY.csv' combination
in the dataset and save a consolidated JSON + CSV summary.

Note: only bus faults are aggregated here; line-fault folders are skipped.

Input  : <DATA_DIR>/Bus XX/<cycles>.csv
Outputs: all_kpis.json, all_kpis_summary.csv  (next to the code)
Usage  : python batch_kpi_analysis.py
"""
__author__ = "Andrea Pomarico"

import os, json, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compute_kpis import compute_kpis
from config import DATA_DIR, REPO_DIR

BENCHMARK_DIR = str(DATA_DIR)
FAULT_DURATIONS = list(range(2, 21))   # fault duration in cycles (filename stem)

results = []
errors  = []

bus_dirs = sorted(
    d for d in os.listdir(BENCHMARK_DIR)
    if d.startswith("Bus ") and os.path.isdir(os.path.join(BENCHMARK_DIR, d))
)
if not bus_dirs:
    sys.exit(
        f"No 'Bus XX' folders found under {BENCHMARK_DIR}.\n"
        "Point the BENCHMARK_DATA_DIR environment variable at your dataset."
    )

total = len(bus_dirs) * len(FAULT_DURATIONS)
done  = 0

for bus_dir in bus_dirs:
    for dur in FAULT_DURATIONS:
        csv_rel  = os.path.join(bus_dir, f"{dur}.csv")
        csv_full = os.path.join(BENCHMARK_DIR, csv_rel)
        done += 1
        if not os.path.exists(csv_full):
            errors.append(csv_rel)
            continue
        try:
            kpi = compute_kpis(csv_full)
            kpi["bus"]      = bus_dir
            kpi["duration_cycles"] = dur
            results.append(kpi)
            print(f"[{done:4d}/{total}] OK  {csv_rel}")
        except Exception as e:
            errors.append(f"{csv_rel}: {e}")
            print(f"[{done:4d}/{total}] ERR {csv_rel}: {e}")

# Save full JSON
out_json = os.path.join(REPO_DIR, "all_kpis.json")
with open(out_json, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

# Save flat CSV summary
import csv as csv_mod
out_csv = os.path.join(REPO_DIR, "all_kpis_summary.csv")
fields = [
    "bus", "duration_cycles", "sc_win",
    "buses_vlo_sc",
    "buses_vhi_aft", "vmax_aft",
    "buses_vlo_aft", "vmin_aft",
    "spmax_aft", "spmin_aft", "stable", "severity_score",
    "buses_vhi_aft_names", "buses_vlo_aft_names",
]
with open(out_csv, "w", newline="", encoding="utf-8") as f:
    w = csv_mod.DictWriter(f, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for r in results:
        row = {k: r.get(k, "") for k in fields}
        row["sc_win"] = f"{r['sc_win'][0]}-{r['sc_win'][1]}"
        row["buses_vhi_aft_names"] = "; ".join(r.get("buses_vhi_aft_names", []))
        row["buses_vlo_aft_names"] = "; ".join(r.get("buses_vlo_aft_names", []))
        w.writerow(row)

print(f"\nDone. {len(results)} analyses saved.")
print(f"  -> {out_json}")
print(f"  -> {out_csv}")
if errors:
    print(f"\nMissing / errors ({len(errors)}):")
    for e in errors:
        print(f"  {e}")
