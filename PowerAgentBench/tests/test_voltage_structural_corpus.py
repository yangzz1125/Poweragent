import itertools
import json
from pathlib import Path

import pytest

from poweragentbench.voltage_case import DEFAULT_SCENARIO_ROOT, load_benchmark_config, load_scenario_network, read_json
from poweragentbench.voltage_evaluator import evaluate_voltage_dispatch
from poweragentbench.voltage_freeze import FREEZE_FIELDS, STRUCTURAL_FREEZE_FIELDS, freeze_contract
from poweragentbench.voltage_structure import PFStore, dispatch, evaluate_memory, identity
from poweragentbench.voltage_tools import VoltageToolServer
from scripts.generate_voltage_structural_corpus import select_dev
from scripts.run_voltage_structural_baselines import policy_action, run_episode
from scripts.validate_voltage_structural_corpus import assert_no_private_keys


def test_freeze_requires_structural_identity_without_breaking_v1():
    old={k:'old' for k in FREEZE_FIELDS}
    assert freeze_contract(old)==old
    new={**old,'corpus_version':'structure-v3'}
    with pytest.raises(ValueError):freeze_contract(new)
    new.update({k:'v3' for k in STRUCTURAL_FREEZE_FIELDS});new['corpus_version']='structure-v3'
    assert freeze_contract(new)==new


def test_same_family_and_near_duplicates_cannot_fill_quota():
    base={'structure_class':'S4','initial_voltage_condition':'OVERVOLTAGE','spatial_family_id':'space',
          'operating_family_id':'parent','physical_fingerprint':'one','physical_vector':[1.,0.]}
    rows=[{**base,'candidate_id':str(i)} for i in range(20)]
    chosen,rejected=select_dev(rows,2031,8)
    assert len(chosen)==1 and len(rejected)==19
    near={**base,'candidate_id':'near','operating_family_id':'another','physical_fingerprint':'two','physical_vector':[1.01,0.]}
    assert len(select_dev([rows[0],near],2031,8)[0])==1


def test_local_policy_counts_every_probe_and_no_oracle():
    specs=load_benchmark_config()['bess']
    summary={'network':{'branches':[{'from_bus':i,'to_bus':i+1,'in_service':True} for i in range(32)]}}
    calls=[]
    def preview(values):
        calls.append(values)
        return {'success':False,'converged':True,'remaining_undervoltage_buses':{'32':.94},
                'remaining_overvoltage_buses':{},'voltage_violation_magnitude':1.}
    _,reason=policy_action('bounded_local',{'raw_bus_voltages_pu':{'32':.94}}, {'bess':specs},summary,preview)
    assert len(calls)==4 and reason=='query_budget_or_no_unseen_neighbor'
    assert calls[1][-1]==1.0  # actual graph-nearest bus, one counted probe


def test_real_tools_separate_preview_submit_audit_and_resume(tmp_path):
    # Existing public regression fixtures only, not hidden Test or construction data.
    import shutil
    root=tmp_path/'case';shutil.copytree(DEFAULT_SCENARIO_ROOT,root/'dev')
    store=PFStore(tmp_path/'pf.sqlite',{'test':'baseline'},100)
    for policy in ('no_action','all_full','uniform_bisection','bounded_local'):
        row=run_episode(root,'V0001',policy,store,'test_dataset')
        assert row['preview_calls']<=4 and row['submit_calls']==1 and row['audit_actual_pf']==1
        assert row['online_actual_pf']==row['preview_calls']+1
        assert row['total_actual_pf']==row['preview_calls']+2
        before=store.count
        assert run_episode(root,'V0001',policy,store,'test_dataset')==row
        assert store.count==before
        assert_no_private_keys(row['tool_log'])
    store.close()


def test_all_eight_conditions_hide_structural_sentinels():
    # Only tool outputs are visible, not this developer-side server metadata.
    fake={'valid_action':1.,'success':0.,'converged':True,'n_actual_power_flows':1,'final_state':{},'artifact_hash':'PRIVATE'}
    for i,v,r in itertools.product((False,True),repeat=3):
        server=VoltageToolServer('V0001',domain_interface=i,verification=v,recovery=r,evaluation_fn=lambda *a,**k:fake)
        server.metadata.update(structure_class='S4',witness='PRIVATE',recipe_id='PRIVATE',template_actions=['PRIVATE'])
        for tool in server.allowed_tools:
            output,_=server.execute(tool,{'dispatch':[]})
            assert_no_private_keys(output)
            assert 'PRIVATE' not in json.dumps(output)


def test_fast_and_independent_success_and_failed_action():
    config=load_benchmark_config();net=load_scenario_network('V0001')
    witness=next(x['dispatch'] for x in read_json(DEFAULT_SCENARIO_ROOT/'private/witnesses.json') if x['scenario_id']=='V0001')
    values={x['bess_id']:round(x['p_mw']/.25) for x in witness}
    for action in [(0,0,0,0),tuple(values.get(s['bess_id'],0) for s in config['bess'])]:
        fast=evaluate_memory(net,action,config)
        slow=evaluate_voltage_dispatch('V0001',dispatch(action,config['bess']))
        assert fast['success']==bool(slow['success'])
        assert fast['state']['bus_voltages_pu']==slow['final_state']['bus_voltages_pu']
