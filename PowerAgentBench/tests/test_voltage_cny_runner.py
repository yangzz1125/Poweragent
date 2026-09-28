import csv
import json
from datetime import datetime

import pytest

from scripts import run_voltage_experiment_matrix as runner
from scripts.analyze_voltage_trajectories import analyze
from tests.test_voltage_matrix import options
from poweragentbench.openai_client import OpenAIResponsesClient
from poweragentbench.voltage_costs import Campaign, ledger_totals


def test_cny_matrix_resume_events_and_shared_account(tmp_path, monkeypatch):
    class OffpeakCampaign(Campaign):
        def __init__(self, *args, **kwargs):
            kwargs['clock'] = lambda: datetime.fromisoformat('2026-09-28T19:00:00+08:00')
            super().__init__(*args, **kwargs)
    monkeypatch.setattr(runner, 'Campaign', OffpeakCampaign)
    args = options(tmp_path, model='deepseek-flash', api_mode='responses', url='https://api.deepseek.com',
                   campaign_dir=tmp_path/'campaign', max_episodes=2)
    def factory(_):
        client = OpenAIResponsesClient(api_key='DO_NOT_LOG', model='deepseek-flash')
        client._post_once = lambda _: {'output_text': '{"tool":"submit","args":{"dispatch":[]}}',
                                      'usage': {'input_tokens': 10, 'output_tokens': 5}}
        return client
    first = runner.run_matrix(args, factory)
    second = runner.run_matrix(args, factory)
    assert (first['complete'], second['complete']) == (2, 4)
    assert second['request_count'] == 4
    rows = list(csv.DictReader((args.output_dir/'episodes.csv').open()))
    assert all(row['campaign_id']==second['campaign_id'] for row in rows)
    assert all(row['n_api_requests']=='1' for row in rows)
    report = analyze(args.output_dir, args.campaign_dir, tmp_path/'analysis')
    assert report['recorded']==4 and report['planned']==64
    assert ledger_totals(args.campaign_dir/'requests.jsonl')['request_count']==4
    assert 'DO_NOT_LOG' not in (args.output_dir/'events.jsonl').read_text()
    assert not (args.campaign_dir/'campaign.lock').exists()


def test_cny_blocks_legacy_budget_and_non_official_host(tmp_path):
    args = options(tmp_path, model='deepseek-flash', api_mode='responses', url='https://api.deepseek.com',
                   campaign_dir=tmp_path/'campaign', max_total_tokens=100)
    with pytest.raises(ValueError, match='cannot be combined'):
        runner.run_matrix(args)
    args.max_total_tokens=None; args.url='https://proxy.example.com'
    with pytest.raises(ValueError, match='official DeepSeek'):
        runner.run_matrix(args)
