from types import SimpleNamespace
from app.dash_ui.charts import usage_heatmap, installation_activity


def test_heatmap_preserves_missing_days_and_zero_activity():
    trend=SimpleNamespace(software_name='Test',license_pool_id='id',daily=[
        {'date':'2026-01-01','used':0,'capacity':10},
        {'date':'2026-01-03','used':3,'capacity':0},
        {'date':'2026-01-04','used':5,'capacity':10}])
    trace=usage_heatmap([trend]).data[0]
    assert list(trace.z[0])==[0,None,None,50]
    assert trace.customdata[0][0]=='#/software?pool=id'


def test_activity_does_not_stack_overlapping_populations():
    figure=installation_activity([{'software_name':'Test','software_id':'a','installations_active':4,
        'installations_without_usage':2,'installations_incomplete':3}])
    assert figure.layout.barmode=='group'
    assert [trace.x[0] for trace in figure.data]==[4,2,3]
    assert figure.data[0].customdata[0]=='#/savings?product=a'
