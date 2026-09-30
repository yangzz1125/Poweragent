"""Evaluator-only discrete structure certificates and durable offline PF accounting."""
from __future__ import annotations

import copy
import itertools
import json
import math
import sqlite3
from pathlib import Path

from poweragentbench.voltage_case import sha256_file
from poweragentbench.voltage_evaluator import (EVALUATOR_VERSION, apply_bess_dispatch,
    run_locked_power_flow, state_metrics)
from poweragentbench.voltage_freeze import digest, environment_identity

STRUCTURE_VERSION = "usc-131-v1"
GRID = tuple(range(-6, 7))
U = frozenset((i,)*4 for i in GRID)
S = frozenset(tuple(i if j == axis else 0 for j in range(4)) for axis in range(4) for i in GRID)
C = frozenset(itertools.product((-6, 0, 6), repeat=4))
TEMPLATES = tuple(sorted(U | S | C))
TEMPLATE_HASH = digest({"version": STRUCTURE_VERSION, "step_mw": .25, "U": sorted(U), "S": sorted(S), "C": sorted(C)})


def dispatch(action, specs):
    if len(action) != 4 or any(type(x) is not int or x not in GRID for x in action):
        raise ValueError("action must contain four integer grid indices")
    return [{"bess_id": spec["bess_id"], "p_mw": value*.25} for spec, value in zip(specs, action)]


def identity(config):
    return {"evaluator_version": EVALUATOR_VERSION,
            "evaluator_sha256": sha256_file(Path(__file__).with_name("voltage_evaluator.py")),
            "case_sha256": sha256_file(Path(__file__).with_name("voltage_case.py")),
            "structure_sha256": sha256_file(__file__), "solver": config["solver"],
            "config_sha256": digest(config), "environment_sha256": digest(environment_identity()),
            "template_definition_sha256": TEMPLATE_HASH, "structure_definition_version": STRUCTURE_VERSION}


def classify(results: dict, witness=None, replay_success=False):
    """Strict certification: any missing/numerically unresolved template blocks classification."""
    if set(results) != set(TEMPLATES) or any(r.get("status") != "ok" for r in results.values()):
        return "structure_unresolved"
    for label, family in (("S1", U), ("S2", S), ("S3", C)):
        if any(results[a]["success"] for a in family):
            return label if replay_success and witness is not None else "witness_unreplayed"
    if witness is not None and tuple(witness) not in TEMPLATES and replay_success:
        return "S4"
    return "search_unresolved"


def certificate(results, witness, replay, numerical_identity, snapshot_hash):
    if replay and (replay.get("artifact_hash") != snapshot_hash
                   or [r["p_mw"] for r in replay.get("submitted_dispatch", [])] != [x*.25 for x in witness]):
        raise ValueError("witness replay does not match snapshot/action")
    counts = {name: {"evaluated": sum(a in results for a in family),
                     "feasible": sum(bool(results.get(a, {}).get("success")) for a in family)}
              for name, family in (("uniform", U), ("single", S), ("coarse", C))}
    cert = {"template_definition_sha256": TEMPLATE_HASH, "template_actions": [list(a) for a in TEMPLATES],
            "template_results": [results.get(a) for a in TEMPLATES], "counts": counts,
            "template_nonconverged_count": sum(r.get("status") != "ok" for r in results.values()),
            "witness": list(witness) if witness is not None else None,
            "independent_replay": replay, "identity": numerical_identity, "snapshot_sha256": snapshot_hash,
            "structure_class": classify(results, witness, bool(replay and replay.get("success")))}
    cert["certificate_sha256"] = digest(cert)
    return cert


def verify_certificate(cert, numerical_identity, snapshot_hash):
    body = {k: v for k, v in cert.items() if k != "certificate_sha256"}
    if cert.get("certificate_sha256") != digest(body) or cert["identity"] != numerical_identity or cert["snapshot_sha256"] != snapshot_hash:
        raise ValueError("certificate identity/integrity mismatch")
    results = {tuple(a): r for a, r in zip(cert["template_actions"], cert["template_results"]) if r is not None}
    expected = certificate(results, cert["witness"], cert["independent_replay"], numerical_identity, snapshot_hash)
    if expected != cert:
        raise ValueError("certificate definition/count/classification mismatch")


def physical_vector(net):
    """Loads/PV at physical buses; invariant to row order, names and scenario IDs."""
    values = []
    for bus in sorted(net.bus.index):
        values.extend([float(net.load.loc[net.load.bus == bus, field].sum()) for field in ("p_mw", "q_mvar")])
        values.extend([float(net.sgen.loc[net.sgen.bus == bus, field].sum()) for field in ("p_mw", "q_mvar")])
    return values


