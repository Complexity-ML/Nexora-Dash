"""Figures built from scoped, published data; no collection or Spark execution."""
from datetime import date, timedelta
import plotly.graph_objects as go
from app.dash_ui.components import route


def usage_heatmap(trends):
    days=[str(r['date']) for t in trends for r in t.daily]
    if not days:return go.Figure()
    start,end=date.fromisoformat(min(days)),date.fromisoformat(max(days))
    axis=[(start+timedelta(days=i)).isoformat() for i in range((end-start).days+1)]
    values=[];targets=[]
    for trend in trends:
        samples={str(r['date']):r for r in trend.daily}
        values.append([100*samples[d]['used']/samples[d]['capacity'] if d in samples and samples[d]['capacity']>0 else None for d in axis])
        targets.append([route('software',pool=trend.license_pool_id)]*len(axis))
    fig=go.Figure(go.Heatmap(x=axis,y=[t.software_name for t in trends],z=values,
        customdata=targets,zmin=0,zmax=100,colorscale=[[0,'#203d50'],[.35,'#5ba4ca'],[.7,'#a9d9d0'],[1,'#e7ad68']],
        hoverongaps=False,colorbar={'title':'Usage %'},hovertemplate='%{y}<br>%{x}<br>%{z:.1f} %<extra></extra>'))
    fig.update_yaxes(autorange='reversed',automargin=True)
    return fig


def installation_activity(rows):
    rows=sorted(rows,key=lambda r:r['installations_without_usage'],reverse=True)[:15]
    fig=go.Figure()
    for key,label,color in [('installations_active','Avec activité','#6fc6b0'),('installations_without_usage','Sans activité · relevés complets','#e7ad68'),('installations_incomplete','Relevés incomplets','#6d8193')]:
        fig.add_bar(y=[r['software_name'] for r in rows],x=[r.get(key) for r in rows],name=label,orientation='h',marker_color=color,
            customdata=[route('savings',product=r.get('software_id') or r.get('license_pool_id')) for r in rows],
            hovertemplate='%{y}<br>%{x:,.0f} installations<extra>%{fullData.name}</extra>')
    # Overlapping quality/activity categories must not be stacked into a false total.
    fig.update_layout(barmode='group')
    fig.update_yaxes(autorange='reversed',automargin=True)
    return fig


def capacity_pressure(trends):
    rows=[t for t in trends if t.capacity>0]
    fig=go.Figure(go.Scatter(x=[t.capacity for t in rows],y=[100*t.utilization_rate for t in rows],mode='markers',
        text=[t.software_name for t in rows],customdata=[route('software',pool=t.license_pool_id) for t in rows],
        marker={'size':18,'color':[100*t.utilization_rate for t in rows],'colorscale':'Tealrose','showscale':False},
        hovertemplate='%{text}<br>Capacité : %{x}<br>Usage moyen : %{y:.1f} %<extra></extra>'))
    fig.update_xaxes(title='Capacité du pool');fig.update_yaxes(title='Utilisation moyenne (%)',rangemode='tozero')
    return fig


def opportunity_ranking(candidates):
    rows=sorted(candidates,key=lambda r:r.recovery_potential,reverse=True)
    fig=go.Figure(go.Bar(x=[r.recovery_potential for r in rows],y=[r.software_name for r in rows],orientation='h',
        customdata=[route('software',pool=r.license_pool_id) for r in rows],marker_color='#e7ad68',
        hovertemplate='%{y}<br>%{x} unités à examiner<extra></extra>'))
    fig.update_yaxes(autorange='reversed',automargin=True)
    return fig
