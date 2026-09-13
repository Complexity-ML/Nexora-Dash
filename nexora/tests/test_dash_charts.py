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


def test_usage_profiles_exclude_invalid_capacity_and_normalize_per_product():
    from app.dash_ui.charts import usage_distribution, usage_duration, capacity_history
    trend=SimpleNamespace(software_name='Test',license_pool_id='id',daily=[
        {'date':'2026-01-01','used':0,'capacity':10},
        {'date':'2026-01-02','used':7,'capacity':0},
        {'date':'2026-01-03','used':10,'capacity':20}])
    assert list(usage_distribution([trend]).data[0].x)==[0,50]
    duration=usage_duration([trend]).data[0]
    assert list(duration.x)==[50,100]
    assert list(duration.y)==[50,0]
    assert list(capacity_history([trend]).data[0].y)==[100,0,200]


def test_shared_tooltip_keeps_series_name_without_secondary_box():
    import plotly.graph_objects as go
    from app.dash_ui.components import plot
    figure=go.Figure(go.Bar(name='Jours actifs',x=[3],y=['Produit'],hovertemplate='%{y}<br>%{x} jours<extra>%{fullData.name}</extra>'))
    rendered=plot(figure).figure
    assert rendered.data[0].hovertemplate=='%{y}<br>%{x} jours<br>%{fullData.name}<extra></extra>'
    assert rendered.layout.hoverlabel.font.color=='#f3f7fb'
    default=plot(go.Figure(go.Scatter(name='Usage',x=[1],y=[2]))).figure
    assert default.data[0].hovertemplate.endswith('%{fullData.name}<extra></extra>')


def test_distribution_has_one_summary_and_preserves_navigation():
    from app.dash_ui.charts import usage_distribution
    from app.dash_ui.components import plot
    trend=SimpleNamespace(software_name='A & B',license_pool_id='pool',daily=[
        {'used':v,'capacity':100} for v in [0,20,40,60,100]])
    figure=plot(usage_distribution([trend])).figure
    box,summary=figure.data
    assert box.hoverinfo=='skip' and box.hovertemplate is None
    assert figure.layout.hovermode=='closest'
    assert 'A &amp; B' in summary.hovertemplate
    for value in ['Minimum : 0,0 %','Premier quartile : 15,0 %','Médiane : 40,0 %',
                  'Troisième quartile : 70,0 %','Maximum : 100,0 %','5 journées']:
        assert value in summary.hovertemplate
    assert set(summary.customdata)=={'#/software?pool=pool'}
    assert min(summary.x)==0 and max(summary.x)==100
    trend.daily=[{'used':1,'capacity':2}]
    assert 'Médiane : 50,0 %' in usage_distribution([trend]).data[1].hovertemplate
