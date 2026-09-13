from datetime import date, timedelta
from app.dash_ui.charts import usage_heatmap, installation_activity, capacity_pressure, opportunity_ranking, usage_distribution, usage_duration, capacity_history
from dash import html, dcc
import plotly.graph_objects as go
from app.dash_ui.components import header, stats, card, link, table, number, money, empty, filter_control, plot, daily_figure, field, action, pager
from app.business import inventory_service as inventory, workspace_service as business


def savings(ctx,query):
    view=query.get('view','installations')
    tabs=html.Nav([link('Usage des installations','savings'),link('Capacités des pools','savings',view='pools')],className='tabs')
    if view!='pools':
        report=ctx.call(inventory.installation_usage,ctx.wid,lake=True)
        rows=report.get('products',[])
        if query.get('product'):
            selected=next((p for p in rows if (p.get('software_id') or p.get('license_pool_id'))==query['product']),None)
            if not selected: return empty('Produit absent de cette analyse.')
            offset=max(0,int(query.get('offset',0)))
            details=ctx.call(inventory.installation_usage_machines,ctx.wid,pool=query['product'],offset=offset,limit=25,lake=True)
            return html.Div([link('← Analyses des installations','savings'),header(selected['software_name'],'Machines sans activité observée sur la période complète.'),
                card(table([('name','Machine'),('site','Site'),('subsidiary','Filiale')],[dict(r,name=link(r['name'],'inventory',detail=r['machine_id'],entity='machines')) for r in details['rows']])),
                pager('savings',offset,details['total'],product=query['product'])],className='stack')
        return html.Div([header('Coûts & économies','Examinez les usages avant de simuler les économies.'),tabs,
            stats([('Installations analysées',number(sum(p['installations_observed'] for p in rows)),f'{report.get("days",0)} jours observés'),
                ('Sans activité',number(sum(p['installations_without_usage'] for p in rows)),'Couverture complète'),
                ('Relevés incomplets',number(sum(p['installations_incomplete'] for p in rows)),'Exclus des conclusions d’inactivité')]),
            card(html.H2('Activité par produit'),html.Small('15 produits avec le plus d’installations sans activité. Cliquez pour examiner les machines.'),plot(installation_activity(rows),{'type':'insight-chart','key':'activity'})),
            card(table([('name','Produit'),('observed','Observées'),('active','Avec activité'),('unused','Sans activité'),('action','')],[{
                'name':p['software_name'],'observed':number(p['installations_observed']),'active':number(p['installations_active']),
                'unused':number(p['installations_without_usage']),'action':link('Examiner →','savings',product=p.get('software_id') or p.get('license_pool_id'))
            } for p in sorted(rows,key=lambda p:p['installations_without_usage'],reverse=True)])),
            html.Small('La valeur financière dépend des droits libérables et de leurs coûts. Une installation inactive n’est pas automatiquement une économie.',className='muted')],className='stack')
    summary=ctx.summary()
    costs={r['pool_id']:r for r in ctx.call(business.costs,ctx.wid)}
    cases=ctx.call(business.cases,ctx.wid)
    panels=[]
    for candidate in summary.inactive:
        key=candidate.license_pool_id
        cost=costs.get(key,{})
        cents=cost.get('annual_unit_cents')
        related=[c for c in cases if c['pool_id']==key]
        panels.append(card(html.Div([html.H2(candidate.software_name),link('Analyser →','software',pool=key)],className='section-heading'),
            stats([('Capacité à examiner',number(candidate.recovery_potential),'Estimation avec réserve'),('Valeur annuelle simulée',money(candidate.recovery_potential*cents if cents is not None else None),'Coût renseigné dans cet espace')]),
            html.Div([field('cost:'+key,'Coût annuel par unité (€)',cents/100 if cents is not None else None,kind='number',min=0,max=10000000),
                      field('cost-version:'+key,'Version',cost.get('version',0),kind='hidden'),
                      action('Enregistrer','cost:'+key,disabled=not ctx.writable)],className='toolbar'),
            html.P(link(f'Voir les {len(related)} dossiers →','cases',pool=key) if related else link('Ouvrir un dossier →','cases',pool=key))))
    return html.Div([header('Coûts & économies','Simulez la valeur des capacités à examiner.'),tabs,
        card(html.H2('Prioriser les examens'),plot(opportunity_ranking(summary.inactive),{'type':'insight-chart','key':'opportunities'})),
        html.Small('Simulation sur les pools analysés. Ces montants ne sont pas des économies réalisées.',className='muted'),*panels],className='stack')


