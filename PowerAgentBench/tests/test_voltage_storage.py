from pathlib import Path
import pytest

import poweragentbench.voltage_storage as storage


def test_private_project_storage_is_explicit_and_external_storage_still_works(tmp_path, monkeypatch):
    checkout=tmp_path/'project'
    monkeypatch.setattr(storage,'REPO_ROOT',checkout/'PowerAgentBench')
    assert storage.evaluator_output_root(checkout/'.local-data'/'v3') == (checkout/'.local-data'/'v3').resolve()
    assert storage.evaluator_output_root(tmp_path/'external') == (tmp_path/'external').resolve()
    for path in (checkout,checkout/'.local-data',checkout/'PowerAgentBench'/'results',checkout/'templates',checkout/'.local-data'/'..'/'public'):
        with pytest.raises(ValueError,match='outside PowerAgentBench'):
            storage.evaluator_output_root(path)


def test_completed_route_validates_without_reentering_old_generator(tmp_path, monkeypatch):
    from scripts import run_voltage_route_b as runner
    (tmp_path/'corpus_manifest.json').write_text('{}')
    def read(path):
        return {'total_pf_limit':10} if Path(path).name=='protocol.json' else {'completed':True}
    monkeypatch.setattr(runner,'read_json',read)
    monkeypatch.setattr(runner,'generate',lambda *a,**k:pytest.fail('completed generation must not restart'))
    monkeypatch.setattr(runner,'baselines',lambda _:[])
    monkeypatch.setattr(runner,'validate',lambda _:{'status':'PASS'})
    monkeypatch.setattr(runner,'ledger_count',lambda _:0)
    assert runner.run(tmp_path)['status']=='PASS'
