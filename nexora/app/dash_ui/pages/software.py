from collections import defaultdict
from dash import html
import plotly.graph_objects as go
from app.business import inventory_service as inventory
from app.dash_ui.components import header, stats, card, link, table, number, empty, filter_control, pager, plot, daily_figure

UNITS={'device':'appareils','named_user':'utilisateurs nommés','concurrent':'usages simultanés','core':'cœurs','host':'hôtes','unmetered':'Sans décompte'}


def products(ctx, include_installations=True):
    return ctx.call(inventory.inventory_software,ctx.wid,include_installations=include_installations,lake=True)


def layout(ctx, query):
    items=products(ctx)
    summary=ctx.summary()
    selected=query.get('product')
    pool=query.get('pool')
    product=next((p for p in items if p.get('software_id')==selected or pool and p.get('license_pool_id')==pool),None)
    if product:
        return detail(ctx,product,summary)
    trends={t.license_pool_id:t for t in summary.trends}
    filtered=[p for p in items if query.get('q','').casefold() in (p['name']+' '+p['software_id']+' '+str(p.get('license_pool_id') or '')).casefold()]
    filtered.sort(key=lambda p:p['name'].casefold())
    offset=max(0,int(query.get('offset',0)))
    cards=[]
    for p in filtered[offset:offset+12]:
        trend=trends.get(p.get('license_pool_id'))
        cards.append(card(html.Div(p['name'][:1],className='product-icon'),html.H3(p['name']),
            html.Strong(number(p.get('machines')),className='metric small'),html.Small('machines inventoriées'),
            html.P(f'{trend.utilization_rate:.1%} d’utilisation de la capacité' if trend else 'Inventaire des installations'),
            link('Ouvrir le produit →','software',product=p['software_id'])))
    return html.Div([header('Parc logiciel','Applications, systèmes et services remontés par DIGIMON.',[link('Gérer mon périmètre →','portfolio')]),
        html.Div([filter_control('q','Rechercher un logiciel',query.get('q')),html.Span(f'{number(len(filtered))} produits')],className='toolbar'),
        html.Div(cards,className='product-grid'),pager('software',offset,len(filtered),size=12,q=query.get('q',''))],className='stack')


def detail(ctx,p,summary):
    trend=next((t for t in summary.trends if t.license_pool_id==p.get('license_pool_id')),None)
    data=ctx.call(inventory.installation_usage,ctx.wid,lake=True)
    usage=next((r for r in data.get('products',[]) if r.get('software_id')==p['software_id']),None)
    return html.Div([link('← Parc logiciel','software'),header(p['name'],'Usages, installations et licences du produit.'),
        stats([('Installations',number(p.get('machines')),'Machines du périmètre'),
               ('Avec activité',number(usage.get('installations_active')) if usage else '—','Sur la période analysée'),
               ('Sans activité observée',number(usage.get('installations_without_usage')) if usage else '—','Relevés complets uniquement')]),
        card(html.H2('Historique de capacité'),plot(daily_figure([trend]))) if trend else card(html.H2('Analyse des installations'),
            html.P('Ce produit est suivi à partir de ses installations et observations.'),link('Examiner les usages →','savings',product=p['software_id'])),
        card(html.H2('Licences et abonnements'),right_details(p)),
        link('Explorer les machines →','inventory',q=p['name'],entity='machines'),
        link('Ouvrir les dossiers →','cases',pool=p.get('license_pool_id') or p['software_id'])],className='stack')


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
    filtered=[p for p in items if query.get('q','').casefold() in p['name'].casefold()]
    rows=[]
    for p in sorted(filtered,key=lambda p:p['name']):
        groups=grouped_rights(p)
        quantities=[]
        for g in groups:
            quantities.append(html.Div(['Sans décompte' if g['metric']=='unmetered' else number(g['quantity']),
                html.Small(f'{g["missing"]} remontée(s) manquante(s)') if g['missing'] else None]))
        rows.append({'name':html.Strong(p['name']), 'quantity':quantities or 'Non reçue dans ce périmètre',
            'unit':[html.Div(UNITS.get(g['metric'],g['metric'])) for g in groups],
            'detail':html.Details([html.Summary('Détails'),right_details(p)])})
    return html.Div([header('Licences & abonnements','Quantités remontées par DIGIMON, dans leur unité de licence.'),
        html.Div([filter_control('q','Rechercher un produit',query.get('q')),html.Span(f'{number(len(items))} produits')],className='toolbar'),
        card(table([('name','Produit'),('quantity','Quantité reçue'),('unit','Unité'),('detail','')],rows)),
        html.Small('Les contrats et quantités du jeu de démonstration sont fictifs.',className='muted')],className='stack')
