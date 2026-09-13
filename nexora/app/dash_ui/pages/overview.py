from dash import html
import plotly.graph_objects as go
from app.business import exploration
from app.business.errors import BusinessError
from app.dash_ui.components import header, stats, card, link, table, number, plot, daily_figure, empty, route, filter_control
from app.business import inventory_service as inventory


def layout(ctx, query):
    try:summary=ctx.summary()
    except BusinessError as exc:
        if exc.status_code!=409:raise
        summary=None
    estate=ctx.call(inventory.inventory,ctx.wid,limit=1,lake=True)
    counts=estate.get('counts',{})
    if summary is None and estate.get('available') is False:
        return html.Div([header('Votre parc, dans la durée.','Les données apparaîtront après leur collecte et leur publication.'),
            empty('Aucun inventaire publié. Les volumes du parc ne sont pas encore connus.'),
            link('Consulter le Data Lake →','lake')],className='stack')
    if summary is None:
        return html.Div([header('Votre parc, dans la durée.','L’inventaire reste consultable pendant la préparation des analyses.'),
            stats([('Machines et VM',number(counts.get('machines')),'Dans votre périmètre'),
                   ('Utilisateurs',number(counts.get('users')),'Dans votre périmètre'),
                   ('Sites',number(counts.get('sites')),'Implantations observées')]),
            empty('Les analyses de capacité ne sont pas encore publiées.'),
            html.Div([link('Explorer le parc →','inventory'),link('Parc logiciel →','software'),link('Licences →','licenses')],className='actions')],className='stack')
    opportunities=sorted(summary.inactive,key=lambda row:row.recovery_potential,reverse=True)
    distributions=[]
    filters={key:query[key] for key in ('subsidiary','os') if query.get(key)}
    comparison=None
    try:
        grouped=ctx.call(exploration.aggregate,ctx.wid,entity='machines',dimension='subsidiary',split='os',measure='count',filters=filters,limit=100,lake=True)
    except BusinessError as exc:
        if exc.status_code!=409: raise
    else:
        rows=grouped['rows']
        subsidiaries=list(dict.fromkeys(r['label0'] or 'Non renseignée' for r in rows))
        systems=list(dict.fromkeys(r['label1'] or 'Non renseigné' for r in rows))
        figure=go.Figure()
        relative=query.get('comparison')=='share'
        for system in systems:
            values=[sum(r['value'] for r in rows if (r['label0'] or 'Non renseignée')==name and (r['label1'] or 'Non renseigné')==system) for name in subsidiaries]
            figure.add_bar(y=subsidiaries,x=values,name=system,orientation='h',customdata=values,hovertemplate=('%{y}<br>%{customdata:,.0f} machines<br>%{x:.1f} %<extra>%{fullData.name}</extra>' if relative else '%{y}<br>%{x:,.0f} machines<extra>%{fullData.name}</extra>'))
        figure.update_layout(barmode='stack',barnorm='percent' if relative else '',height=max(380,len(subsidiaries)*36))
        figure.update_xaxes(title='Part du parc de la filiale (%)' if relative else 'Machines',ticksuffix=' %' if relative else '')
        figure.update_yaxes(autorange='reversed',automargin=True)
        comparison=card(html.Div([html.H2('Comparer les systèmes par filiale'),filter_control('comparison','Mesure',query.get('comparison','count'),[{'label':'Nombre de machines','value':'count'},{'label':'Part du parc (%)','value':'share'}])],className='section-heading'),
            html.Small('La légende permet d’isoler un système. '+('100 combinaisons affichées sur '+str(grouped['groups'])+'.' if grouped['groups']>100 else '')),
            plot(figure))
    for dimension,title in [('subsidiary','Le parc par filiale'),('os','Systèmes du parc')]:
        try:data=ctx.call(exploration.aggregate,ctx.wid,entity='machines',dimension=dimension,measure='count',filters=filters,limit=12,lake=True)
        except BusinessError as exc:
            if exc.status_code!=409:raise
            continue
        rows=data['rows']
        fig=go.Figure(go.Bar(x=[r['value'] for r in rows],y=[r['label0'] or 'Non remonté' for r in rows],orientation='h',
            customdata=[route('overview',**{**filters,dimension:r['key0']},comparison=query.get('comparison')) for r in rows],hovertemplate='%{y}<br>%{x:,.0f} machines<extra></extra>'))
        fig.update_yaxes(autorange='reversed',automargin=True)
        distributions.append(card(html.H2(title),html.Small('Cliquez sur une barre pour filtrer cette comparaison sur place. 12 groupes au maximum.'),plot(fig,{'type':'insight-chart','key':dimension})))
    return html.Div([
        header('Votre parc, dans la durée.', 'Explorez les usages et identifiez les sujets à examiner.', [link('Explorer les données →','explore')]),
        stats([('Machines et VM',number(counts.get('machines')),'Dans votre périmètre'),
               ('Utilisateurs',number(counts.get('users')),'Salariés et prestataires'),
               ('Sites',number(counts.get('sites')),'Implantations observées'),
               ('Pools analysés',number(summary.pools_total),'Avec historique de capacité')]),
        html.Div([html.H2('Comparer le parc'),html.Span('Sélection : '+' · '.join(filters.values()) if filters else 'Tout le parc de cet espace'),link('Effacer la sélection','overview') if filters else None],className='section-heading'),
        html.Div(distributions,className='settings-profile'),
        comparison,
        html.H2('Capacités des pools de l’espace'),
        html.Small('Les filtres du parc ci-dessus ne répartissent pas les capacités de licence entre filiales.'),
        html.Div([
            card(html.Div([html.H2('Usage des capacités'),link('Comparer les périodes →','annual')],className='section-heading'),
                 plot(daily_figure(summary.trends))),
            card(html.H2('À examiner'),html.Strong(number(summary.recovery_potential),className='metric'),
                 html.P('Unités de capacité potentiellement récupérables'),
                 html.P(f'{len(opportunities)} pools sous-utilisés · {summary.pools_at_risk} pools en tension'),
                 link('Ouvrir les analyses →','savings'), className='insight')
        ],className='split'),
        card(html.Div([html.H2('Opportunités sur les pools'),link('Toutes les analyses →','savings')],className='section-heading'),
             table([('name','Logiciel'),('usage','Utilisation moyenne'),('quantity','Capacité à examiner'),('action','')],
             [{'name':x.software_name,'usage':f'{x.utilization_rate:.1%}', 'quantity':number(x.recovery_potential),
               'action':link('Examiner →','software',pool=x.license_pool_id)} for x in opportunities])),
        html.Small('Analyses des pools avec historique. Les installations et les unités de licence restent distinctes.',className='muted')
    ],className='stack')
