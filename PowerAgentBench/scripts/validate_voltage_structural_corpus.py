"""Offline v3 integrity, complete independent template replay and tool leakage checks."""
from __future__ import annotations

import argparse
import itertools
import json
from collections import Counter
from pathlib import Path

from poweragentbench.voltage_case import (load_benchmark_config, load_scenario_network, read_json, sha256_file, write_pandapower_json)
from poweragentbench.voltage_evaluator import evaluate_voltage_dispatch
from poweragentbench.voltage_freeze import digest
from poweragentbench.voltage_structure import (PFStore, TEMPLATES, certificate, dispatch, identity,
    near_duplicate, physical_fingerprint, physical_vector, verify_certificate)
from poweragentbench.voltage_tools import VoltageToolServer
from scripts.generate_voltage_structural_corpus import write_json, make_candidate
from scripts.run_voltage_structural_baselines import ledger_count

FORBIDDEN = {'structure_class','uniform_feasible','single_feasible','coarse_feasible','witness','witness_action',
             'recipe_id','recipe_family','operating_family_id','spatial_family_id','full_path','artifact_hash',
             'template_actions','template_results','certificate_path','search_pf_calls','feasible_density',
             'physical_fingerprint','generation_seed','template_definition_sha256','corpus_version'}


def assert_no_private_keys(value):
    if isinstance(value,dict):
        if set(value)&FORBIDDEN:raise ValueError(f'private tool output: {set(value)&FORBIDDEN}')
        for v in value.values():assert_no_private_keys(v)
    elif isinstance(value,list):
        for v in value:assert_no_private_keys(v)


