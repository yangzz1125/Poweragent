import pytest
from scripts.study_voltage_shortcuts import classify, uniform_bisection


@pytest.mark.parametrize('condition,sign', [('UNDERVOLTAGE',1),('OVERVOLTAGE',-1)])
def test_bisection_uses_feedback_without_oracle(condition, sign):
    calls=[]
    def evaluate(values):
        calls.append(values)
        assert len(set(values))==1
        power=values[0]*sign
        under = power<1 if sign>0 else power>1
        over = power>1 if sign>0 else power<1
        return {'success':power==1,'converged':True,'final_state':{'undervoltage_buses':[1] if under else [],'overvoltage_buses':[1] if over else []}}
    ok, trace, reason=uniform_bisection(evaluate,condition)
    assert ok and reason=='success' and len(trace)==3
    assert [values[0]*sign for values in calls]==[.75,1.25,1.0]


def test_bisection_stops_when_uniform_feedback_conflicts():
    report={'success':False,'converged':True,'final_state':{'undervoltage_buses':[1],'overvoltage_buses':[2]}}
    ok, trace, reason=uniform_bisection(lambda _:report,'UNDERVOLTAGE')
    assert not ok and len(trace)==1 and reason=='mixed_violation'
    with pytest.raises(ValueError):uniform_bisection(lambda _:report,'MIXED')


def test_classes_are_explicit_template_coverage_not_difficulty_scores():
    assert classify(True,1,1,1)=='all_bess_full_power'
    assert classify(False,1,1,1)=='uniform_interior'
    assert classify(False,0,1,1)=='single_bess_nonuniform'
    assert classify(False,0,0,1)=='zero_full_combination'
    assert classify(False,0,0,0)=='outside_tested_templates'
