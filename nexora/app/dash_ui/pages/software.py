from collections import defaultdict
from dash import html
import plotly.graph_objects as go
from app.business import inventory_service as inventory
from app.business import asset_analysis
from app.business.errors import BusinessError
from app.dash_ui.components import header, stats, card, link, table, number, empty, filter_control, pager, plot, daily_figure, route

UNITS={'device':'appareils','named_user':'utilisateurs nommés','concurrent':'usages simultanés','core':'cœurs','host':'hôtes','unmetered':'Sans décompte'}


def export_button():
    return html.Button('Exporter CSV',id='export-table',n_clicks=0,className='button',title='Tous les résultats de la recherche dans cet espace, au-delà de la page affichée. Les licences sont détaillées par filiale et unité.')


def products(ctx, include_installations=True):
    return ctx.call(inventory.inventory_software,ctx.wid,include_installations=include_installations,lake=True)


def layout(ctx, query):
    items=products(ctx)
    try:
        summary=ctx.summary()
    except BusinessError as exc:
        if exc.status_code != 409:
            raise
        summary=None
    selected=query.get('product')
    pool=query.get('pool')
    product=next((p for p in items if p.get('software_id')==selected or pool and p.get('license_pool_id')==pool),None)
    if product:
        return detail(ctx,product,summary)
    trends={t.license_pool_id:t for t in (summary.trends if summary else [])}
    filtered=[p for p in items if query.get('q','').casefold() in (p['name']+' '+p['software_id']+' '+str(p.get('license_pool_id') or '')).casefold()]
    filtered.sort(key=lambda p:p['name'].casefold())
    offset=max(0,int(query.get('offset',0)))
    cards=[]
    for p in filtered[offset:offset+12]:
        trend=trends.get(p.get('license_pool_id'))
        cards.append(card(html.Div(p['name'][:1],className='product-icon'),html.H3(p['name']),
            html.Strong(number(p.get('machines')),className='metric small'),html.Small('machines inventoriées'),
            html.P(f'{100*trend.utilization_rate:.1f} % d’utilisation de la capacité'.replace('.', ',') if trend else 'Inventaire des installations'),
            link('Ouvrir le produit →','software',product=p['software_id'])))
    ranking=sorted((p for p in filtered if p.get('machines') is not None),key=lambda p:p['machines'],reverse=True)[:15]
    footprint=go.Figure(go.Bar(x=[p['machines'] for p in ranking],y=[p['name'] for p in ranking],orientation='h',
        customdata=[route('software',product=p['software_id']) for p in ranking],hovertemplate='%{y}<br>%{x:,.0f} machines<extra></extra>'))
    footprint.update_yaxes(autorange='reversed',automargin=True)
    footprint.update_xaxes(title='Machines avec le produit installé')
    footprint.update_layout(height=max(360,32*len(ranking)))
    return html.Div([header('Parc logiciel','Applications, systèmes et services remontés par DIGIMON.',[link('Gérer mon périmètre →','portfolio'),export_button()]),
        html.Div([filter_control('q','Rechercher un logiciel',query.get('q')),html.Span(f'{number(len(filtered))} produits')],className='toolbar'),
        card(html.H2('Empreinte des logiciels'),html.Small('Les 15 produits les plus déployés dans la recherche courante. Une machine peut héberger plusieurs produits.'),plot(footprint,{'type':'insight-chart','key':'software-footprint'})) if ranking else None,
        html.Div(cards,className='product-grid'),pager('software',offset,len(filtered),size=12,q=query.get('q',''))],className='stack')


