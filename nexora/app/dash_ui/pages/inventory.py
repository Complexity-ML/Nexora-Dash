from dash import html
import json
import plotly.graph_objects as go
from app.business import exploration
from app.business.errors import BusinessError
from app.business import inventory_service as service
from app.dash_ui.components import header, stats, card, link, table, number, empty, filter_control, pager, plot, route

ENTITIES={'machines':'Machines et VM','users':'Utilisateurs','sites':'Sites'}
ENV={'production':'Production','development':'Développement','test':'Test','active':'Actif','inactive':'Inactif',
     'physical':'Physique','virtual':'VM','employee':'Salarié','contractor':'Prestataire'}


def options(value, fallback):
    result=[{'label':fallback,'value':''}]
    for item in value:
        if isinstance(item,dict):
            key=item.get('id') or item.get('value') or item.get('subsidiary_id') or item.get('site_id')
            result.append({'label':(str(item.get('label'))+' · '+str(item['description']) if item.get('description') else item.get('name') or item.get('label') or str(key)),'value':key})
        else: result.append({'label':str(item),'value':item})
    return result


def layout(ctx, query):
    entity=query.get('entity','machines')
    if entity not in ENTITIES: entity='machines'
    offset=max(0,int(query.get('offset',0)))
    filters={k:query.get(k,'') for k in ('subsidiary','country','region','site','kind','environment')}
    data=ctx.call(service.inventory,ctx.wid,entity=entity,q=query.get('q','')[:200],
                  offset=offset,limit=25,detail=query.get('detail',''),**filters,lake=True)
    counts=data.get('counts',{})
    if query.get('detail'):
        return detail(data, entity, ctx, query)
    available=data.get('filters',{})
    controls=[filter_control('q','Rechercher dans le parc',query.get('q'))]
    for key,label in [('subsidiary','Filiale'),('country','Pays'),('region','Région'),('site','Site')]:
        controls.append(filter_control(key,label,filters[key],options(available.get({'subsidiary':'subsidiaries','country':'countries','region':'regions','site':'sites'}[key],[]),'Tous')))
    rows=[]
    for row in data.get('rows',[]):
        identity=row.get({'machines':'machine_id','users':'user_id','sites':'site_id'}[entity]) or row.get('id')
        name=row.get('name') or row.get('display_name') or identity
        product_count=len(row.get('installed_products',[])) or len(row.get('software',[]))
        rows.append({'name':link(name,'inventory',entity=entity,detail=identity),
            'description':row.get('operating_system') or row.get('department') or row.get('city') or '—',
            'site':html.Div([html.Strong(row.get('site') or row.get('country') or '—'),html.Small(row.get('subsidiary') or '')]),
            'detail':number(product_count) if entity!='sites' else number(row.get('machines')),
            'action':link('→','inventory',entity=entity,detail=identity)})
    charts=[]
    chart_filters={k:v for k,v in filters.items() if v and k in exploration.DIMENSIONS and entity in exploration.DIMENSIONS[k][3]}
    dimensions={'machines':[('kind','Composition du parc'),('environment','Environnements')],
                'users':[('employment_type','Salariés et prestataires'),('department','Départements')],
                'sites':[('country','Implantations par pays'),('region','Régions')]}[entity]
    for dimension,title in dimensions:
        try:
            grouped=ctx.call(exploration.aggregate,ctx.wid,entity=entity,dimension=dimension,measure='count',filters=chart_filters,query=query.get('q','')[:200],limit=12,lake=True)
        except BusinessError as exc:
            if exc.status_code!=409:raise
            continue
        groups=grouped['rows']
        targets=[route('explore',entity=entity,dimension=dimension,selection=json.dumps({**chart_filters,dimension:r['key0']}),view='records',q=query.get('q')) for r in groups]
        labels=[ENV.get(str(r['label0']),str(r['label0'] or 'Non remonté')) for r in groups]
        if dimension in ('kind','employment_type'):
            fig=go.Figure(go.Pie(labels=labels,values=[r['value'] for r in groups],hole=.65,customdata=targets,textinfo='percent',hovertemplate='%{label}<br>%{value} · %{percent}<extra></extra>'))
        else:
            fig=go.Figure(go.Bar(y=labels,x=[r['value'] for r in groups],orientation='h',customdata=targets))
            fig.update_yaxes(autorange='reversed',automargin=True)
        charts.append(card(html.H2(title),html.Small('Dans la sélection courante · cliquez pour approfondir.'),plot(fig,{'type':'insight-chart','key':'inventory-'+dimension})))
    return html.Div([header('Inventaire','Machines, utilisateurs et implantations de votre périmètre.'),
        stats([(name,number(counts.get(key)),'Dans votre périmètre') for key,name in ENTITIES.items()]),
        html.Nav([link(name,'inventory',entity=key,subsidiary=filters['subsidiary']) for key,name in ENTITIES.items()],className='tabs'),
        html.Div(controls,className='filters'),
        html.Div([html.H2(ENTITIES[entity]),html.Span(f'{number(data.get("total",0))} résultats'),link('Réinitialiser','inventory',entity=entity)],className='section-heading'),
        html.Div([filter_control('kind','Type',filters['kind'],[{'label':'Tout le parc','value':''},{'label':'Machines physiques','value':'physical'},{'label':'Machines virtuelles','value':'virtual'}]),
                  filter_control('environment','Environnement',filters['environment'],[{'label':'Tous','value':''}]+[{'label':ENV[k],'value':k} for k in ('production','test','development')])],className='filters') if entity=='machines' else None,
        html.Div(charts,className='settings-profile'),
        card(table([('name',ENTITIES[entity]),('description','Système / activité'),('site','Implantation'),('detail','Logiciels' if entity!='sites' else 'Machines'),('action','')],rows)),
        pager('inventory',offset,data.get('total',0),entity=entity,q=query.get('q',''),**filters),
        html.Small('Données fictives' if data.get('is_demo') else 'Source : DIGIMON',className='muted')],className='stack')


