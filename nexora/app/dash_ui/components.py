from urllib.parse import urlencode
import json
import re
from dash import html, dcc
import plotly.graph_objects as go


DROPDOWN_LABELS = {
    'select_all': 'Tout sélectionner', 'deselect_all': 'Tout désélectionner',
    'selected_count': '{num_selected} sélectionnés', 'search': 'Rechercher…',
    'clear_search': 'Effacer la recherche', 'clear_selection': 'Effacer la sélection',
    'no_options_found': 'Aucun résultat',
}


def number(value):
    if value is None:
        return '—'
    return f'{value:,.0f}'.replace(',', '\u202f')


def money(cents):
    return 'À renseigner' if cents is None else f'{cents/100:,.2f} €'.replace(',', '\u202f').replace('.', ',')


def route(page, **query):
    query = {k:v for k,v in query.items() if v is not None and v != ''}
    return '#/'+page+('?' + urlencode(query) if query else '')


def link(label, page, **query):
    return dcc.Link(label, href=route(page, **query), className='text-link')


def header(title, subtitle, actions=None):
    return html.Header([html.Div([html.Div('NEXORA / SAM INTELLIGENCE', className='eyebrow'),
        html.H1(title), html.P(subtitle)]), html.Div(actions or [], className='actions')], className='page-header')


def card(*children, className=''):
    return html.Section(list(children), className='card '+className)


def stats(items):
    return html.Div([card(html.Span(label, className='muted'), html.Strong(value, className='metric'),
        html.Small(caption)) for label,value,caption in items], className='stats')


def empty(text):
    return html.Div(text, className='empty', role='status')


def table(columns, rows):
    return html.Div(html.Table([html.Thead(html.Tr([html.Th(label, scope='col') for _,label in columns])),
        html.Tbody([html.Tr([html.Td(row.get(key, '—')) for key,_ in columns]) for row in rows])]), className='table-scroll') if rows else empty('Aucun résultat pour cette sélection.')


def field(key, label, value=None, *, options=None, kind='text', **kwargs):
    identifier={'type':'field','key':key}
    if options is not None:
        control=dcc.Dropdown(labels=DROPDOWN_LABELS, id=identifier, options=options, value=value, clearable=False, **kwargs)
    elif kind == 'textarea':
        control=dcc.Textarea(id=identifier, value=value or '', **kwargs)
    else:
        control=dcc.Input(id=identifier, value=value, type=kind, **kwargs)
    return html.Div([html.Label(label, htmlFor=json.dumps(identifier,sort_keys=True,separators=(",",":"))), control], className='field')


def action(label, name, *, disabled=False, danger=False):
    return html.Button(label, id={'type':'action','name':name}, n_clicks=0,
        disabled=disabled, className='button danger' if danger else 'button')


def filter_control(key, label, value=None, options=None):
    identifier={'type':'filter','key':key}
    control = (dcc.Dropdown(labels=DROPDOWN_LABELS, id=identifier, options=options, value=value or '', clearable=False)
        if options is not None else dcc.Input(id=identifier, value=value or '', type='search', debounce=True, placeholder=label))
    return html.Div([html.Label(label, htmlFor=json.dumps(identifier,sort_keys=True,separators=(",",":"))), control], className='field')


def pager(page, offset, total, size=25, **query):
    offset = int(offset)
    return html.Div([link('← Précédent', page, **query, offset=max(0, offset-size)) if offset else html.Span(),
        html.Span(f'{number(offset+1) if total else 0}–{number(min(offset+size,total))} sur {number(total)}'),
        link('Suivant →',page,**query,offset=offset+size) if offset+size<total else html.Span()], className='pagination')


def plot(figure, identifier=None):
    # Plotly renders <extra> in a separate, theme-dependent box. Keep all text
    # in the main high-contrast label, including the series name.
    for trace in figure.data:
        if not hasattr(trace, 'hovertemplate'):
            continue
        template=trace.hovertemplate
        if isinstance(template,str):
            extra=re.search(r'<extra>(.*?)</extra>',template,re.DOTALL)
            if extra:
                label=extra.group(1)
                trace.hovertemplate=template[:extra.start()]+('<br>'+label if label else '')+template[extra.end():]+'<extra></extra>'
            else:
                trace.hovertemplate=template+('<br>%{fullData.name}' if trace.name else '')+'<extra></extra>'
        elif template is None:
            value='%{label}<br>%{value}<br>%{percent}' if trace.type=='pie' else '%{x}<br>%{y}'
            if trace.type=='heatmap': value+='<br>%{z}'
            trace.hovertemplate=value+('<br>%{fullData.name}' if trace.name else '')+'<extra></extra>'
    figure.update_layout(template='plotly_dark', paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font=dict(family='Arial, sans-serif', color='#dbe5ee'), margin=dict(l=45,r=20,t=20,b=40),
        height=figure.layout.height or 400, colorway=['#68b4ec','#64d5b2','#f1c777'], legend=dict(orientation='h',y=-.22),
        hoverlabel=dict(bgcolor='#18232e',bordercolor='#8dc4e7',font=dict(color='#f3f7fb',size=14),namelength=-1),
        uirevision='nexora')
    props={'figure':figure, 'config':{'displaylogo':False,'scrollZoom':False}, 'className':'chart'}
    if identifier: props['id']=identifier
    return dcc.Graph(**props)


def daily_figure(trends):
    days={}
    for trend in trends:
        for row in trend.daily:
            entry=days.setdefault(str(row['date']), [0,0,0])
            entry[0]+=int(row['used']); entry[1]+=int(row['capacity']); entry[2]+=1
    complete=[(d,used/cap*100 if cap>0 and n==len(trends) else None) for d,(used,cap,n) in sorted(days.items())]
    fig=go.Figure(go.Scatter(x=[r[0] for r in complete],y=[r[1] for r in complete],mode='lines',
        name='Utilisation',connectgaps=False,line=dict(width=2),fill='tozeroy',fillcolor='rgba(104,180,236,.08)'))
    fig.update_yaxes(ticksuffix=' %',rangemode='tozero')
    return fig
