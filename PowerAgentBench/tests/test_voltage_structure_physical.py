"""Real S4 evidence test, explicitly skipped when the private Dev corpus is absent."""
from pathlib import Path
import pytest

from poweragentbench.voltage_case import read_json,load_benchmark_config
from poweragentbench.voltage_evaluator import evaluate_voltage_dispatch
from poweragentbench.voltage_structure import TEMPLATES,dispatch,identity,verify_certificate


def test_real_s4_complete_exclusion_and_independent_witness(request):
    location=request.config.getoption('--v3-root')
    if not location:pytest.skip('requires --v3-root with actual generated Dev')
    root=Path(location);entries=read_json(root/'dev/manifest.json')['scenarios']
    s4=[e for e in entries if e['structure_class']=='S4']
    assert s4, 'no actual S4; mock certification is not a physical prototype'
    entry=s4[0];cert=read_json(root/entry['certificate_path']);config=load_benchmark_config()
    verify_certificate(cert,identity(config),entry['full_sha256'])
    assert tuple(cert['witness']) not in TEMPLATES
    for action in TEMPLATES:
        report=evaluate_voltage_dispatch(entry['scenario_id'],dispatch(action,config['bess']),scenario_root=root/'dev')
        assert report['converged'] and not report['success']
    report=evaluate_voltage_dispatch(entry['scenario_id'],dispatch(cert['witness'],config['bess']),scenario_root=root/'dev')
    assert report['success']
