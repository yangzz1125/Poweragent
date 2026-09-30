"""Bounded offline Route B scout/build/validate. Deliberately no Test or model mode."""
from __future__ import annotations

import argparse
import itertools
import json
import random
import shutil
import subprocess
import time
from collections import Counter, defaultdict, deque
from pathlib import Path

from poweragentbench.voltage_case import (DEFAULT_CONFIG_PATH, REPO_ROOT, build_ieee33_network,
    load_benchmark_config, read_json, sha256_file, write_pandapower_json)
from poweragentbench.voltage_evaluator import evaluate_voltage_dispatch
from poweragentbench.voltage_freeze import digest, environment_identity
from poweragentbench.voltage_structure import (C, GRID, S, TEMPLATES, TEMPLATE_HASH, U, STRUCTURE_VERSION,
    BudgetExhausted, PFStore, certificate, dispatch, evaluate_memory, identity, near_duplicate,
    physical_fingerprint, physical_vector, search_witness, verify_certificate)

from poweragentbench.voltage_storage import evaluator_output_root

GENERATOR_VERSION = "structure-v3-recipes-v1"
VERSIONS = {"corpus_version": "structure-v3", "generator_version": GENERATOR_VERSION,
            "physical_schema_version": "ieee33-bess-voltage-v1", "structure_definition_version": STRUCTURE_VERSION,
            "observation_protocol_version": "existing-raw-vs-domain-summary-v1",
            "template_definition_sha256": TEMPLATE_HASH}


