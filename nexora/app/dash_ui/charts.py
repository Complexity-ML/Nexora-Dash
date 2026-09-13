"""Figures built from scoped, published data; no collection or Spark execution."""
from datetime import date, timedelta
from html import escape
from math import floor, ceil
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
            hovertemplate='%{y}<br>'+label+' : %{x:,.0f} installations<extra></extra>')
    # Overlapping quality/activity categories must not be stacked into a false total.
    fig.update_layout(barmode='group',height=max(460,len(rows)*54+130),bargap=.28,bargroupgap=.12)
    fig.update_xaxes(title='Nombre d’installations',tickfont={'size':13})
    fig.update_yaxes(tickfont={'size':13})
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


def usage_distribution(trends):
    """Observed daily ratios only: missing data is never counted as inactivity."""
    fig=go.Figure()
    for index,t in enumerate(trends):
        samples=[100*r['used']/r['capacity'] for r in t.daily if r['capacity']>0]
        if samples:
            color=['#68b4ec','#64d5b2','#f1c777'][index%3]
            fig.add_trace(go.Box(x=samples,name=t.software_name,orientation='h',boxpoints=False,
                quartilemethod='linear',marker_color=color,hoverinfo='skip',
                customdata=[route('software',pool=t.license_pool_id)]*len(samples)))
            ordered=sorted(samples)
            def percentile(fraction):
                # Match Plotly's linear Box interpolation (n*p - 0.5).
                position=max(0,min(len(ordered)-1,len(ordered)*fraction-.5))
                weight=position%1
                return ordered[floor(position)]*(1-weight)+ordered[ceil(position)]*weight
            q1,median,q3=(percentile(p) for p in (.25,.5,.75))
            fmt=lambda value:f'{value:.1f}'.replace('.',',')+' %'
            summary=(f'<b>{escape(t.software_name)}</b><br>{len(samples)} journées observées'
                f'<br>Minimum : {fmt(min(samples))}<br>Premier quartile : {fmt(q1)}'
                f'<br>Médiane : {fmt(median)}<br>Troisième quartile : {fmt(q3)}'
                f'<br>Maximum : {fmt(max(samples))}<extra></extra>')
            # Native Box hover produces five rotated, overlapping labels. A
            # transparent hit area across the row shows one statistical summary.
            targets=[min(samples)+(max(samples)-min(samples))*i/40 for i in range(41)]
            fig.add_scatter(x=targets,y=[t.software_name]*len(targets),mode='markers',
                marker=dict(size=24,opacity=0,color=color),showlegend=False,
                name=t.software_name,hovertemplate=summary,
                customdata=[route('software',pool=t.license_pool_id)]*len(targets))
    fig.update_xaxes(title='Utilisation journalière (%)',rangemode='tozero')
    fig.update_yaxes(autorange='reversed',automargin=True)
    fig.update_layout(showlegend=False,hovermode='closest',height=max(340,44*len(trends)))
    return fig


def usage_duration(trends):
    fig=go.Figure()
    for t in trends:
        samples=sorted([100*r['used']/r['capacity'] for r in t.daily if r['capacity']>0],reverse=True)
        if samples:
            fig.add_scatter(x=[100*(i+1)/len(samples) for i in range(len(samples))],y=samples,
                name=t.software_name,mode='lines',customdata=[route('software',pool=t.license_pool_id)]*len(samples),
                hovertemplate='%{y:.1f} % d’utilisation atteints ou dépassés<br>sur %{x:.1f} % des jours observés<extra>%{fullData.name}</extra>')
    fig.update_xaxes(title='Part des journées observées (%)',range=[0,100])
    fig.update_yaxes(title='Utilisation (%)',rangemode='tozero')
    return fig


def capacity_history(trends):
    """Normalize each pool separately; heterogeneous capacities are never summed."""
    fig=go.Figure()
    for t in trends:
        rows=sorted(t.daily,key=lambda r:str(r['date']))
        reference=next((r['capacity'] for r in rows if r['capacity']>0),None)
        if reference:
            fig.add_scatter(x=[r['date'] for r in rows],y=[100*r['capacity']/reference for r in rows],
                name=t.software_name,mode='lines',line_shape='hv',
                customdata=[route('software',pool=t.license_pool_id)]*len(rows),
                hovertemplate='%{x}<br>Indice de capacité : %{y:.1f}<extra>%{fullData.name}</extra>')
    fig.update_yaxes(title='Indice · première capacité positive = 100',rangemode='tozero')
    return fig
