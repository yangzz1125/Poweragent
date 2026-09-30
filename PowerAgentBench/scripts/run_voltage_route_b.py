"""One-command offline B0-B4 data pipeline. Never calls a model, Test, git or freeze."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from poweragentbench.voltage_case import read_json
from poweragentbench.voltage_storage import evaluator_output_root
from scripts.generate_voltage_structural_corpus import run as generate, write_json
from scripts.run_voltage_structural_baselines import run as baselines, ledger_count
from scripts.validate_voltage_structural_corpus import validate


def run(root):
    root=evaluator_output_root(root)
    # Completed datasets are immutable: validate them, do not re-enter generation
    # using a newer launcher or rewrite their original protocol/source identity.
    if (root/'corpus_manifest.json').exists():
        generation=read_json(root/'exploration/summary.json')
    else:
        generation=generate(root,'all')
    if not (root/'corpus_manifest.json').exists():
        report={'status':'FEASIBILITY_BLOCKED','reason':'no certified Dev candidates','generation':generation}
        write_json(root/'offline_acceptance.json',report);return report
    baseline=baselines(root)
    validation=validate(root)
    report={'status':validation['status'],'generation':read_json(root/'exploration/summary.json'),
            'baseline_summary':baseline,'validation':validation,
            'actual_data_pipeline_pf':sum(ledger_count(root/p) for p in ('exploration/pf_ledger.sqlite','baselines/pf_ledger.sqlite','validation/pf_ledger.sqlite')),
            'model_api_requests':0,'test_run':False,'freeze_approved':False,'tag_created':False,'pushed':False,
            'tests':'Run pytest separately with --offline-pf-report and --v3-root; pipeline PASS alone does not claim tests passed.'}
    if report['actual_data_pipeline_pf']>read_json(root/'exploration/protocol.json')['total_pf_limit']:
        raise RuntimeError('shared offline PF budget exceeded')
    write_json(root/'offline_acceptance.json',report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True)
    print(json.dumps(run(p.parse_args().output_dir),indent=2))