def product_charts(analysis):
    if not analysis.get('available'):
        return empty('Les analyses des installations ne sont pas encore publiées pour ce produit.')
    panels=[]
    if analysis.get('footprint'):
        rows=analysis['footprint']
        fig=go.Figure(go.Bar(y=[r[0] for r in rows],x=[r[1] for r in rows],orientation='h',marker_color='#68b4ec',hovertemplate='%{y}<br>%{x:,.0f} machines<extra></extra>'))
        fig.update_yaxes(autorange='reversed',automargin=True)
        fig.update_xaxes(title='Machines avec le produit installé')
        panels.append(card(html.H2('Déploiement par filiale'),plot(fig)))
    if analysis.get('analyzed'):
        groups=analysis['activity']
        labels=['Avec activité','Sans activité · période complète','Activité indéterminée','Sans historique']
        values=[groups.get('active',0),groups.get('inactive',0),groups.get('unknown',0),analysis.get('unobserved',0)]
        slices=[(label,value,color) for label,value,color in zip(labels,values,['#64d5b2','#f1c777','#8194a5','#576572']) if value]
        fig=go.Figure(go.Pie(labels=[r[0] for r in slices],values=[r[1] for r in slices],hole=.6,marker_colors=[r[2] for r in slices],textinfo='percent',hovertemplate='%{label}<br>%{value:,.0f} installations · %{percent}<extra></extra>'))
        panels.append(card(html.H2('Activité des installations'),html.Small('Les relevés incomplets sans activité restent indéterminés.'),plot(fig)))
    if analysis.get('frequency'):
        bins=[(0,0,'0'),(1,30,'1–30'),(31,90,'31–90'),(91,180,'91–180'),(181,270,'181–270'),(271,365,'271–365'),(366,float('inf'),'366 et plus')]
        rows=[(label,sum(count for days,count in analysis['frequency'] if low<=days<=high)) for low,high,label in bins if low<=max(r[0] for r in analysis['frequency'])]
        fig=go.Figure(go.Bar(x=[r[0] for r in rows],y=[r[1] for r in rows],text=[number(r[1]) for r in rows],textposition='outside',cliponaxis=False,hovertemplate='%{x} jours actifs<br>%{y:,.0f} installations<extra></extra>'))
        fig.update_xaxes(type='category')
        fig.update_layout(bargap=.25)
        fig.update_yaxes(range=[0,max(r[1] for r in rows)*1.18])
        fig.update_xaxes(title='Nombre de jours avec activité sur la période')
        fig.update_yaxes(title='Installations')
        panels.append(card(html.H2('Fréquence d’activité'),html.Small('Installations dont la période est entièrement observée.'),plot(fig)))
    if analysis.get('coverage'):
        rows=analysis['coverage']
        fig=go.Figure(go.Bar(x=[f"{r['observed']} / {r['expected']} jours" for r in rows],y=[r['count'] for r in rows],marker_color='#8194a5',hovertemplate='%{x}<br>%{y:,.0f} installations<extra></extra>'))
        fig.update_yaxes(title='Installations')
        panels.append(card(html.H2('Couverture des observations'),html.Small('Jours effectivement reçus sur les jours attendus.'),plot(fig)))
    return html.Div(panels,className='settings-profile') if panels else empty('Aucune observation exploitable publiée pour ce produit.')


def detail(ctx,p,summary):
    trend=next((t for t in (summary.trends if summary else []) if t.license_pool_id==p.get('license_pool_id')),None)
    analysis=ctx.call(asset_analysis.product_analysis,ctx.wid,p['software_id'],lake=True)
    activity=analysis.get('activity',{})
    period='Du '+str(analysis['period_start'])+' au '+str(analysis['period_end']) if analysis.get('period_start') else 'Historique non publié'
    rights=p.get('entitlements',[])
    unmetered=bool(rights) and all(r['metric']=='unmetered' for r in rights)
    return html.Div([link('← Parc logiciel','software'),header(p['name'],'Déploiement et activité dans votre périmètre.'),
        stats([('Installations',number(p.get('machines')),'Machines du périmètre'),
               ('Avec activité',number(activity.get('active',0)) if analysis.get('analyzed') else '—',period),
               ('Sans activité observée',number(activity.get('inactive',0)) if analysis.get('analyzed') else '—','Relevés complets uniquement')]),
        product_charts(analysis),
        card(html.H2('Historique de capacité'),plot(daily_figure([trend]))) if trend else None,
        card(html.H2('Licences et abonnements'),html.P('Ce produit est remonté sans quantité de licence à décompter.') if unmetered else right_details(p)),
        html.Details([html.Summary('Approfondir les données et le suivi'),html.Div([
            link('Voir les machines concernées →','inventory',q=p['name'],entity='machines'),
            link('Ouvrir les dossiers →','cases',pool=p.get('license_pool_id') or p['software_id'])],className='toolbar')])],className='stack')


