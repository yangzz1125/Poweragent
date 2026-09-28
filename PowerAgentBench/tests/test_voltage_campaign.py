import json
from datetime import datetime
from decimal import Decimal

import pytest

from poweragentbench.voltage_costs import Campaign, BudgetStop, ledger_totals, read_events
from poweragentbench.openai_client import OpenAIResponsesClient
from poweragentbench.voltage_agentic import LLMVoltageAgent

OFFPEAK = datetime.fromisoformat('2026-09-28T19:00:00+08:00')


def client(campaign, answer='case_summary', tokens=100):
    c = OpenAIResponsesClient(api_key='test-key', model='deepseek-flash', request_hook=campaign, retry_backoff=0)
    c.request_context = dict(campaign_id=campaign.campaign_id, run_id='r', episode_key='e', episode_attempt_id='e:1')
    c._post_once = lambda _: {'output_text': json.dumps({'tool': answer, 'args': {'dispatch': []}}),
                              'usage': {'input_tokens': tokens, 'output_tokens': 1, 'input_tokens_details': {'cached_tokens': 0}}}
    return c


def test_budget_stops_before_next_call_and_does_not_submit(tmp_path):
    with Campaign(tmp_path, episode_limit='0.0001', clock=lambda: OFFPEAK) as campaign:
        c = client(campaign)
        events = []
        out = LLMVoltageAgent(c, name='test', checkpoint_path=tmp_path/'checkpoint.json', event_sink=events.append).run('V0001')
        assert [e['event'] for e in events] == ['episode_start', 'model_response', 'tool_started', 'tool_finished', 'episode_stop']
        assert events[-1]['reason'] == 'episode_cost_limit'
        assert out.termination_reason == 'episode_cost_limit'
        assert not out.paused and out.n_llm_turns == 1 and not out.attempts
        assert ledger_totals(campaign.path)['request_count'] == 1
        assert Decimal(ledger_totals(campaign.path)['accounted_cost_cny']) >= Decimal('0.0001')
        restored = LLMVoltageAgent(c, name='test', checkpoint_path=tmp_path/'checkpoint.json').run('V0001')
        assert restored.termination_reason == 'episode_cost_limit'
        assert ledger_totals(campaign.path)['request_count'] == 1


def test_unknown_timeout_stops_automatic_retry(tmp_path):
    with Campaign(tmp_path, clock=lambda: OFFPEAK) as campaign:
        c = client(campaign)
        def timeout(_):
            raise TimeoutError('secret')
        c._post_once = timeout
        out = LLMVoltageAgent(c, name='test', checkpoint_path=tmp_path/'checkpoint.json').run('V0001')
        assert out.paused and out.termination_reason == 'usage_unknown'
        assert [e['event'] for e in read_events(campaign.path)] == ['started','error']
        assert ledger_totals(campaign.path)['unknown_requests'] == 1


def test_offpeak_pause_resume_preserves_turns_and_spending(tmp_path):
    now = [OFFPEAK]
    with Campaign(tmp_path, clock=lambda: now[0]) as campaign:
        c = client(campaign)
        def first(_):
            now[0] = datetime.fromisoformat('2026-09-29T10:00:00+08:00')
            return {'output_text': '{"tool":"case_summary","args":{}}', 'usage': {'input_tokens': 100,'output_tokens': 10}}
        c._post_once = first
        a = LLMVoltageAgent(c, name='test', checkpoint_path=tmp_path/'checkpoint.json').run('V0001')
        assert a.paused and a.termination_reason == 'offpeak_pause' and a.n_llm_turns == 1
        now[0] = OFFPEAK
        c = client(campaign, answer='submit')
        b = LLMVoltageAgent(c, name='test', recovery=False, checkpoint_path=tmp_path/'checkpoint.json').run('V0001')
        assert not b.paused and b.n_llm_turns == 2
        assert b.termination_reason == 'first_failure_no_recovery'
        assert ledger_totals(campaign.path)['request_count'] == 2


def test_guard_windows_and_lock(tmp_path):
    moment = datetime.fromisoformat('2026-09-28T08:59:00+08:00')
    with Campaign(tmp_path, clock=lambda: moment) as campaign:
        c = client(campaign)
        assert campaign.reason(c.request_context, timeout=90) == 'offpeak_pause'
        with pytest.raises(FileExistsError):
            with Campaign(tmp_path):
                pass
        with pytest.raises(BudgetStop, match='offpeak_pause'):
            c([])
        assert not campaign.path.exists()
    with pytest.raises(ValueError, match='identity/limits'):
        with Campaign(tmp_path, campaign_limit='5'):
            pass
    assert not (tmp_path/'campaign.lock').exists()


