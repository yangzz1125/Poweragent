import copy
import itertools
from collections import Counter

import pytest

from poweragentbench.voltage_case import load_benchmark_config, read_json, REPO_ROOT
from poweragentbench.voltage_structure import (U,S,C,GRID,TEMPLATES,PFStore,BudgetExhausted,
    certificate,classify,verify_certificate,physical_fingerprint,near_duplicate)
from scripts.generate_voltage_structural_corpus import make_candidate, select_dev


def results(feasible=()):
    return {a:{'status':'ok','success':a in feasible} for a in TEMPLATES}


def test_action_families_and_v2_mapping():
    assert len(list(itertools.product(GRID,repeat=4)))==28561
    assert (len(U),len(S),len(C),len(TEMPLATES))==(13,49,81,131)
    assert (-6,)*4 in TEMPLATES and (6,)*4 in TEMPLATES
    import csv
    with (REPO_ROOT.parent/'research_records/voltage_control/dev_structural_coverage/coverage.csv').open() as f:
        labels=['S1' if int(r['uniform_feasible_templates']) else 'S2' if int(r['single_bess_feasible_templates']) else 'S3' if int(r['zero_full_feasible_templates']) else 'unresolved' for r in csv.DictReader(f)]
    assert Counter(labels)=={'S1':19,'S2':4,'S3':1}


def test_structure_requires_complete_evidence_and_replay():
    for label,a in [('S1',(1,1,1,1)),('S2',(1,0,0,0)),('S3',(6,0,6,0)),('S4',(1,2,0,0))]:
        r=results([a])
        assert classify(r,a,True)==label
        assert classify(dict(reversed(list(r.items()))),a,True)==label
        assert classify(r,a,False)!=label
        r.pop(next(iter(r)))
        assert classify(r,a,True)=='structure_unresolved'
    r=results();assert classify(r)=='search_unresolved'
    r[TEMPLATES[0]]={'status':'numerical_unresolved','success':False}
    assert classify(r,(1,2,0,0),True)=='structure_unresolved'


def test_certificate_tamper_and_identity():
    r=results();a=(1,2,0,0)
    replay={'success':1,'artifact_hash':'snap','submitted_dispatch':[{'p_mw':x*.25} for x in a]}
    cert=certificate(r,a,replay,{'solver':'locked'},'snap')
    verify_certificate(cert,{'solver':'locked'},'snap')
    for ident,snapshot in [({'solver':'changed'},'snap'),({'solver':'locked'},'changed')]:
        with pytest.raises(ValueError):verify_certificate(cert,ident,snapshot)
    bad=copy.deepcopy(cert);bad['template_results'][0]['success']=True
    with pytest.raises(ValueError):verify_certificate(bad,{'solver':'locked'},'snap')
    bad=copy.deepcopy(cert);bad['template_definition_sha256']='wrong'
    with pytest.raises(ValueError):verify_certificate(bad,{'solver':'locked'},'snap')


def test_budget_resume_and_no_repeated_accounting(tmp_path):
    path=tmp_path/'ledger.sqlite';store=PFStore(path,{'environment':'one'},1)
    calls=[]
    fn=lambda: calls.append(1) or {'ok':True}
    assert store.call('a','construction',fn)=={'ok':True}
    with pytest.raises(BudgetExhausted):store.call('b','construction',fn)
    store.close();store=PFStore(path,{'environment':'one'},2)
    store.call('a','construction',fn);store.call('b','construction',fn)
    assert len(calls)==2 and store.count==2;store.close()
    with pytest.raises(ValueError):PFStore(path,{'environment':'two'},3)


def test_fixed_recipes_physical_fingerprint_and_diversity():
    config=load_benchmark_config()
    for index in range(4):
        a,r=make_candidate(index,{'seed':2031},config)
        b,s=make_candidate(index,{'seed':2031},config)
        assert r==s and physical_fingerprint(a)==physical_fingerprint(b)
        b.name='different id';b.load=b.load.iloc[::-1]
        assert physical_fingerprint(a)==physical_fingerprint(b)
        b.load.iloc[0,b.load.columns.get_loc('p_mw')]+=.5
        assert physical_fingerprint(a)!=physical_fingerprint(b)
        assert all(.3<=f<=2.5 for f in r['load_multipliers'])
    assert near_duplicate([1.,0],[1.01,0])
    assert not near_duplicate([1.,0],[0,1.])


def test_nonfinite_missing_inactive_bus_cannot_succeed(monkeypatch):
    from poweragentbench.voltage_evaluator import run_locked_power_flow
    import pandapower as pp
    net,_=make_candidate(0,{'seed':2031},load_benchmark_config())
    solver=load_benchmark_config()['solver']
    assert run_locked_power_flow(net,solver)[0]
    monkeypatch.setattr(pp,'runpp',lambda *a,**k:None)
    for mode in ('nan','missing','inactive'):
        bad=copy.deepcopy(net)
        if mode=='nan':bad.res_bus.at[1,'vm_pu']=float('nan')
        if mode=='missing':bad.res_bus.drop(index=1,inplace=True)
        if mode=='inactive':bad.bus.at[1,'in_service']=False
        ok,error=run_locked_power_flow(bad,solver)
        assert not ok and 'invalid voltage' in error