def annual(ctx,query):
    summary=ctx.summary()
    trends=[t for t in summary.trends if not query.get('pool') or t.license_pool_id==query['pool']]
    if not trends: return empty('Aucun historique de capacité dans ce périmètre.')
    first=min(str(p['date']) for t in trends for p in t.daily)
    last=max(str(p['date']) for t in trends for p in t.daily)
    midpoint=date.fromisoformat(first)+(date.fromisoformat(last)-date.fromisoformat(first))//2
    ranges=[(query.get('a_start',first),query.get('a_end',midpoint.isoformat())),
            (query.get('b_start',(midpoint+timedelta(days=1)).isoformat()),query.get('b_end',last))]
    controls=[filter_control('pool','Historique à comparer',query.get('pool'),[{'label':'Tous les pools de cet espace','value':''}]+[{'label':t.software_name,'value':t.license_pool_id} for t in summary.trends])]
    days={}
    for t in trends:
        for p in t.daily:
            entry=days.setdefault(str(p['date']),[0,0,0]); entry[0]+=p['used']; entry[1]+=p['capacity']; entry[2]+=1
    values=[]
    for i,(start,end) in enumerate(ranges):
        key='a' if i==0 else 'b'
        controls.append(html.Div([html.Label('Période '+key.upper()),
            dcc.Input(id={'type':'filter','key':key+'_start'},type='date',value=start,min=first,max=last,debounce=True),
            dcc.Input(id={'type':'filter','key':key+'_end'},type='date',value=end,min=first,max=last,debounce=True)],className='field'))
        samples=[used/cap for d,(used,cap,n) in days.items() if start<=d<=end and cap>0 and n==len(trends)] if first<=start<=end<=last else []
        values.append(sum(samples)/len(samples)*100 if samples else None)
    delta=values[1]-values[0] if all(v is not None for v in values) else None
    monthly={}
    for day,(used,cap,n) in sorted(days.items()):
        if cap>0 and n==len(trends): monthly.setdefault(day[:7],[]).append(used/cap*100)
    fig=go.Figure(go.Bar(x=list(monthly),y=[sum(v)/len(v) for v in monthly.values()],name='Utilisation moyenne'))
    fig.update_yaxes(ticksuffix=' %')
    changes=[]
    for t in trends:
        for before,after in zip(t.daily,t.daily[1:]):
            if before['capacity']!=after['capacity']:
                changes.append({'name':t.software_name,'day':after['date'],'before':number(before['capacity']),'after':number(after['capacity'])})
    return html.Div([header('Analyse annuelle','Comparez les usages et les capacités sur l’historique disponible.'),
        html.Div(controls,className='filters'),
        stats([('Période A',f'{values[0]:.1f} %' if values[0] is not None else 'Non calculable','Journées complètes avec capacité positive'),
               ('Période B',f'{values[1]:.1f} %' if values[1] is not None else 'Non calculable','Journées complètes avec capacité positive'),
               ('Évolution',f'{delta:+.1f} points' if delta is not None else '—','Utilisation inchangée' if delta==0 else 'Écart entre les deux périodes')]),
        card(html.H2('Usage au fil des journées'),html.Small('Une cellule vide signifie une journée absente ou une capacité non calculable. Cliquez pour ouvrir le produit.'),plot(usage_heatmap(trends),{'type':'insight-chart','key':'usage'})),
        card(html.H2('Profil mensuel'),plot(fig)),
        card(html.H2('Variabilité des usages'),html.Small('Médiane, dispersion et extrêmes des journées observées par produit.'),plot(usage_distribution(trends),{'type':'insight-chart','key':'distribution'})),
        card(html.H2('Pics ponctuels ou usage durable ?'),html.Small('Les courbes distinguent les pics rares des niveaux d’usage soutenus. Cliquez sur la légende pour isoler un produit.'),plot(usage_duration(trends),{'type':'insight-chart','key':'duration'})),
        card(html.H2('Évolution relative des capacités'),html.Small('Chaque produit part de sa première capacité positive, ramenée à 100. Les unités ne sont pas additionnées.'),plot(capacity_history(trends),{'type':'insight-chart','key':'capacity-history'})),
        html.Details([html.Summary('Voir les changements de capacité en détail'),table([('name','Produit'),('day','Constat'),('before','Avant'),('after','Après')],changes)],className='card')],className='stack')


def pools(ctx,query):
    summary=ctx.summary()
    eligible=[]
    # Use source product metadata when available rather than inferring licence type from a name.
    from app.dash_ui.pages.software import products
    concurrent={p.get('license_pool_id') for p in products(ctx,False) if any(r['metric']=='concurrent' for r in p.get('entitlements',[]))}
    eligible=[r for r in summary.risks if r.license_pool_id in concurrent]
    levels={'high':'Élevé','medium':'Modéré','low':'Faible'}
    cards=[]
    for r in eligible:
        trend=next(t for t in summary.trends if t.license_pool_id==r.license_pool_id)
        horizon=(r.estimated_saturation_date.date()-trend.period_end.date()).days if r.estimated_saturation_date else None
        estimate=f'Dans {horizon} jours' if horizon is not None and 0<=horizon<=365 else 'Hors horizon de projection' if horizon and horizon>365 else 'Non estimable'
        cards.append(card(html.Span(levels[r.level],className='badge '+r.level),html.H3(r.software_name),
            html.Strong(number(r.remaining_capacity),className='metric small'),html.Small('unités disponibles'),
            html.P(estimate),link('Analyser →','software',pool=r.license_pool_id)))
    return html.Div([header('Pools de licences','Surveillez les capacités concurrentes et leur évolution.'),
        stats([('Pools analysés',number(len(eligible)),'Licences concurrentes'),('Risque élevé',number(sum(r.level=='high' for r in eligible)),'Selon les observations publiées')]),
        card(html.H2('Capacité et pression d’usage'),html.Small('Cliquez sur un point pour ouvrir le pool.'),plot(capacity_pressure([t for t in summary.trends if t.license_pool_id in concurrent]),{'type':'insight-chart','key':'pressure'})),
        html.Div(cards,className='product-grid'),html.Small('Projection linéaire indicative, limitée à un an.',className='muted')],className='stack')
