import itertools
import json
import random
import shutil

import pytest

from poweragentbench.voltage_case import DEFAULT_SCENARIO_ROOT, read_json, sha256_file
from scripts.study_voltage_landscape import sample_grid, study, wilson


def test_grid_sampling_is_unique_reproducible_and_complete():
    axes = [[-.25, 0, .25], [0, .5]]
    a = sample_grid(axes, 99, random.Random(1))
    assert set(a) == set(itertools.product(*axes)) and len(a) == 6
    assert a == sample_grid(axes, 99, random.Random(1))
    assert wilson(0, 256)[1] > 0
    assert wilson(256, 256)[0] < 1


def test_landscape_only_evaluates_verified_dev_and_keeps_artifacts(tmp_path):
    root=tmp_path/'corpus'/'dev'
    manifest=read_json(DEFAULT_SCENARIO_ROOT/'manifest.json')
    entry=manifest['scenarios'][0]
    entry.update(difficulty='medium', severity=read_json(DEFAULT_SCENARIO_ROOT/entry['public_path'])['initial_state']['voltage_violation_magnitude'])
    for key in ('full_path','public_path'):
        dst=root/entry[key]; dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(DEFAULT_SCENARIO_ROOT/entry[key],dst)
    manifest['scenarios']=[entry]
    (root/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    (root.parent/'corpus_manifest.json').write_text(json.dumps({'dataset_sha256':'test','split_manifest_sha256':{'dev':sha256_file(root/'manifest.json')}}))
    witness=next(x for x in read_json(DEFAULT_SCENARIO_ROOT/'private'/'witnesses.json') if x['scenario_id']==entry['scenario_id'])
    private=root.parent/'evaluator_private';private.mkdir()
    (private/'witnesses.json').write_text(json.dumps([{**witness,'split':'dev'}]))
    before=sha256_file(root/entry['full_path'])
    result=study(root,tmp_path/'study',samples=8)
    assert result['cases']==1 and result['actual_power_flows']>0
    assert sha256_file(root/entry['full_path'])==before
    with pytest.raises(ValueError,match='must be new'):
        study(root,tmp_path/'study',samples=8)
    (root/'manifest.json').write_text('{}')
    with pytest.raises(ValueError,match='verified Dev'):
        study(root,tmp_path/'bad')
