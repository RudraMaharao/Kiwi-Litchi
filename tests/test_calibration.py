import copy
import pytest
from kiwi_litchi.intelligence import calibration_report
from kiwi_litchi.common import UserError


def report(month='2026-08',n=40,score=.9,correct=True):
    return {'month':month,'model':'test@digest','n':n,'top1_accuracy':1 if correct else 0,
            'kiwi_baseline_accuracy':.7,'rows':[{'expected':'A','predicted':'A' if correct else 'B','vote_share':score} for _ in range(n)]}


def test_gate_requires_separate_later_month():
    with pytest.raises(UserError):calibration_report(report(),report())


def test_gate_rejects_model_change():
    test=report('2026-09');test['model']='different@digest'
    with pytest.raises(UserError):calibration_report(report(),test)


def test_calibration_needs_minimum_sample():
    result=calibration_report(report(n=29),report('2026-09'))
    assert not result['enabled'] and result['threshold']>1


def test_holdout_needs_minimum_sample():
    assert not calibration_report(report(),report('2026-09',n=29))['enabled']


def test_gate_requires_beating_kiwi():
    test=report('2026-09');test['kiwi_baseline_accuracy']=1
    assert not calibration_report(report(),test)['enabled']


def test_holdout_failure_does_not_retune_threshold():
    good=report('2026-09');bad=copy.deepcopy(good)
    for row in bad['rows'][:5]:row['predicted']='B'
    first=calibration_report(report(),good);second=calibration_report(report(),bad)
    assert first['enabled'] and not second['enabled']
    assert first['threshold']==second['threshold']


def test_gate_requires_coverage():
    test=report('2026-09',n=100)
    for row in test['rows'][60:]:row['vote_share']=.1
    result=calibration_report(report(),test)
    assert result['test_ready_accuracy']==1 and result['test_ready_coverage']==.6
    assert not result['enabled']


def test_calibration_excludes_low_quality_votes():
    cal=report(n=100)
    for row in cal['rows'][80:]:row.update(predicted='B',vote_share=.6)
    result=calibration_report(cal,report('2026-09'))
    assert result['enabled'] and result['threshold']==.7
