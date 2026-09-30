"""Offline online-budget baselines: 4 previews, 1 submit, 1 final audit, no oracle inputs."""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import defaultdict, deque
from pathlib import Path

from poweragentbench.voltage_case import load_benchmark_config, read_json, sha256_file
from poweragentbench.voltage_evaluator import evaluate_voltage_dispatch
from poweragentbench.voltage_structure import PFStore, identity
from poweragentbench.voltage_tools import VoltageToolServer
from scripts.generate_voltage_structural_corpus import write_json
from scripts.study_voltage_shortcuts import uniform_bisection

POLICIES = ("no_action", "all_full", "uniform_bisection", "bounded_local")


def hops(branches, start):
    graph=defaultdict(list)
    for edge in branches:
        if edge['in_service']:
            a,b=edge['from_bus'],edge['to_bus'];graph[a].append(b);graph[b].append(a)
    distance={start:0};queue=deque([start])
    while queue:
        bus=queue.popleft()
        for child in graph[bus]:
            if child not in distance:distance[child]=distance[bus]+1;queue.append(child)
    return distance


def policy_action(policy, initial, capabilities, summary, preview):
    """Only explicitly public observations and own preview feedback enter this function."""
    specs=capabilities['bess'];voltages=initial['raw_bus_voltages_pu']
    condition='UNDERVOLTAGE' if min(voltages.values())<.95 else 'OVERVOLTAGE'
    sign=1 if condition=='UNDERVOLTAGE' else -1
    if policy=='no_action':return [0.]*4,'open_loop'
    if policy=='all_full':return [sign*1.5]*4,'open_loop'
    if policy=='uniform_bisection':
        def evaluate(values):
            f=preview(values)
            return {'success':f['success'],'converged':f['converged'],
                    'final_state':{'undervoltage_buses':f['remaining_undervoltage_buses'],'overvoltage_buses':f['remaining_overvoltage_buses']}}
        _,trace,reason=uniform_bisection(evaluate,condition,budget=4)
        return trace[-1]['values'],reason
    if policy!='bounded_local':raise ValueError('unknown policy')
    # Fixed initial midpoint, then at most three single-coordinate improvements.
    # Nearby means actual in-service graph hop distance, not bus-index subtraction.
    best=[sign*.75]*4;feedback=preview(best);seen={tuple(best)}
    for _ in range(3):
        if feedback['success']:return best,'success'
        if not feedback['converged']:return best,'pf_nonconverged'
        violations=[(abs(v-.95),int(b),1) for b,v in feedback['remaining_undervoltage_buses'].items()]
        violations += [(abs(v-1.05),int(b),-1) for b,v in feedback['remaining_overvoltage_buses'].items()]
        if not violations:break
        _,bus,direction=max(violations);distance=hops(summary['network']['branches'],bus)
        candidate=None
        for i in sorted(range(4),key=lambda i:(distance[specs[i]['bus']],specs[i]['bess_id'])):
            trial=list(best);trial[i]+=direction*.25
            if specs[i]['p_min_mw']<=trial[i]<=specs[i]['p_max_mw'] and tuple(trial) not in seen:
                candidate=trial;break
        if candidate is None:break
        seen.add(tuple(candidate));result=preview(candidate)
        if result['success'] or (result['converged'] and result['voltage_violation_magnitude']<feedback['voltage_violation_magnitude']):
            best,feedback=candidate,result
    return best,'success' if feedback['success'] else 'query_budget_or_no_unseen_neighbor'


