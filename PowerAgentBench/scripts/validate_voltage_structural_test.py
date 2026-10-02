"""Offline v3 Test validation: integrity, Dev/Test independence, full independent template replay and tool leakage checks.

Mirrors scripts/validate_voltage_structural_corpus.py (Dev) for the sealed Test split. No model API, no freeze.
"""
from __future__ import annotations

import argparse
import itertools
import json
from collections import Counter
from pathlib import Path

from poweragentbench.voltage_case import (load_benchmark_config, load_scenario_network, read_json, sha256_file, write_pandapower_json)
from poweragentbench.voltage_evaluator import evaluate_voltage_dispatch
from poweragentbench.voltage_freeze import digest
from poweragentbench.voltage_structure import (PFStore, TEMPLATES, dispatch, identity, near_duplicate, physical_fingerprint,
                                               physical_vector, verify_certificate)
from poweragentbench.voltage_tools import VoltageToolServer
from scripts.generate_voltage_structural_corpus import make_candidate, write_json
from scripts.validate_voltage_structural_corpus import assert_no_private_keys

DEV_ROOT = Path(__file__).resolve().parents[2] / ".local-data" / "voltage_structure_v3"
PER_CLASS = 24


def validate(root, dev_root=DEV_ROOT):
    corpus = read_json(root / 'corpus_manifest.json')
    protocol = read_json(root / 'exploration/protocol.json')
    if corpus['corpus_version'] != 'structure-v3' or corpus['num_test'] != 96 or corpus['status'] != 'TEST_BUILT':
        raise ValueError('not a built v3 Test corpus')
    if corpus['main_authorized'] is not False:
        raise ValueError('Test must not be authorized for Main by the generator')
    if digest({k: v for k, v in corpus.items() if k != 'dataset_sha256'}) != corpus['dataset_sha256']:
        raise ValueError('corpus digest mismatch')
    if sha256_file(root / 'test/manifest.json') != corpus['split_manifest_sha256']['test']:
        raise ValueError('Test manifest mismatch')
    if sha256_file(root / 'evaluator_private/witnesses.json') != corpus['witnesses_sha256']:
        raise ValueError('witness artifact mismatch')
    config = load_benchmark_config()
    ident = identity(config)
    if corpus['numerical_identity'] != ident or corpus['generation_protocol_sha256'] != digest(protocol):
        raise ValueError('numeric/protocol identity mismatch')
    entries = read_json(root / 'test/manifest.json')['scenarios']
    if digest({r['candidate_id']: r['certificate_sha256'] for r in entries}) != corpus['structure_evidence_sha256']:
        raise ValueError('evidence collection mismatch')
    if len(entries) != 96 or len({e['scenario_id'] for e in entries}) != 96:
        raise ValueError('expected 96 unique Test scenarios')

    # Dev/Test independence, recomputed from the frozen Dev manifest and the physical vectors on disk.
    dev_entries = read_json(dev_root / 'dev/manifest.json')['scenarios']
    dev_families = {e['operating_family_id'] for e in dev_entries}
    dev_fingerprints = {e['physical_fingerprint'] for e in dev_entries}
    dev_vectors = [physical_vector(load_scenario_network(e['scenario_id'], dev_root / 'dev')) for e in dev_entries]

    output = root / 'validation'
    output.mkdir(exist_ok=True)
    validation_identity = {'numeric': ident, 'dataset_sha256': corpus['dataset_sha256'], 'validator_sha256': sha256_file(__file__),
                           'tools_sha256': sha256_file(Path(__file__).parents[1] / 'poweragentbench/voltage_tools.py')}
    store = PFStore(output / 'pf_ledger.sqlite', validation_identity, 200000)
    vectors, families, checks = [], set(), []
    try:
        for entry in entries:
            sid = entry['scenario_id']
            net = load_scenario_network(sid, root / 'test')
            generated, _ = make_candidate(int(entry['candidate_id'][1:]), protocol, config)
            if physical_fingerprint(generated) != entry['physical_fingerprint']:
                raise ValueError('sampled physical fingerprint mismatch')
            reconstructed = output / 'reconstructed' / f'{sid}.json'
            write_pandapower_json(generated, reconstructed)
            if sha256_file(reconstructed) != entry['full_sha256']:
                raise ValueError('serialized snapshot does not match the fixed recipe/topology')
            vector = physical_vector(net)
            roundoff = max(abs(a - b) for a, b in zip(vector, physical_vector(generated)))
            if roundoff > 1e-12:
                raise ValueError('serialized operating point differs beyond roundoff')
            if entry['operating_family_id'] in families or any(near_duplicate(vector, v) for v in vectors):
                raise ValueError('duplicate family/near state inside Test')
            if (entry['operating_family_id'] in dev_families or entry['physical_fingerprint'] in dev_fingerprints
                    or any(near_duplicate(vector, v) for v in dev_vectors)):
                raise ValueError(f'Test scenario {sid} duplicates a Dev family/state')
            families.add(entry['operating_family_id'])
            vectors.append(vector)
            path = root / entry['certificate_path']
            if sha256_file(path) != entry['certificate_sha256']:
                raise ValueError('certificate artifact mismatch')
            cert = read_json(path)
            verify_certificate(cert, ident, entry['full_sha256'])
            if cert['structure_class'] != entry['structure_class']:
                raise ValueError('entry class mismatch')
            results, zero_report = {}, None
            for a, expected in zip(TEMPLATES, cert['template_results']):
                report = store.call([sid, entry['full_sha256'], 'template', a], 'validation_templates/' + sid,
                                    lambda a=a: evaluate_voltage_dispatch(sid, dispatch(a, config['bess']), scenario_root=root / 'test'))
                if not report['converged'] or bool(report['success']) != expected['success']:
                    raise ValueError(f'independent template mismatch: {sid} {a}')
                for key in ('min_vm_pu', 'max_vm_pu', 'voltage_violation_magnitude'):
                    if abs(report['final_state'][key] - expected['state'][key]) > 1e-10:
                        raise ValueError(f'template numeric drift: {sid} {a}')
                results[a] = expected
                if a == (0, 0, 0, 0):
                    zero_report = report
            witness = store.call([sid, entry['full_sha256'], 'witness'], 'validation_witness/' + sid,
                                 lambda: evaluate_voltage_dispatch(sid, dispatch(cert['witness'], config['bess']), scenario_root=root / 'test'))
            if not witness['success']:
                raise ValueError('independent witness failed')
            if entry['fragile']:
                again = store.call([sid, entry['full_sha256'], 'fragile_repeat'], 'validation_fragile/' + sid,
                                   lambda: evaluate_voltage_dispatch(sid, dispatch(cert['witness'], config['bess']), scenario_root=root / 'test'))
                if again['final_state'] != witness['final_state']:
                    raise ValueError('fragile witness unstable')
            for i, v, r in itertools.product((False, True), repeat=3):
                server = VoltageToolServer(sid, scenario_root=root / 'test', domain_interface=i, verification=v, recovery=r,
                                           evaluation_fn=lambda *a, **k: zero_report)
                for tool in server.allowed_tools:
                    observation, _ = server.execute(tool, {'dispatch': []})
                    assert_no_private_keys(observation)
            public = read_json(root / 'test' / entry['public_path'])
            assert_no_private_keys(public)
            checks.append({'scenario_id': sid, 'structure_class': entry['structure_class'], 'independent_templates': len(results),
                           'witness_success': True, 'serialization_max_roundoff': roundoff,
                           'all_eight_tool_conditions_no_leakage': True, 'public_card_no_private_keys': True, 'fragile': entry['fragile']})
            write_json(output / 'checks.json', checks)
        counts = Counter(e['structure_class'] for e in entries)
        s4_families = {e['spatial_family_id'] for e in entries if e['structure_class'] == 'S4'}
        complete = all(counts[s] == PER_CLASS for s in ('S1', 'S2', 'S3', 'S4')) and len(s4_families) >= 2
        result = {'status': 'PASS' if complete else 'FEASIBILITY_BLOCKED', 'counts': dict(counts), 's4_spatial_families': len(s4_families),
                  'dev_test_independent': True, 'actual_pf_calls': store.count, 'pf_by_phase': store.totals(), 'checks': checks,
                  'model_api_requests': 0, 'test_run': False,
                  'warning': 'PASS is offline structure/data validation, not Main authorization or freeze'}
        write_json(output / 'report.json', result)
        return result
    finally:
        store.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--corpus-root', type=Path, required=True)
    p.add_argument('--dev-root', type=Path, default=DEV_ROOT)
    a = p.parse_args()
    print(json.dumps(validate(a.corpus_root.resolve(), a.dev_root.resolve()), indent=2))