def detail(data, entity, ctx, query):
    if not data.get('rows'): return empty('Cet élément ne figure pas dans votre périmètre.')
    row=data['rows'][0]
    title=row.get('name') or row.get('display_name') or 'Site'
    products=row.get('installed_products',[])
    observations=row.get('observations',[])
    software=ctx.call(service.inventory_software,ctx.wid,lake=True)
    names={p.get('license_pool_id') or p['software_id']:p['name'] for p in software}
    installations=[{'name':p.get('name','—'),'version':p.get('version') or '—'} for p in products]
    if not installations:
        installations=[{'name':names.get(key,key),'version':'—'} for key in row.get('software',[])]
    configuration=[('operating_system','Système'),('cpu_cores','Cœurs'),('memory_gb','Mémoire (Go)'),('environment','Environnement'),
        ('department','Département'),('employment_type','Profil'),('email','E-mail'),('status','Statut')]
    config=[{'name':label,'value':ENV.get(str(row[key]),str(row[key]))} for key,label in configuration if row.get(key) is not None]
    relations=[]
    if row.get('host_id'): relations.append(link('Hôte →','inventory',entity='machines',detail=row['host_id']))
    for mid in row.get('machines',[]):
        relations.append(link(mid,'inventory',entity='machines',detail=mid))
    if entity=='sites': relations.append(link('Explorer les machines du site →','inventory',entity='machines',site=row['site_id']))
    return html.Div([link('← '+ENTITIES[entity],'inventory',entity=entity),
        header(title,' · '.join(str(row.get(k)) for k in ('subsidiary','site','country') if row.get(k))),
        html.Div([card(html.H2('Configuration'),table([('name',''),('value','')],config)),
                  card(html.H2('Logiciels observés'),table([('name','Produit'),('version','Version')],installations))],className='split'),
        card(html.H2('Relations'),html.Div(relations,className='stack') if relations else empty('Aucune relation complémentaire remontée.')),
        html.Details([html.Summary('Provenance'),html.P('DIGIMON · '+str(row.get('digimon_reported_source') or 'Inventaire consolidé'))])],className='stack')
