import json
from pathlib import Path

import pandas as pd

from scripts.analyze_voltage_trajectories import analyze


def test_recovery_streaks_and_unobserved_are_distinct(tmp_path):
    run, campaign, output = tmp_path/'run', tmp_path/'campaign', tmp_path/'analysis'
    run.mkdir(); campaign.mkdir()
    conditions = ['I0-V0-R1', 'I1-V0-R1']
    (run/'run.json').write_text(json.dumps({'run_id': 'r', 'planned_tasks': [[c, 'D1', 0] for c in conditions] + [['I0-V0-R0','D2',0]]}))
    rows = []
    for c in conditions:
        rows.append(dict(run_id='r', condition=c, scenario_id='D1', repetition_index=0, episode_attempt=1,
                         recovery=1, status='complete' if c.startswith('I0') else 'paused',
                         success=1 if c.startswith('I0') else None, termination_reason='success' if c.startswith('I0') else 'offpeak_pause',
                         accounted_cost_cny=0, unknown_cost_requests=0, n_llm_turns=4, n_actual_power_flows=3))
    pd.DataFrame(rows).to_csv(run/'episodes.csv', index=False)
    events = []
    def emit(c, turn, kind, **more):
        events.append(dict(event_id=str(len(events)), event=kind, run_id='r', episode_key=json.dumps([c,'D1',0],separators=(',',':')),
                           episode_attempt=1, turn=turn, **more))
    c=conditions[0]
    emit(c,1,'parse_error')
    emit(c,2,'tool_finished',tool='inspect_voltage_state',args={},observation={},outcome='ok')
    emit(c,3,'tool_finished',tool='submit',args={'dispatch': []},outcome='voltage_unresolved',observation={'accepted':False,'verification':{'success':False,'valid_action':True}})
    emit(c,4,'tool_finished',tool='submit',args={'dispatch': []},outcome='ok',observation={'accepted':True,'verification':{'success':True,'valid_action':True}})
    emit(conditions[1],1,'parse_error')
    emit(conditions[1],2,'parse_error')
    (run/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    report = analyze(run,campaign,output)
    assert report['planned']==3 and report['known_success']==1 and report['unresolved']==2
    assert report['success_lower_bound']==1/3 and report['success_upper_bound']==1
    recovery=pd.read_csv(output/'recovery_summary.csv')
    assert recovery.iloc[0]['rate']==0  # final failure probability after first submit failed
    assert pd.isna(recovery.iloc[0]['ci_low'])  # no pseudo-certainty from one scenario
    streaks=pd.read_csv(output/'error_streaks.csv')
    pending=streaks[(streaks.condition==conditions[1]) & (streaks.k==2)].iloc[0]
    assert pd.isna(pending['next_relevant_operation_success']) and pd.isna(pending['final_success'])
    assert (output/'termination.png').exists()
