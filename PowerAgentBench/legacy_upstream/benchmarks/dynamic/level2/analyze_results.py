"""
Aggregate the batch KPI results per fault location and print the most
vulnerable buses.

Input : all_kpis.json  — produced by `python batch_kpi_analysis.py`
Usage : python analyze_results.py
"""
__author__ = "Andrea Pomarico"

import json
import statistics
import sys
from collections import defaultdict

from config import REPO_DIR

ALL_KPIS_PATH = REPO_DIR / "all_kpis.json"

if not ALL_KPIS_PATH.exists():
    sys.exit(
        f"{ALL_KPIS_PATH} not found.\n"
        "Generate it first with:  python batch_kpi_analysis.py"
    )

with open(ALL_KPIS_PATH, encoding="utf-8") as f:
    data = json.load(f)

bus_data = defaultdict(list)
for r in data:
    bus_data[r["bus"]].append(r)

print(f"{'Bus':<10} {'N':>3} {'vloSC_avg':>10} {'vhiAFT_avg':>10} {'vloAFT_avg':>10} {'vmax_avg':>9} {'vmin_avg':>9} {'vmax_max':>9} {'vmin_min':>9}")
print("-" * 92)

rows = []
for bus in sorted(bus_data.keys()):
    recs = bus_data[bus]
    n = len(recs)
    vlo_sc   = [r["buses_vlo_sc"]  for r in recs]
    vhi_aft  = [r["buses_vhi_aft"] for r in recs]
    vlo_aft  = [r["buses_vlo_aft"] for r in recs]
    vmax_aft = [r["vmax_aft"] for r in recs if r.get("vmax_aft") is not None]
    vmin_aft = [r["vmin_aft"] for r in recs if r.get("vmin_aft") is not None]

    row = {
        "bus":         bus,
        "n":           n,
        "vlo_sc_avg":  round(statistics.mean(vlo_sc), 2),
        "vhi_aft_avg": round(statistics.mean(vhi_aft), 2),
        "vlo_aft_avg": round(statistics.mean(vlo_aft), 2),
        "vmax_avg":    round(statistics.mean(vmax_aft), 4) if vmax_aft else None,
        "vmin_avg":    round(statistics.mean(vmin_aft), 4) if vmin_aft else None,
        "vmax_max":    round(max(vmax_aft), 4) if vmax_aft else None,
        "vmin_min":    round(min(vmin_aft), 4) if vmin_aft else None,
    }
    rows.append(row)
    print(f"{bus:<10} {n:>3} {row['vlo_sc_avg']:>10} {row['vhi_aft_avg']:>10} {row['vlo_aft_avg']:>10} "
          f"{str(row['vmax_avg']):>9} {str(row['vmin_avg']):>9} {str(row['vmax_max']):>9} {str(row['vmin_min']):>9}")

print()
print("=" * 92)
print("TOP 10 BUS PIU VULNERABILI - SOTTOTENSIONE DOPO CORTO CIRCUITO (vlo_aft_avg)")
print("=" * 92)
top_underv = sorted(rows, key=lambda x: (-x["vlo_aft_avg"], x["vmin_min"] if x["vmin_min"] else 1))
for i, r in enumerate(top_underv[:10], 1):
    print(f"  {i:2}. {r['bus']}  vlo_aft_avg={r['vlo_aft_avg']:6}  vmin_min={r['vmin_min']}  vmin_avg={r['vmin_avg']}")

print()
print("=" * 92)
print("TOP 10 BUS PIU VULNERABILI - SOVRATENSIONE DOPO CORTO CIRCUITO (vhi_aft_avg)")
print("=" * 92)
top_overv = sorted(rows, key=lambda x: (-x["vhi_aft_avg"], -(x["vmax_max"] if x["vmax_max"] else 0)))
for i, r in enumerate(top_overv[:10], 1):
    print(f"  {i:2}. {r['bus']}  vhi_aft_avg={r['vhi_aft_avg']:6}  vmax_max={r['vmax_max']}  vmax_avg={r['vmax_avg']}")

print()
print("=" * 92)
print("TOP 10 BUS PIU VULNERABILI - SOTTOTENSIONE DURANTE CORTO CIRCUITO (vlo_sc_avg)")
print("=" * 92)
top_sc = sorted(rows, key=lambda x: -x["vlo_sc_avg"])
for i, r in enumerate(top_sc[:10], 1):
    print(f"  {i:2}. {r['bus']}  vlo_sc_avg={r['vlo_sc_avg']:6}  vmin_min={r['vmin_min']}")

# Calcola anche il peggior CSV in assoluto per sottotensione e sovratensione
print()
print("=" * 92)
print("CASO PEGGIORE ASSOLUTO - SOTTOTENSIONE (vmin_aft minimo)")
worst_under = sorted(data, key=lambda x: x.get("vmin_aft") or 999)
for r in worst_under[:5]:
    print(f"  {r['bus']} / {r['csv']}  vmin_aft={r['vmin_aft']}  buses_vlo_aft={r['buses_vlo_aft']}  sc_win={r['sc_win']}")

print()
print("=" * 92)
print("CASO PEGGIORE ASSOLUTO - SOVRATENSIONE (vmax_aft massimo)")
worst_over = sorted(data, key=lambda x: -(x.get("vmax_aft") or 0))
for r in worst_over[:5]:
    print(f"  {r['bus']} / {r['csv']}  vmax_aft={r['vmax_aft']}  buses_vhi_aft={r['buses_vhi_aft']}  sc_win={r['sc_win']}")