def write_json(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, sort_keys=True, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    temp.replace(path)


def branch_groups(net):
    adjacency = defaultdict(list)
    for row in net.line.itertuples():
        if row.in_service:
            adjacency[int(row.from_bus)].append(int(row.to_bus)); adjacency[int(row.to_bus)].append(int(row.from_bus))
    root = int(net.ext_grid.bus.iloc[0]); parents = {root: None}; order = [root]
    for bus in order:
        for child in sorted(adjacency[bus]):
            if child not in parents:
                parents[child] = bus; order.append(child)
    if len(order) != len(net.bus):
        raise ValueError("disconnected generator topology")
    groups = {root: root}
    for bus in order:
        children = [c for c in adjacency[bus] if parents.get(c) == bus]
        for child in children:
            groups[child] = child if len(children)>1 else groups[bus]
    return groups


def make_candidate(index, protocol, config):
    rng = random.Random(f"{protocol['seed']}:{index}")
    recipe = "ABCD"[index % 4]; under = (index//4) % 2 == 0
    base = build_ieee33_network(load_scale=1, pv_injections=[], bess_specs=config["bess"])
    groups = branch_groups(base)
    if recipe == "A":
        scale = rng.uniform(.7,1.5) if under else rng.uniform(.3,.8)
        buses = rng.sample(range(5 if under else 10,33), rng.randint(0,2) if under else rng.randint(2,4))
        pv = [(b, round(rng.uniform(.1,.8) if under else rng.uniform(1.2,3.5),4)) for b in buses]
        factors = [round(rng.uniform(.3,2.5) if under else rng.uniform(.5,1.5),4) for _ in base.load.index]
    else:
        scale = rng.uniform(.3,1.5)
        eligible = sorted(set(groups[b] for b in range(5,33)))
        chosen = rng.choice(eligible)
        group_factors = {g: rng.uniform(.3,2.5) for g in set(groups.values())}
        if recipe == "D":
            group_factors = {g: rng.uniform(.3,.7) if g==chosen else rng.uniform(1.5,2.5) for g in group_factors}
        factors = [round(min(2.5,max(.3,group_factors[groups[int(row.bus)]]*rng.uniform(.9,1.1))),4) for row in base.load.itertuples()]
        if recipe == "B":
            buses = rng.sample(range(5,33),rng.randint(0,4))
        else:
            available = [b for b in range(5,33) if groups[b]==chosen]
            buses = rng.sample(available,rng.randint(1,min(4,len(available))))
        pv = [(b,round(rng.uniform(.1,3.5),4)) for b in buses]
    scale = round(scale,4)
    net = build_ieee33_network(load_scale=scale, pv_injections=pv, bess_specs=config["bess"])
    net.load.loc[:,"p_mw"] *= factors; net.load.loc[:,"q_mvar"] *= factors
    group_load = {g: [f for f,row in zip(factors,base.load.itertuples()) if groups[int(row.bus)]==g] for g in set(groups.values())}
    spatial = {"recipe": recipe, "pv_groups": sorted(set(groups[b] for b in buses)),
               "high_load_groups": sorted(g for g, fs in group_load.items() if fs and sum(fs)/len(fs)>1.4)}
    family = {**spatial,"pv_buses":sorted(buses)}
    return net, {"candidate_id": f"N{index:05d}", "candidate_index":index, "recipe_id":recipe,
                 "seed": protocol["seed"], "load_scale":scale,"load_multipliers":factors,"pv_injections":pv,
                 "spatial_family_id":digest(spatial)[:16],"operating_family_id":digest(family)[:16],
                 "physical_fingerprint":physical_fingerprint(net),"physical_vector":physical_vector(net)}


def save_scenario(root, sid, net, initial, config):
    full = root/"full"/f"{sid}.json"; public = root/"public"/f"{sid}.json"
    if not full.exists():
        write_pandapower_json(net,full)
    write_json(public,{"scenario_id":sid,"network":{"name":"IEEE 33-bus distribution feeder", "n_bus":len(net.bus),"n_line":len(net.line),
        "branches":[{"line_id":int(i),"from_bus":int(row.from_bus),"to_bus":int(row.to_bus),"in_service":bool(row.in_service)} for i,row in net.line.iterrows()],
        "loads":[{"load_id":int(i),"bus":int(row.bus),"p_mw":float(row.p_mw),"q_mvar":float(row.q_mvar)} for i,row in net.load.iterrows()]},
        "voltage_limits_pu":config["voltage_limits_pu"],"line_loading_percent_max":config["line_loading_percent_max"],"bess":config["bess"],"initial_state":initial})
    return {"scenario_id":sid,"condition":initial["condition"],"severity":initial["voltage_violation_magnitude"],
            "full_path":f"full/{sid}.json","public_path":f"public/{sid}.json", "full_sha256":sha256_file(full),"public_sha256":sha256_file(public)}


def manifest(entries, config):
    return {"dataset_version":config["dataset_version"],"benchmark_config_sha256":sha256_file(DEFAULT_CONFIG_PATH),**VERSIONS,"scenarios":entries}


def independent(store, key, sid, action, case_root, config, phase="independent_replay"):
    return store.call(key,phase+"/"+sid,lambda:evaluate_voltage_dispatch(sid,dispatch(action,config["bess"]),scenario_root=case_root))


def compare_replay(memory, replay):
    if bool(memory["success"]) != bool(replay["success"]) or bool(memory["state"]["converged"]) != bool(replay["converged"]):
        raise RuntimeError("fast/independent outcome mismatch")
    if memory["status"] == "ok":
        for k in ("min_vm_pu","max_vm_pu","voltage_violation_magnitude"):
            if abs(memory["state"][k]-replay["final_state"][k]) > 1e-10:
                raise RuntimeError("fast/independent numeric mismatch")


def evaluate_candidate(index, root, protocol, config, store, ident, scan=False):
    net, row = make_candidate(index,protocol,config); sid=row["candidate_id"]
    case_root=root/"evaluator_private"/"candidates"/sid
    full=case_root/"full"/f"{sid}.json"
    if not full.exists():write_pandapower_json(net,full)
    snapshot=sha256_file(full)
    # Include both serialized identity and physical identity in each cache key.
    def evaluate(action):
        return store.call([snapshot,row["physical_fingerprint"],list(action)],"construction/"+sid,lambda:evaluate_memory(net,action,config))
    initial=evaluate((0,0,0,0)); state=initial["state"]
    row.update(protocol_sha256=digest(protocol),identity=ident,initial_pf_status=initial["status"],
               initial_voltage_condition=None,severity=state["voltage_violation_magnitude"],snapshot_sha256=snapshot,
               template_definition_sha256=TEMPLATE_HASH,classification_status="initial_rejected",structure_class=None,
               search_pf_calls=0,witness_found=False,independent_replay_success=False,
               uniform_evaluated=0,uniform_feasible_count=0,single_evaluated=0,single_feasible_count=0,
               coarse_evaluated=0,coarse_feasible_count=0,template_nonconverged_count=0,template_errors=[],search_method="not_started")
    if initial["status"] != "ok":
        row["rejection_or_unresolved_reason"]="initial_numerical_unresolved"; return row
    if bool(state["undervoltage_buses"]) == bool(state["overvoltage_buses"]):
        row["rejection_or_unresolved_reason"]="initial_mixed_or_already_compliant"; return row
    state["condition"]="UNDERVOLTAGE" if state["undervoltage_buses"] else "OVERVOLTAGE"
    row["initial_voltage_condition"]=state["condition"]
    entry=save_scenario(case_root,sid,net,state,config);write_json(case_root/"manifest.json",manifest([entry],config))
    results={a:evaluate(a) for a in TEMPLATES}
    witness=next((a for a in TEMPLATES if results[a]["success"]),None)
    numeric=any(r["status"]!="ok" for r in results.values())
    search_calls=0
    if witness is None and not numeric:
        witness,search_calls=search_witness(evaluate,results,random.Random(f"search:{protocol['seed']}:{index}"),protocol["search_calls"])
    row["search_method"]="templates" if search_calls==0 else "multistart_coordinate_pair_random"
    if scan and witness is None and not numeric:
        for a in itertools.product(GRID,repeat=4):
            if evaluate(a)["success"]:
                witness=a;break
        row["search_method"] += "+full_grid_scan"
        row["full_scan_complete_no_witness"] = witness is None
    replay=None
    if witness is not None:
        replay=independent(store,[sid,snapshot,"witness"],sid,witness,case_root,config)
        compare_replay(evaluate(witness),replay)
    failed=next((a for a in TEMPLATES if results[a]["status"]=="ok" and not results[a]["success"]),None)
    if failed is not None:
        fail_replay=independent(store,[sid,snapshot,"failed_template"],sid,failed,case_root,config)
        compare_replay(results[failed],fail_replay)
    cert=certificate(results,witness,replay,ident,snapshot)
    cert_path=root/"evaluator_private"/"template_certificates"/f"{sid}.json";write_json(cert_path,cert)
    row.update(classification_status=cert["structure_class"], structure_class=cert["structure_class"] if cert["structure_class"] in ("S1","S2","S3","S4") else None,
               witness_found=witness is not None,independent_replay_success=bool(replay and replay["success"]),search_pf_calls=search_calls,
               certificate_path=str(cert_path.relative_to(root)),certificate_sha256=sha256_file(cert_path),
               template_nonconverged_count=cert["template_nonconverged_count"],template_errors=[r["state"]["error"] for r in results.values() if r["status"]!="ok"],
               witness_voltage_margin=evaluate(witness)["margin"] if witness is not None else None,
               all_full_feasible=results[((6 if state["condition"]=="UNDERVOLTAGE" else -6),)*4]["success"],
               rejection_or_unresolved_reason=None if cert["structure_class"] in ("S1","S2","S3","S4") else cert["structure_class"])
    for name,counts in cert["counts"].items():
        row[name+"_evaluated"]=counts["evaluated"];row[name+"_feasible_count"]=counts["feasible"]
    return row


def select_dev(rows, seed, per_class):
    # Fixed random priority, direction/spatial-family round robin, no model scores.
    chosen=[]; rejected=[]; families=set(); vectors=[]; fingerprints=set()
    for label in ("S1","S2","S3","S4"):
        pool=[r for r in rows if r.get("structure_class")==label]
        pool.sort(key=lambda r:digest([seed,"selection",r["candidate_id"]]))
        buckets=defaultdict(list)
        for row in pool:buckets[(row["initial_voltage_condition"],row["spatial_family_id"])].append(row)
        ordered=[]
        directions = {condition: deque(sorted(key for key in buckets if key[0] == condition))
                      for condition in sorted({key[0] for key in buckets})}
        while any(directions.values()):
            for keys in directions.values():
                if keys:
                    key = keys[0]; ordered.append(buckets[key].pop())
                    if buckets[key]: keys.rotate(-1)
                    else: keys.popleft()
        count=0
        for row in ordered:
            if row["physical_fingerprint"] in fingerprints or row["operating_family_id"] in families or any(near_duplicate(row["physical_vector"],v) for v in vectors):
                rejected.append({"candidate_id":row["candidate_id"],"reason":"duplicate_family_or_near_state"});continue
            if count>=per_class:continue
            chosen.append(row);count+=1;families.add(row["operating_family_id"]);vectors.append(row["physical_vector"]);fingerprints.add(row["physical_fingerprint"])
    return chosen,rejected


def load_rows(root):
    return [read_json(p) for p in sorted((root/"exploration"/"checkpoint").glob("N*.json"))]


def summarize(root, store, protocol):
    rows=load_rows(root);chosen,rejected=select_dev(rows,protocol["seed"],protocol["dev_per_structure"])
    summary={"candidates_completed":len(rows),"actual_pf_calls":store.count,"pf_by_phase":store.totals(),
             "certified_counts":dict(Counter(r["structure_class"] for r in rows if r.get("structure_class"))),
             "selected_counts":dict(Counter(r["structure_class"] for r in chosen)),
             "selection_rejections":rejected,"by_recipe":{},"model_api_requests":0,"test_generated":False}
    for recipe in "ABCD":
        subset=[r for r in rows if r["recipe_id"]==recipe]
        summary["by_recipe"][recipe]={"candidates":len(subset),"status_counts":dict(Counter(r["classification_status"] for r in subset))}
    if (root/"corpus_manifest.json").exists():
        summary["corpus_status"] = read_json(root/"corpus_manifest.json")["status"]
    write_json(root/"exploration"/"summary.json",summary)
    with (root/"exploration"/"candidate_audit.jsonl").open("w",encoding="utf-8") as f:
        for row in rows:f.write(json.dumps(row,sort_keys=True)+"\n")
    return summary,chosen


def build_dev(root, chosen, protocol, config, store, ident):
    if (root/"corpus_manifest.json").exists():
        return read_json(root/"corpus_manifest.json")
    entries=[];witnesses=[]
    chosen=sorted(chosen,key=lambda r:digest([protocol["seed"],"opaque-id",r["candidate_id"]]))
    for i,row in enumerate(chosen,1):
        sid=f"D{i:04d}";net,_=make_candidate(row["candidate_index"],protocol,config)
        old=root/"evaluator_private"/"candidates"/row["candidate_id"]
        old_public=read_json(old/"public"/f"{row['candidate_id']}.json")
        entry=save_scenario(root/"dev",sid,net,old_public["initial_state"],config)
        if entry["full_sha256"] != row["snapshot_sha256"]:
            raise ValueError("rebuilt Dev snapshot differs from certified candidate")
        cert=read_json(root/row["certificate_path"]);verify_certificate(cert,ident,row["snapshot_sha256"])
        entry.update({k:row[k] for k in ("structure_class","recipe_id","operating_family_id","spatial_family_id","physical_fingerprint","witness_voltage_margin","certificate_path","certificate_sha256","all_full_feasible")})
        entry["candidate_id"]=row["candidate_id"];entry["difficulty"]="unstratified";entry["fragile"]=row["witness_voltage_margin"]<1e-4
        entries.append(entry)
        write_json(root/"dev"/"manifest.json",manifest(entries,config))
        replay=independent(store,[sid,entry["full_sha256"],"dev_witness"],sid,cert["witness"],root/"dev",config,"dev_replay")
        if not replay["success"]:raise RuntimeError("selected Dev witness failed independent replay")
        witnesses.append({"scenario_id":sid,"candidate_id":row["candidate_id"],"dispatch":dispatch(cert["witness"],config["bess"]),"replay":replay})
    write_json(root/"evaluator_private"/"witnesses.json",witnesses)
    counts=Counter(r["structure_class"] for r in chosen)
    complete=all(counts[k]==protocol["dev_per_structure"] for k in ("S1","S2","S3","S4")) and len({r["spatial_family_id"] for r in chosen if r["structure_class"]=="S4"})>=2
    evidence_hash=digest({r["candidate_id"]:r["certificate_sha256"] for r in chosen})
    dev_manifest=read_json(root/"dev"/"manifest.json");dev_manifest["structure_evidence_sha256"]=evidence_hash
    write_json(root/"dev"/"manifest.json",dev_manifest)
    corpus={**VERSIONS,"dataset_version":config["dataset_version"],"benchmark_config_sha256":sha256_file(DEFAULT_CONFIG_PATH),
            "generation_protocol_sha256":digest(protocol),"structure_evidence_sha256":evidence_hash,"numerical_identity":ident,
            "split_manifest_sha256":{"dev":sha256_file(root/"dev"/"manifest.json")},"witnesses_sha256":sha256_file(root/"evaluator_private"/"witnesses.json"),
            "num_dev":len(entries),"num_test":0,"status":"DEV_BUILT" if complete else "FEASIBILITY_BLOCKED",
            "structure_counts":dict(counts),"main_authorized":False}
    corpus["dataset_sha256"]=digest(corpus);write_json(root/"corpus_manifest.json",corpus)
    return corpus


def run(root, mode, seed=2031, candidates=512, rounds=2, pf_limit=250000, search_calls=384, scans=2, per_class=8):
    root=evaluator_output_root(root)
    if not (0<candidates<=512 and candidates%4==0 and 1<=rounds<=2 and 0<pf_limit<=250000 and 0<=scans<=12 and 0<search_calls<=512 and 0<per_class<=8):
        raise ValueError("invalid or excessive offline bounds")
    config=load_benchmark_config();ident=identity(config)
    protocol={**VERSIONS,"seed":seed,"candidates_per_round":candidates,"rounds":rounds,"pf_per_round_limit":pf_limit,
              "total_pf_limit":pf_limit*rounds,"search_calls":search_calls,"full_scan_candidates_per_round":scans,"dev_per_structure":per_class,
              "recipes":"A v2 envelope; B branch-correlated; C PV in one electrical group; D low-load PV group/high-load other groups",
              "envelope":{"global_load_scale":[.3,1.5],"local_multiplier":[.3,2.5],"pv_buses":[5,32],"pv_count":[0,4],"pv_mw":[.1,3.5]},
              "initial_acceptance":"finite/converged, nonzero pure under OR pure over; no severity or margin acceptance cutoff",
              "jitter":"B/C/D U(.9,1.1) multiplied per group, clipped to [.3,2.5]; P,Q same multiplier",
              "scan_selection":"seeded hash order among complete-template numerically clean search_unresolved, list saved before scanning",
              "selection":"seeded priorities, direction/spatial-family round-robin; one per operating family; reject max bus power difference<.10 MW OR relative L2<.10",
              "source_commit":subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip(),
              "generator_sha256":sha256_file(__file__),"numerical_identity":ident,"api_calls_allowed":False,"test_allowed":False}
    protocol_path=root/"exploration"/"protocol.json"
    if protocol_path.exists():
        if read_json(protocol_path)!=protocol:raise ValueError("resume protocol/source/limits mismatch")
    else:
        if root.exists() and any(root.iterdir()):raise ValueError("new evaluator root must be empty")
        write_json(protocol_path,protocol);write_json(root/"exploration"/"environment.json",environment_identity())
    store=PFStore(root/"exploration"/"pf_ledger.sqlite",ident,protocol["total_pf_limit"])
    try:
        if mode in ("scout","all"):
            for round_i in range(rounds):
                store.limit=min(protocol["total_pf_limit"],(round_i+1)*pf_limit)
                try:
                    for i in range(round_i*candidates,(round_i+1)*candidates):
                        path=root/"exploration"/"checkpoint"/f"N{i:05d}.json"
                        if path.exists():continue
                        start=time.monotonic()
                        try:
                            row=evaluate_candidate(i,root,protocol,config,store,ident)
                        except BudgetExhausted:
                            _, partial=make_candidate(i,protocol,config)
                            partial.update(classification_status="budget_partial",structure_class=None,identity=ident,
                                           rejection_or_unresolved_reason="PF budget exhausted; cached partial evidence is not certification",
                                           actual_total_pf_calls=store.candidate_count(partial["candidate_id"]))
                            write_json(path,partial)
                            raise
                        row["actual_total_pf_calls"]=store.candidate_count(row["candidate_id"]);row["elapsed_seconds"]=time.monotonic()-start
                        write_json(path,row)
                        if (i+1)%16==0:
                            summary,_=summarize(root,store,protocol);print(json.dumps({"completed":i+1,"pf":store.count,"counts":summary["certified_counts"]}),flush=True)
                    rows=load_rows(root)
                    queue=sorted([r for r in rows if round_i*candidates<=r["candidate_index"]<(round_i+1)*candidates and r["classification_status"]=="search_unresolved"],key=lambda r:digest([seed,"scan",r["candidate_id"]]))[:scans]
                    queue_path=root/"exploration"/f"scan_queue_{round_i}.json"
                    if queue_path.exists():
                        by_id={r["candidate_id"]:r for r in rows};queue=[by_id[sid] for sid in read_json(queue_path)]
                    else:write_json(queue_path,[r["candidate_id"] for r in queue])
                    for old in queue:
                        if "+full_grid_scan" in old.get("search_method",""):continue
                        row=evaluate_candidate(old["candidate_index"],root,protocol,config,store,ident,scan=True)
                        row["actual_total_pf_calls"]=store.candidate_count(row["candidate_id"])
                        write_json(root/"exploration"/"checkpoint"/f"{row['candidate_id']}.json",row)
                except BudgetExhausted as exc:
                    write_json(root/"exploration"/f"budget_stop_{round_i}.json",{"reason":str(exc),"actual_pf_calls":store.count})
                summary,chosen=summarize(root,store,protocol)
                if all(summary["selected_counts"].get(k,0)>=per_class for k in ("S1","S2","S3","S4")) and len({r["spatial_family_id"] for r in chosen if r["structure_class"]=="S4"})>=2:break
        store.limit=protocol["total_pf_limit"]
        summary,chosen=summarize(root,store,protocol)
        if mode in ("build-dev","all") and chosen:
            build_dev(root,chosen,protocol,config,store,ident)
            summary,_=summarize(root,store,protocol)
        return summary
    finally:
        summarize(root,store,protocol);store.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode",choices=("scout","build-dev","all"),default="all")
    p.add_argument("--output-dir",type=Path,required=True);p.add_argument("--seed",type=int,default=2031)
    p.add_argument("--candidates",type=int,default=512);p.add_argument("--rounds",type=int,default=2)
    p.add_argument("--pf-limit",type=int,default=250000);p.add_argument("--search-calls",type=int,default=384)
    p.add_argument("--scans",type=int,default=2);p.add_argument("--dev-per-structure",type=int,default=8)
    a=p.parse_args();print(json.dumps(run(a.output_dir,a.mode,a.seed,a.candidates,a.rounds,a.pf_limit,a.search_calls,a.scans,a.dev_per_structure),indent=2))


if __name__=="__main__":main()
