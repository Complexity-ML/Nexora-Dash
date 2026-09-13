import json
from dash import html
import plotly.graph_objects as go
from app.business import exploration
from app.dash_ui.components import header, stats, card, link, table, number, filter_control, plot, pager
from app.dash_ui.pages.inventory import ENTITIES,ENV


def selection(query):
    filters=json.loads(query.get('selection','{}'))
    if not isinstance(filters,dict) or len(filters)>10: raise ValueError('Invalid selection')
    return filters


def layout(ctx,query):
    entity=query.get('entity','machines')
    if entity not in ENTITIES: entity='machines'
    dimension=query.get('dimension','subsidiary')
    if dimension not in exploration.DIMENSIONS or entity not in exploration.DIMENSIONS[dimension][3]: dimension='subsidiary'
    split=query.get('split') or None
    if split and (split not in exploration.DIMENSIONS or entity not in exploration.DIMENSIONS[split][3]): split=None
    measure=query.get('measure','count')
    if measure not in exploration.MEASURES or entity not in exploration.MEASURES[measure][2]: measure='count'
    filters={k:v for k,v in selection(query).items() if k in exploration.DIMENSIONS and entity in exploration.DIMENSIONS[k][3]}
    offset=max(0,int(query.get('offset',0)))
    dims=[{'label':v[0],'value':k} for k,v in exploration.DIMENSIONS.items() if entity in v[3]]
    controls=html.Div([
        filter_control('entity','Explorer',entity,[{'label':v,'value':k} for k,v in ENTITIES.items()]),
        filter_control('dimension','Regrouper par',dimension,dims),
        filter_control('split','Croiser avec',split,[{'label':'Aucun croisement','value':''}]+dims),
        filter_control('measure','Mesurer',measure,[{'label':v[0],'value':k} for k,v in exploration.MEASURES.items() if entity in v[2]]),
        filter_control('q','Rechercher',query.get('q'))],className='filters')
    chips=html.Div([html.Span(f'{exploration.DIMENSIONS[k][0]} : {ENV.get(str(v),str(v)) if v is not None else "Non remonté"}',className='badge') for k,v in filters.items()]+([link('Tout effacer','explore',entity=entity,dimension=dimension,measure=measure)] if filters else []),className='actions')
    if query.get('view')=='records':
        data=ctx.call(exploration.records,ctx.wid,entity=entity,filters=filters,query=query.get('q',''),offset=offset,lake=True)
        return html.Div([header('Explorer les éléments','Résultats de votre sélection.'),controls,chips,
            link('← Revenir à la comparaison','explore',**{k:v for k,v in query.items() if k not in ('view','offset')}),
            card(table([('name','Nom'),('subsidiary','Filiale'),('site','Site'),('os','Système')],[dict(r,name=link(r['name'],'inventory',entity=entity,detail=r['id'])) for r in data['rows']])),
            pager('explore',offset,data['total'],**{k:v for k,v in query.items() if k!='offset'})],className='stack')
    data=ctx.call(exploration.aggregate,ctx.wid,entity=entity,dimension=dimension,split=split,measure=measure,filters=filters,query=query.get('q',''),offset=offset,lake=True)
    fig=go.Figure()
    dimensions=data['dimensions']
    top=data['rows'][:20]
    categories=sorted({str(r.get('label1') or 'Non remonté') for r in top}) if len(dimensions)>1 else ['']
    for category in categories:
        rows=[r for r in top if not category or str(r.get('label1') or 'Non remonté')==category]
        fig.add_trace(go.Bar(x=[r['value'] for r in rows],y=[ENV.get(str(r['label0']),str(r['label0'] or 'Non remonté')) for r in rows],orientation='h',name=ENV.get(category,category),
            customdata=[json.dumps({**filters,**{d:r[f'key{i}'] for i,d in enumerate(dimensions)}}) for r in rows]))
    fig.update_layout(barmode='stack',showlegend=len(categories)>1)
    fig.update_yaxes(autorange='reversed')
    tabular=[]
    for r in data['rows']:
        chosen={**filters,**{d:r[f'key{i}'] for i,d in enumerate(dimensions)}}
        tabular.append({'group':' · '.join(ENV.get(str(r.get('label'+str(i))),str(r.get('label'+str(i)) or 'Non remonté')) for i in range(len(dimensions))),
            'value':number(r['value']),'records':number(r['records']),
            'open':link('Explorer →','explore',entity=entity,dimension=dimension,split=split,measure=measure,selection=json.dumps(chosen),view='records',q=query.get('q',''))})
    return html.Div([header('Exploration','Croisez les dimensions du parc et approfondissez chaque résultat.'),controls,chips,
        stats([(ENTITIES[entity],number(data['records']),'Éléments dans la sélection'),(exploration.MEASURES[measure][0],number(data['value']),'Mesure inventoriée'),('Groupes',number(data['groups']),'Combinaisons observées')]),
        card(html.H2('Comparer les répartitions'),html.Small('Cliquez sur une barre pour ouvrir les éléments correspondants. Les 20 premiers groupes de cette page sont affichés.'),plot(fig,'exploration-chart')),
        card(table([('group','Regroupement'),('value',exploration.MEASURES[measure][0]),('records','Éléments'),('open','')],tabular)),
        pager('explore',offset,data['groups'],size=50,**{k:v for k,v in query.items() if k!='offset'})],className='stack')


def quality(ctx,query):
    entity=query.get('entity','machines')
    data=ctx.call(exploration.completeness,ctx.wid,entity=entity,lake=True)
    rows=[dict(r,coverage=f'{(1-r["missing"]/data["total"])*100:.1f} %' if data['total'] else '—',missing=number(r['missing'])) for r in data['fields']]
    return html.Div([header('Qualité des données','Complétude des dimensions dans le périmètre de votre espace.'),
        filter_control('entity','Analyser',entity,[{'label':v,'value':k} for k,v in ENTITIES.items()]),
        card(table([('name','Champ'),('coverage','Valeurs présentes'),('missing','Valeurs absentes')],rows)),
        html.Small('Ces indicateurs décrivent la présence des champs. Ils ne garantissent pas leur exactitude et ne constituent pas une détection PII.',className='muted')],className='stack')