def validate(root):
    corpus=read_json(root/'corpus_manifest.json');protocol=read_json(root/'exploration/protocol.json')
    if corpus['corpus_version']!='structure-v3' or corpus['num_test']!=0 or (root/'test').exists():
        raise ValueError('only Dev-only v3 corpus is authorized')
    if digest({k:v for k,v in corpus.items() if k!='dataset_sha256'})!=corpus['dataset_sha256']:
        raise ValueError('corpus digest mismatch')
    if sha256_file(root/'dev/manifest.json')!=corpus['split_manifest_sha256']['dev']:
        raise ValueError('Dev manifest mismatch')
    if sha256_file(root/'evaluator_private/witnesses.json')!=corpus['witnesses_sha256']:
        raise ValueError('witness artifact mismatch')
    config=load_benchmark_config();ident=identity(config)
    if corpus['numerical_identity']!=ident or corpus['generation_protocol_sha256']!=digest(protocol):
        raise ValueError('numeric/protocol identity mismatch')
    entries=read_json(root/'dev/manifest.json')['scenarios']
    if digest({r['candidate_id']:r['certificate_sha256'] for r in entries})!=corpus['structure_evidence_sha256']:
        raise ValueError('evidence collection mismatch')
    output=root/'validation';output.mkdir(exist_ok=True)
    other=ledger_count(root/'exploration/pf_ledger.sqlite')+ledger_count(root/'baselines/pf_ledger.sqlite')
    validation_identity={'numeric':ident,'dataset_sha256':corpus['dataset_sha256'],'validator_sha256':sha256_file(__file__),
                         'tools_sha256':sha256_file(Path(__file__).parents[1]/'poweragentbench/voltage_tools.py')}
    store=PFStore(output/'pf_ledger.sqlite',validation_identity,protocol['total_pf_limit']-other)
    vectors=[];families=set();checks=[]
    try:
        for entry in entries:
            sid=entry['scenario_id'];net=load_scenario_network(sid,root/'dev')
            # Candidate fingerprint identifies the sampled operating point before
            # pandas JSON rounds floats. Frozen bytes have their own strict hash.
            generated,_=make_candidate(int(entry['candidate_id'][1:]),protocol,config)
            if physical_fingerprint(generated)!=entry['physical_fingerprint']:
                raise ValueError('sampled physical fingerprint mismatch')
            reconstructed=output/'reconstructed'/f'{sid}.json'
            write_pandapower_json(generated,reconstructed)
            if sha256_file(reconstructed)!=entry['full_sha256']:
                raise ValueError('serialized snapshot does not match the fixed recipe/topology')
            vector=physical_vector(net)
            roundoff=max(abs(a-b) for a,b in zip(vector,physical_vector(generated)))
            if roundoff>1e-12:
                raise ValueError('serialized operating point differs beyond roundoff')
            if entry['operating_family_id'] in families or any(near_duplicate(vector,v) for v in vectors):
                raise ValueError('duplicate family/near state in Dev')
            families.add(entry['operating_family_id']);vectors.append(vector)
            path=root/entry['certificate_path']
            if sha256_file(path)!=entry['certificate_sha256']:raise ValueError('certificate artifact mismatch')
            cert=read_json(path);verify_certificate(cert,ident,entry['full_sha256'])
            if cert['structure_class']!=entry['structure_class']:raise ValueError('entry class mismatch')
            results={};zero_report=None
            for a,expected in zip(TEMPLATES,cert['template_results']):
                report=store.call([sid,entry['full_sha256'],'template',a],'validation_templates/'+sid,
                    lambda a=a:evaluate_voltage_dispatch(sid,dispatch(a,config['bess']),scenario_root=root/'dev'))
                if not report['converged'] or bool(report['success'])!=expected['success']:
                    raise ValueError(f'independent template mismatch: {sid} {a}')
                for key in ('min_vm_pu','max_vm_pu','voltage_violation_magnitude'):
                    if abs(report['final_state'][key]-expected['state'][key])>1e-10:
                        raise ValueError(f'template numeric drift: {sid} {a}')
                results[a]=expected
                if a==(0,0,0,0):zero_report=report
            witness=store.call([sid,entry['full_sha256'],'witness'],'validation_witness/'+sid,
                lambda:evaluate_voltage_dispatch(sid,dispatch(cert['witness'],config['bess']),scenario_root=root/'dev'))
            if not witness['success']:raise ValueError('independent witness failed')
            if entry['fragile']:
                again=store.call([sid,entry['full_sha256'],'fragile_repeat'],'validation_fragile/'+sid,
                    lambda:evaluate_voltage_dispatch(sid,dispatch(cert['witness'],config['bess']),scenario_root=root/'dev'))
                if again['final_state']!=witness['final_state']:raise ValueError('fragile witness unstable')
            # All 8 interfaces, legal zero-action feedback. Synthetic calls reuse the
            # already independently evaluated zero report; no model or extra PF.
            for i,v,r in itertools.product((False,True),repeat=3):
                server=VoltageToolServer(sid,scenario_root=root/'dev',domain_interface=i,verification=v,recovery=r,
                                         evaluation_fn=lambda *a,**k:zero_report)
                for tool in server.allowed_tools:
                    observation,_=server.execute(tool,{'dispatch':[]})
                    assert_no_private_keys(observation)
            checks.append({'scenario_id':sid,'structure_class':entry['structure_class'],'independent_templates':len(results),
                           'witness_success':True,'serialization_max_roundoff':roundoff,'all_eight_tool_conditions_no_leakage':True,'fragile':entry['fragile']})
            write_json(output/'checks.json',checks)
        counts=Counter(e['structure_class'] for e in entries)
        s4_families={e['spatial_family_id'] for e in entries if e['structure_class']=='S4'}
        complete=all(counts[s]==8 for s in ('S1','S2','S3','S4')) and len(s4_families)>=2
        result={'status':'PASS' if complete else 'FEASIBILITY_BLOCKED','counts':dict(counts),'s4_spatial_families':len(s4_families),
                'actual_pf_calls':store.count,'pf_by_phase':store.totals(),'checks':checks,'model_api_requests':0,'test_run':False,
                'warning':'PASS is offline structure/data validation, not Pilot/Main authorization'}
        write_json(output/'report.json',result)
        return result
    finally:store.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus-root',type=Path,required=True)
    print(json.dumps(validate(p.parse_args().corpus_root),indent=2))
