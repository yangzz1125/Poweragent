"""
KPI engine for the IEEE 39-bus transient-stability benchmark.

Reads one RMS simulation CSV and returns the voltage / generator-speed KPIs
plus a scalar severity score (see severity_iov below).

Usage: python compute_kpis.py "Bus 01/10.csv" [--short-start 1.0] [--short-end 1.1]
"""
__author__ = "Andrea Pomarico"

import os
import json
import argparse
import pandas as pd

# Default CSV (relative to the dataset directory) when no CLI argument is given.
CSV_TO_READ = os.path.join('Bus 01', '10.csv')

# JSON key legend:
#   csv            source file
#   sc_win         short-circuit window [start, end] in seconds
#   skip_after     seconds skipped immediately after short_end before observation starts
#   buses_vlo_sc   buses with V < 0.9 pu during short circuit
#   buses_vhi_aft  buses with V > 1.05 pu in the recovery window
#   vmax_aft       max voltage in the recovery window (pu)
#   buses_vlo_aft  buses with V < underv_threshold pu in the recovery window
#   vmin_aft       min voltage in the recovery window (pu)
#   spmax_aft      max generator speed in the recovery window (pu)
#   spmin_aft      min generator speed in the recovery window (pu)
#   stable         1 = stable, 0 = unstable (any generator speed > 1.05 pu)
#   severity       detailed IoV severity breakdown (includes instability flag)
#   severity_score scalar final KPI score (higher = worse)
#
#   Recovery window: from (short_end + skip_after) to end of simulation.
#   severity_score uses the Integral of Violation (IoV) method:
#     - if is_unstable (any gen speed > 1.05 pu): score = 1.0 unconditionally
#     - otherwise: 0.5 * s_undervolt + 0.5 * s_overvolt  (both from IoV)




def severity_iov(
    va: pd.DataFrame,
    times_aft: pd.Series,
    is_unstable: bool = False,
    w_lo: float = 0.5,
    w_hi: float = 0.5,
    V_lo_threshold: float = 0.95,
    V_lo_floor: float = 0.90,
    V_hi_threshold: float = 1.05,
    V_hi_floor: float = 1.10,
) -> dict:
    """
    Integral of Violation (IoV) severity score con termine di instabilità.

    Per ogni bus e ogni timestep calcola la violazione di tensione normalizzata
    in [0, 1], la integra nel tempo e la media su tutti i bus.
    La finestra copre da (short_end + skip_after) alla fine della simulazione.

    Se is_unstable=True (almeno un generatore con speed > 1.05 pu nella recovery
    window), lo score è forzato a 1.0 indipendentemente dalle tensioni.
    """
    # Caso degenere: nessun dato di tensione disponibile
    if va.empty or times_aft.empty or len(times_aft) < 2:
        s_speed = 1.0 if is_unstable else 0.0
        return {
            "score": s_speed,               # 1.0 se instabile, 0.0 altrimenti
            "is_unstable": is_unstable,
            "s_undervolt": 0.0,
            "s_overvolt": 0.0,
            "s_speed": s_speed,
            "base_score": 0.0,
            "raw_kpis": {"vmin": None, "vmax": None},
        }

    # Δt tra campioni consecutivi (primo Δt = 0 per non duplicare l'area)
    dt = times_aft.diff().fillna(0).values          # shape (N,)
    T  = float(times_aft.iloc[-1] - times_aft.iloc[0])
    if T <= 0:
        T = 1.0  # guard contro finestre degeneri

    # Violazione normalizzata per ogni bus × timestep
    # sottotensione: quanto scende sotto V_lo_threshold, saturata a 1 a V_lo_floor
    viol_lo = (
        (V_lo_threshold - va.clip(upper=V_lo_threshold)).clip(lower=0)
        / (V_lo_threshold - V_lo_floor)
    )
    # sovratensione: quanto sale sopra V_hi_threshold, saturata a 1 a V_hi_floor
    viol_hi = (
        (va.clip(lower=V_hi_threshold) - V_hi_threshold).clip(lower=0)
        / (V_hi_floor - V_hi_threshold)
    )

    # Integrale nel tempo per ogni bus, normalizzato su T → [0, 1] per bus
    iov_lo_per_bus = (viol_lo.values * dt[:, None]).sum(axis=0) / T  # shape (B,)
    iov_hi_per_bus = (viol_hi.values * dt[:, None]).sum(axis=0) / T  # shape (B,)

    # Media su tutti i bus e clip finale
    s_lo = float(min(1.0, max(0.0, iov_lo_per_bus.mean())))
    s_hi = float(min(1.0, max(0.0, iov_hi_per_bus.mean())))

    base_score = w_lo * s_lo + w_hi * s_hi

    # Termine di instabilità: se almeno un generatore ha perso il sincronismo,
    # il sistema è instabile → score = 1.0 (caso peggiore, override)
    s_speed     = 1.0 if is_unstable else 0.0
    final_score = 1.0 if is_unstable else base_score

    return {
        "score": final_score,
        "is_unstable": is_unstable,
        "s_undervolt": s_lo,
        "s_overvolt": s_hi,
        "s_speed": s_speed,
        "base_score": base_score,
        "raw_kpis": {
            "vmin": _r(float(va.min().min())),
            "vmax": _r(float(va.max().max())),
        },
    }