def grouped_rights(p):
    groups=defaultdict(list)
    for r in p.get('entitlements',[]): groups[r['metric']].append(r)
    rows=[]
    for metric,rights in groups.items():
        received=[r['quantity'] for r in rights if r.get('quantity') is not None]
        missing=sum(r.get('quantity') is None for r in rights) if metric!='unmetered' else 0
        rows.append(dict(metric=metric,quantity=sum(received) if received else None,missing=missing))
    return rows


def right_details(p):
    return table([('site','Filiale'),('quantity','Quantité reçue'),('unit','Unité')],[{
        'site':r.get('subsidiary_name') or r.get('subsidiary_id') or 'Groupe',
        'quantity':'Sans décompte' if r['metric']=='unmetered' else number(r.get('quantity')) if r.get('quantity') is not None else 'Remontée manquante',
        'unit':UNITS.get(r['metric'],r['metric'])} for r in p.get('entitlements',[])])


def licenses(ctx,query):
    items=products(ctx,False)
    selected=next((p for p in items if p['software_id']==query.get('product')),None)
    if query.get('product'):
        if selected is None:
            return html.Div([link('← Licences & abonnements','licenses'),empty('Produit indisponible dans ce périmètre.')],className='stack')
        return html.Div([link('← Licences & abonnements','licenses',q=query.get('q')),
            header(selected['name'],'Licences et abonnements par filiale.',[export_button()]),
            card(right_details(selected))],className='stack')
    filtered=[p for p in items if query.get('q','').casefold() in p['name'].casefold()]
    offset=max(0,int(query.get('offset',0)))
    units=sorted({g['metric'] for p in filtered for g in grouped_rights(p) if g['metric']!='unmetered'})
    unit=query.get('unit') if query.get('unit') in units else (units[0] if units else None)
    comparable=[(p,g) for p in filtered for g in grouped_rights(p) if g['metric']==unit and g['quantity'] is not None]
    comparable=sorted(comparable,key=lambda pair:pair[1]['quantity'],reverse=True)[:15]
    figure=go.Figure(go.Bar(x=[g['quantity'] for p,g in comparable],y=[p['name'] for p,g in comparable],orientation='h',
        customdata=[route('licenses',product=p['software_id']) for p,g in comparable],
        text=['Partiel' if g['missing'] else '' for p,g in comparable],
        hovertemplate='%{y}<br>%{x:,.0f}<extra></extra>'))
    figure.update_yaxes(autorange='reversed',automargin=True)
    figure.update_xaxes(title=UNITS.get(unit,unit))
    rows=[]
    for p in sorted(filtered,key=lambda p:p['name'])[offset:offset+25]:
        groups=grouped_rights(p)
        quantities=[]
        for g in groups:
            quantities.append(html.Div(['Sans décompte' if g['metric']=='unmetered' else number(g['quantity']),
                html.Small(f'{g["missing"]} remontée(s) manquante(s)') if g['missing'] else None]))
        rows.append({'name':html.Strong(p['name']), 'quantity':quantities or 'Non reçue dans ce périmètre',
            'unit':[html.Div(UNITS.get(g['metric'],g['metric'])) for g in groups],
            'detail':link('Détails →','licenses',product=p['software_id'],q=query.get('q'))})
    return html.Div([header('Licences & abonnements','Quantités remontées par DIGIMON, dans leur unité de licence.',[export_button()]),
        html.Div([filter_control('q','Rechercher un produit',query.get('q')),html.Span(f'{number(len(filtered))} produits')],className='toolbar'),
        card(html.H2('Comparer les quantités reçues'),filter_control('unit','Unité de comparaison',unit,[{'label':UNITS.get(u,u),'value':u} for u in units]),html.Small('15 produits au maximum, dans une même unité. Les totaux partiels sont signalés.'),plot(figure,{'type':'insight-chart','key':'licenses'})) if units else empty('Aucune quantité comparable disponible.'),
        card(table([('name','Produit'),('quantity','Quantité reçue'),('unit','Unité'),('detail','')],rows)),
        pager('licenses',offset,len(filtered),q=query.get('q')),
        html.Small('Les contrats et quantités du jeu de démonstration sont fictifs.',className='muted')],className='stack')