def run_episode(root, sid, policy, store, dataset_hash):
    slot=0
    def counted(scenario_id, dispatch, **kwargs):
        nonlocal slot
        slot+=1
        # Own episode's call slots only. Never key by construction action/cache.
        return store.call([dataset_hash,policy,sid,'online',slot,dispatch],'baseline_online/'+sid,
                          lambda:evaluate_voltage_dispatch(scenario_id,dispatch,**kwargs))
    server=VoltageToolServer(sid,scenario_root=root/'dev',domain_interface=False,verification=True,recovery=False,
                             max_previews=4,max_attempts=1,evaluation_fn=counted)
    tool_log=[]
    def tool(name,args):
        observation,done=server.execute(name,args)
        tool_log.append({'tool':name,'args':args,'observation':observation,'done':done})
        return observation
    summary=tool('case_summary',{});initial=tool('inspect_voltage_state',{});capabilities=tool('get_bess_capabilities',{})
    def action(values):return [{'bess_id':s['bess_id'],'p_mw':float(v)} for s,v in zip(capabilities['bess'],values)]
    def preview(values):return tool('preview_bess_dispatch',{'dispatch':action(values)})['preview']
    values,reason=policy_action(policy,initial,capabilities,summary,preview)
    submitted=tool('submit',{'dispatch':action(values)})
    report=store.call([dataset_hash,policy,sid,'final_audit',action(values)],'baseline_audit/'+sid,
                      lambda:evaluate_voltage_dispatch(sid,action(values),scenario_root=root/'dev'))
    if bool(report['success'])!=submitted['accepted']:raise RuntimeError('baseline final audit mismatch')
    return {'scenario_id':sid,'policy':policy,'success':int(report['success']), 'proposal_queries':server.state.preview_requests,
            'preview_calls':server.state.preview_calls,'submit_calls':server.state.submit_requests,
            'online_actual_pf':server.state.actual_power_flows,'audit_actual_pf':report['n_actual_power_flows'],
            'total_actual_pf':server.state.actual_power_flows+report['n_actual_power_flows'],'stop':reason,'tool_log':tool_log}


def ledger_count(path):
    if not path.exists():return 0
    db=sqlite3.connect(f'file:{path.as_posix()}?mode=ro',uri=True)
    try:return db.execute('SELECT COUNT(*) FROM calls').fetchone()[0]
    finally:db.close()


def run(root):
    corpus=read_json(root/'corpus_manifest.json');protocol=read_json(root/'exploration/protocol.json')
    manifest=read_json(root/'dev/manifest.json')
    if corpus['corpus_version']!='structure-v3' or sha256_file(root/'dev/manifest.json')!=corpus['split_manifest_sha256']['dev']:
        raise ValueError('only intact v3 Dev may be run')
    output=root/'baselines';output.mkdir(exist_ok=True)
    baseline_protocol={'policies':list(POLICIES),'max_previews':4,'max_submit':1,'audit_per_episode':1,
                       'policy_sha256':sha256_file(__file__),'uniform_helper_sha256':sha256_file(Path(__file__).with_name('study_voltage_shortcuts.py')),
                       'tools_sha256':sha256_file(Path(__file__).parents[1]/'poweragentbench/voltage_tools.py'),
                       'dataset_sha256':corpus['dataset_sha256'],'oracle_inputs':False,'model_api_requests':0,
                       'local_policy':'midpoint then greedy +/- one step at graph-nearest untried BESS; every probe charged'}
    if (output/'protocol.json').exists() and read_json(output/'protocol.json')!=baseline_protocol:
        raise ValueError('baseline resume identity mismatch')
    write_json(output/'protocol.json',baseline_protocol)
    other=ledger_count(root/'exploration/pf_ledger.sqlite')+ledger_count(root/'validation/pf_ledger.sqlite')
    store=PFStore(output/'pf_ledger.sqlite',{'numeric':identity(load_benchmark_config()),'baseline':baseline_protocol},protocol['total_pf_limit']-other)
    rows=[]
    try:
        for entry in manifest['scenarios']:
            for policy in POLICIES:
                path=output/'episodes'/f"{entry['scenario_id']}_{policy}.json"
                if path.exists():result=read_json(path)
                else:
                    result=run_episode(root,entry['scenario_id'],policy,store,corpus['dataset_sha256']);write_json(path,result)
                rows.append({**{k:v for k,v in result.items() if k!='tool_log'},'structure_class':entry['structure_class']})
        with (output/'per_case.csv').open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
        summary=[]
        for policy in POLICIES:
            for label in ['ALL','S1','S2','S3','S4']:
                group=[r for r in rows if r['policy']==policy and (label=='ALL' or r['structure_class']==label)]
                if group:summary.append({'policy':policy,'structure_class':label,'episodes':len(group),'successes':sum(r['success'] for r in group),
                    **{key:sum(r[key] for r in group) for key in ('proposal_queries','preview_calls','submit_calls','online_actual_pf','audit_actual_pf','total_actual_pf')}})
        write_json(output/'summary.json',{'rows':summary,'actual_pf_calls':store.count,'api_requests':0})
        assert store.count==sum(r['total_actual_pf'] for r in rows)
        return summary
    finally:store.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--corpus-root',type=Path,required=True)
    print(json.dumps(run(parser.parse_args().corpus_root),indent=2))