def _r(v, decimals=4):
    """Round a float to reduce tokens; pass None through."""
    return round(v, decimals) if v is not None else None


def _bus_name(col):
    return col[0] if isinstance(col, tuple) else str(col)


def compute_kpis(csv_path, short_start=None, short_end=None, underv_threshold=0.95, after_extra=0.1):
    # Use sep=None and engine='python' to auto-detect the delimiter (comma or semicolon)
    df = pd.read_csv(csv_path, header=[0, 1], sep=None, engine='python')

    time_col = None
    for col in df.columns:
        if isinstance(col, tuple) and 'Time' in str(col[1]):
            time_col = col
            break
    if time_col is None:
        time_col = df.columns[0]

    if short_start is None:
        short_start = 1.0
    if short_end is None:
        base = os.path.splitext(os.path.basename(csv_path))[0]
        try:
            short_end = 1.0 + int(base) / 100.0
        except Exception:
            short_end = short_start + 0.02

    bus_cols = [c for c in df.columns if isinstance(c, tuple) and 'u1' in str(c[1])]
    speed_cols = [c for c in df.columns if isinstance(c, tuple) and 'Speed' in str(c[1])]

    times = df[time_col]
    short_mask    = (times >= short_start) & (times <= short_end)
    # Recovery window: salta i primi `after_extra` secondi dopo il fault,
    # poi osserva fino alla fine della simulazione.
    recovery_mask = times > (short_end + after_extra)

    r = {
        'csv':     os.path.basename(csv_path),
        'sc_win':  [_r(short_start), _r(short_end)],
        # 'aft_dur': _r(after_extra),
    }

    va        = pd.DataFrame()
    times_aft = pd.Series(dtype=float)

    if bus_cols:
        vs        = df.loc[short_mask,    bus_cols]
        va        = df.loc[recovery_mask, bus_cols]
        times_aft = times[recovery_mask].reset_index(drop=True)
        va        = va.reset_index(drop=True)

        vhi_mask = (va > 1.05).any(axis=0) if not va.empty else None
        vlo_mask = (va < underv_threshold).any(axis=0) if not va.empty else None
        r['buses_vlo_sc']  = int((vs < underv_threshold).any(axis=0).sum())
        r['buses_vhi_aft'] = int(vhi_mask.sum()) if vhi_mask is not None else 0
        r['buses_vhi_aft_names'] = [_bus_name(c) for c in va.columns[vhi_mask]] if vhi_mask is not None else []
        r['vmax_aft']      = _r(float(va.max().max())) if not va.empty else None
        r['vmax_aft_bus']  = [_bus_name(c) for c in va.columns if not va.empty and float(va[c].max()) == float(va.max().max())] if not va.empty else []
        r['buses_vlo_aft'] = int(vlo_mask.sum()) if vlo_mask is not None else 0
        r['buses_vlo_aft_names'] = [_bus_name(c) for c in va.columns[vlo_mask]] if vlo_mask is not None else []
        r['vmin_aft']      = _r(float(va.min().min())) if not va.empty else None
        r['vmin_aft_bus']  = [_bus_name(c) for c in va.columns if not va.empty and float(va[c].min()) == float(va.min().min())] if not va.empty else []
    else:
        r.update(
            buses_vlo_sc=0,
            buses_vhi_aft=0,
            buses_vhi_aft_names=[],
            vmax_aft=None,
            vmax_aft_bus=[],
            buses_vlo_aft=0,
            buses_vlo_aft_names=[],
            vmin_aft=None,
            vmin_aft_bus=[],
        )

    # Calcola statistiche di velocità dei generatori nella recovery window
    # e determina la stabilità (instabile se almeno uno supera 1.05 pu)
    is_unstable = False
    if speed_cols:
        sp = df.loc[recovery_mask, speed_cols].reset_index(drop=True)
        if not sp.empty:
            r['spmax_aft'] = _r(float(sp.max().max()))
            r['spmin_aft'] = _r(float(sp.min().min()))
            is_unstable    = bool((sp > 1.05).any().any())
        else:
            r.update(spmax_aft=None, spmin_aft=None)
    else:
        r.update(spmax_aft=None, spmin_aft=None)

    r['stable'] = int(not is_unstable)

    r['severity'] = severity_iov(va, times_aft, is_unstable=is_unstable)
    r['severity_score'] = _r(float(r['severity']['score']))

    return r