def test_failure_preserves_prior_tools_and_fee(tmp_path):
    with Campaign(tmp_path, clock=lambda: OFFPEAK) as campaign:
        c = client(campaign)
        count = [0]
        def post(_):
            count[0] += 1
            if count[0] == 2:
                raise TimeoutError('hidden')
            return {'output_text': '{"tool":"submit","args":{"dispatch":[]}}', 'usage': {'input_tokens': 10,'output_tokens': 5}}
        c._post_once = post
        events = []
        out = LLMVoltageAgent(c, name='test', checkpoint_path=tmp_path/'checkpoint.json', event_sink=events.append).run('V0001')
        assert out.paused and out.termination_reason == 'usage_unknown'
        assert len(out.attempts) == 1 and out.attempts[0]['success'] == 0
        assert any(e.get('outcome') == 'voltage_unresolved' for e in events)
        assert ledger_totals(campaign.path)['request_count'] == 2
        assert Decimal(ledger_totals(campaign.path)['accounted_cost_cny']) > 0
        saved = json.loads((tmp_path/'checkpoint.json').read_text())
        assert len(saved['state']['attempts']) == 1


def test_paid_response_recovered_after_interruption_without_resending(tmp_path):
    with Campaign(tmp_path, clock=lambda: OFFPEAK) as campaign:
        c = client(campaign, answer='submit')
        def interrupt(event):
            if event['event'] == 'model_response':
                raise KeyboardInterrupt()
        with pytest.raises(KeyboardInterrupt):
            LLMVoltageAgent(c, name='test', recovery=False, checkpoint_path=tmp_path/'checkpoint.json', event_sink=interrupt).run('V0001')
        assert ledger_totals(campaign.path)['request_count']==1
        c._post_once = lambda _: pytest.fail('paid response must not be requested twice')
        output = LLMVoltageAgent(c, name='test', recovery=False, checkpoint_path=tmp_path/'checkpoint.json').run('V0001')
        assert len(output.attempts)==1 and output.n_llm_turns==1
        assert ledger_totals(campaign.path)['request_count']==1


def test_approved_reserve_preserves_unknown_and_uses_campaign_budget(tmp_path):
    from poweragentbench.voltage_costs import append_event
    with Campaign(tmp_path, campaign_limit='0.20', clock=lambda: OFFPEAK) as campaign:
        c = client(campaign)
        c._post_once = lambda _: (_ for _ in ()).throw(ConnectionResetError())
        with pytest.raises(BudgetStop, match='usage_unknown'):
            c([])
        request_id = read_events(campaign.path)[0]['request_id']
        append_event(tmp_path/'reservations.jsonl', {'request_id': request_id, 'reserve_cny': '0.20',
                     'approved_by': 'user', 'reason': 'explicit one-request precautionary reserve'})
        totals = ledger_totals(campaign.path)
        assert totals['unknown_requests']==1 and totals['unreserved_unknown_requests']==0
        assert Decimal(totals['accounted_cost_cny'])==0
        assert Decimal(totals['budget_consumed_cny'])==Decimal('0.20')
        assert campaign.reason(c.request_context)=='campaign_cost_limit'
    with Campaign(tmp_path/'other', clock=lambda: OFFPEAK) as campaign:
        c=client(campaign)
        c._post_once = lambda _: (_ for _ in ()).throw(ConnectionResetError())
        with pytest.raises(BudgetStop): c([])
        request_id=read_events(campaign.path)[0]['request_id']
        append_event(campaign.root/'reservations.jsonl', {'request_id':request_id,'reserve_cny':'0.20',
                     'approved_by':'user','reason':'approved for this one failed request'})
        assert campaign.reason(c.request_context) is None  # reserve is campaign-only, not invented episode spend
        c.request_context.update(episode_key='new')
        with pytest.raises(BudgetStop, match='usage_unknown'): c([])  # approval does not cover future failures


def test_approved_policy_reserves_reset_requests_and_retries_within_budget(tmp_path):
    from poweragentbench.voltage_costs import atomic_json
    with Campaign(tmp_path, clock=lambda: OFFPEAK) as campaign:
        atomic_json(tmp_path/'reservation_policy.json', {'approved_by':'user', 'approved_at':OFFPEAK.isoformat(),
                    'reserve_per_unknown_request_cny':'0.20', 'reason':'approved bounded supervised retry policy'})
        c=client(campaign)
        calls=[]
        def post(_):
            calls.append(1)
            if len(calls)<3:
                raise ConnectionResetError()
            return {'output_text':'{}','usage':{'input_tokens':10,'output_tokens':2}}
        c._post_once=post
        assert c([])=='{}'
        totals=ledger_totals(campaign.path)
        assert totals['request_count']==3 and totals['unknown_requests']==2
        assert totals['unreserved_unknown_requests']==0
        assert Decimal(totals['reserved_unknown_cost_cny'])==Decimal('0.40')
        assert Decimal(totals['budget_consumed_cny'])>Decimal('0.40')
        assert c.retry_count_last_call==2


def test_campaign_ceiling_counts_other_runs(tmp_path):
    with Campaign(tmp_path, campaign_limit='0.0001', clock=lambda: OFFPEAK) as campaign:
        c = client(campaign)
        c([])
        c.request_context.update(run_id='another', episode_key='other')
        with pytest.raises(BudgetStop, match='campaign_cost_limit'):
            c([])
        assert ledger_totals(campaign.path)['request_count'] == 1