def physical_fingerprint(net):
    # Static tables protect against accidental topology/device changes as well.
    tables = {}
    for name, cols in {"bus": ["vn_kv", "in_service"],
                       "line": ["from_bus", "to_bus", "length_km", "r_ohm_per_km", "x_ohm_per_km", "c_nf_per_km", "in_service"],
                       "ext_grid": ["bus", "vm_pu", "va_degree", "in_service"],
                       "storage": ["bus", "p_mw", "q_mvar", "scaling", "in_service"]}.items():
        tables[name] = json.loads(net[name][cols].sort_index().to_json(orient="split"))
    return digest({"static": tables, "bus_powers": physical_vector(net)})


def near_duplicate(a, b, threshold=.10):
    # ponytail: fixed physical distance, not a learned electrical embedding.
    distance = math.sqrt(sum((x-y)**2 for x, y in zip(a, b)))
    scale = max(math.sqrt(sum(x*x for x in a)), math.sqrt(sum(x*x for x in b)), 1e-12)
    return max(abs(x-y) for x, y in zip(a, b)) < threshold or distance/scale < .10


class BudgetExhausted(RuntimeError):
    pass


class PFStore:
    """Single-writer SQLite ledger. Reserve before PF; unknown crash charges block resume."""
    def __init__(self, path, numerical_identity, limit):
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS metadata (id INTEGER PRIMARY KEY, identity TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS calls (key TEXT PRIMARY KEY, phase TEXT, result TEXT)")
        ident = json.dumps(numerical_identity, sort_keys=True)
        old = self.db.execute("SELECT identity FROM metadata WHERE id=1").fetchone()
        if old and old[0] != ident:
            raise ValueError("offline ledger environment/source/solver mismatch")
        self.db.execute("INSERT OR IGNORE INTO metadata VALUES (1,?)", (ident,))
        self.db.commit()
        self.limit = limit
        if self.db.execute("SELECT COUNT(*) FROM calls WHERE result IS NULL").fetchone()[0]:
            raise RuntimeError("interrupted PF reservation: unknown count retained; inspect before resuming")

    @property
    def count(self):
        return self.db.execute("SELECT COUNT(*) FROM calls").fetchone()[0]

    def call(self, key, phase, fn):
        key = digest(key)
        old = self.db.execute("SELECT result FROM calls WHERE key=?", (key,)).fetchone()
        if old:
            if old[0] is None:
                raise RuntimeError("unknown interrupted PF; never silently repeat")
            return json.loads(old[0])
        if self.count >= self.limit:
            raise BudgetExhausted(f"PF cap reached: {self.count}/{self.limit}")
        self.db.execute("INSERT INTO calls VALUES (?,?,NULL)", (key, phase)); self.db.commit()
        result = fn()
        self.db.execute("UPDATE calls SET result=? WHERE key=?", (json.dumps(result, allow_nan=False), key))
        self.db.commit()
        return result

    def candidate_count(self, sid):
        return self.db.execute("SELECT COUNT(*) FROM calls WHERE phase LIKE ?", ("%/"+sid,)).fetchone()[0]

    def totals(self):
        totals = {}
        for phase, count in self.db.execute("SELECT phase,COUNT(*) FROM calls GROUP BY phase"):
            name = phase.split('/')[0]
            totals[name] = totals.get(name, 0) + count
        return totals

    def close(self):
        self.db.close()


def evaluate_memory(net, action, config):
    trial = copy.deepcopy(net)
    apply_bess_dispatch(trial, dispatch(action, config["bess"]), config)
    ok, error = run_locked_power_flow(trial, config["solver"])
    state = state_metrics(trial, config, converged=ok, error=error)
    return {"status": "ok" if ok else "numerical_unresolved", "success": bool(ok and state["voltage_violation_count"] == 0),
            "state": state, "margin": min(state["min_vm_pu"]-.95, 1.05-state["max_vm_pu"]) if ok else None}


def score(result):
    return result["state"]["voltage_violation_magnitude"] if result["status"] == "ok" else math.inf


def search_witness(evaluate, templates, rng, max_calls=384):
    """Positive witness search only: multistart coordinate/pair moves, then random grid."""
    visited = set(templates)
    calls = 0
    def probe(a):
        nonlocal calls
        if a in visited or any(x not in GRID for x in a) or calls >= max_calls:
            return None
        visited.add(a); calls += 1
        return evaluate(a)
    starts = sorted(templates, key=lambda a: (score(templates[a]), a))[:4]
    for start in starts:
        current, value = start, score(templates[start])
        for _ in range(16):
            best = None
            for axes in [(i,) for i in range(4)] + list(itertools.combinations(range(4), 2)):
                for signs in itertools.product((-1, 1), repeat=len(axes)):
                    a = list(current)
                    for i, sign in zip(axes, signs):
                        a[i] += sign
                    a = tuple(a); result = probe(a)
                    if result is None:
                        continue
                    if result["success"]:
                        return a, calls
                    if score(result) < value - 1e-12 and (best is None or score(result) < best[0]):
                        best = score(result), a
            if best is None:
                break
            value, current = best
    while calls < max_calls:
        a = tuple(rng.choice(GRID) for _ in range(4))
        result = probe(a)
        if result and result["success"]:
            return a, calls
    return None, calls