if __name__ == '__main__':
    from config import DATA_DIR, REPO_DIR
    here = str(DATA_DIR)
    parser = argparse.ArgumentParser(description='Compute KPIs from CSV output')
    parser.add_argument('csv', nargs='?', help='CSV file (basename or path)')
    parser.add_argument('--short-start', type=float, default=None)
    parser.add_argument('--short-end', type=float, default=None)
    parser.add_argument('--after-extra', type=float, default=0.02)
    parser.add_argument('--underv-threshold', type=float, default=0.95)
    args = parser.parse_args()

    csv_file = None
    if args.csv:
        candidate = args.csv
        if not os.path.isabs(candidate) and os.path.exists(os.path.join(here, candidate)):
            csv_file = os.path.join(here, candidate)
        elif os.path.exists(candidate):
            csv_file = candidate
        else:
            for ext in ('.csv', '.CSV'):
                p = os.path.join(here, candidate + ext)
                if os.path.exists(p):
                    csv_file = p
                    break
            if csv_file is None:
                print('Requested CSV not found:', candidate)
    else:
        preferred = os.path.join(here, CSV_TO_READ)
        if os.path.exists(preferred):
            csv_file = preferred
        else:
            for f in os.listdir(here):
                if f.lower().endswith('.csv'):
                    csv_file = os.path.join(here, f)
                    break

    if csv_file is None:
        print('No CSV file found or specified in', here)
        raise SystemExit(1)

    res = compute_kpis(csv_file, short_start=args.short_start, short_end=args.short_end,
                       underv_threshold=args.underv_threshold, after_extra=args.after_extra)

    for k, v in res.items():
        print(f'{k}: {v}')

    # Name the report after the CSV's position inside the dataset, falling back
    # to the bare filename for CSVs living outside it.
    try:
        rel = os.path.relpath(csv_file, here)
    except ValueError:          # different drive on Windows
        rel = os.path.basename(csv_file)
    if rel.startswith('..'):
        rel = os.path.basename(csv_file)

    report_stem = os.path.splitext(rel)[0].replace('\\', '_').replace('/', '_')
    report_file = os.path.join(REPO_DIR, f'kpi_report_{report_stem}.json')
    try:
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(res, f, separators=(',', ':'))
        print('Wrote JSON report to:', report_file)
    except Exception as e:
        print('Failed to write JSON report:', e)
