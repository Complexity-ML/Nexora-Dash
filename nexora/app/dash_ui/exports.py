"""Tabular downloads from authorized services; never trigger lake computation."""
import csv
from io import StringIO
from app.business.errors import BusinessError
from app.dash_ui.pages.software import products, UNITS


def software_matches(product, query):
    text=' '.join(str(product.get(key) or '') for key in ('name','software_id','license_pool_id'))
    return query.get('q','').casefold() in text.casefold()


def csv_document(columns, rows):
    output=StringIO(newline='')
    writer=csv.writer(output,delimiter=';',lineterminator='\r\n')
    writer.writerow(columns)
    for row in rows:
        # Spreadsheet applications must not execute source-controlled cell text.
        writer.writerow(["'"+value if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')) else value for value in row])
    return '\ufeff'+output.getvalue()


def analysis_rows(context, query):
    from app.business import inventory_service, workspace_service
    if query.get('view') == 'pools':
        summary = context.summary()
        costs = {c['pool_id']: c for c in context.call(workspace_service.costs, context.wid)}
        columns = ['Produit', 'Identifiant pool', 'Capacité à examiner', 'Coût annuel par unité (EUR)', 'Valeur annuelle simulée (EUR)', 'Nature']
        rows = []
        for candidate in summary.inactive:
            cents = costs.get(candidate.license_pool_id, {}).get('annual_unit_cents')
            rows.append([candidate.software_name, candidate.license_pool_id, candidate.recovery_potential,
                         cents / 100 if cents is not None else None,
                         candidate.recovery_potential * cents / 100 if cents is not None else None,
                         'Simulation, sans gain réalisé'])
        return columns, rows
    report = context.call(inventory_service.installation_usage, context.wid, lake=True)
    if report.get('available') is False:
        raise BusinessError(409,'Aucune analyse des installations publiée.')
    columns = ['Produit', 'Identifiant logiciel', 'Identifiant pool', 'Installations observées',
               'Avec activité', 'Sans activité avec couverture complète', 'Relevés incomplets',
               'Début de période', 'Fin de période', 'Jours analysés']
    items = report.get('products', [])
    if query.get('product'):
        items = [p for p in items if (p.get('software_id') or p.get('license_pool_id')) == query['product']]
    return columns, [[p['software_name'], p.get('software_id'), p.get('license_pool_id'),
                      p['installations_observed'], p['installations_active'], p['installations_without_usage'],
                      p['installations_incomplete'], report.get('period_start'), report.get('period_end'), report.get('days')]
                     for p in sorted(items, key=lambda p: p['installations_without_usage'], reverse=True)]


def additional_rows(context, page, query):
    from app.business import workspace_service
    from app.dash_ui.pages.analysis import annual_ranges, concurrent_pools
    from app.dash_ui.pages.cases import STATUS
    if page == 'cases':
        items = context.call(workspace_service.cases, context.wid)
        if query.get('pool'):
            items = [r for r in items if r['pool_id'] == query['pool']]
        columns = ['Dossier', 'Identifiant', 'Produit / pool', 'État', 'Responsable (identifiant)', 'Quantité examinée', 'Coût annuel unitaire (EUR)', 'Hypothèse annuelle (EUR)']
        return columns, [[r['title'], r['id'], r['pool_id'], STATUS.get(r['status'], r['status']), r.get('assignee_id'),
                          r['quantity'], r['annual_unit_cents']/100, r['quantity']*r['annual_unit_cents']/100] for r in items]
    summary = context.summary()
    if page == 'flexlm':
        eligible = concurrent_pools(context)
        columns = ['Produit', 'Identifiant pool', 'Risque', 'Capacité disponible', 'Croissance par jour', 'Saturation estimée (indicative)']
        return columns, [[r.software_name, r.license_pool_id, {'high':'Élevé','medium':'Modéré','low':'Faible'}[r.level],
                          r.remaining_capacity, r.growth_per_day, r.estimated_saturation_date.isoformat() if r.estimated_saturation_date else None]
                         for r in summary.risks if r.license_pool_id in eligible]
    trends = [t for t in summary.trends if not query.get('pool') or t.license_pool_id == query['pool']]
    if not trends or not any(t.daily for t in trends):
        raise BusinessError(409,'Aucun historique de capacité dans ce périmètre.')
    first,last,ranges = annual_ranges(trends, query)
    if any(not first <= start <= end <= last for start,end in ranges):
        raise BusinessError(400,'Choisissez deux périodes comprises dans l’historique disponible.')
    columns = ['Produit', 'Identifiant pool', 'Jour observé', 'Usage', 'Capacité', 'Utilisation (%)', 'Période A', 'Période B']
    rows = []
    for t in trends:
        for p in sorted(t.daily,key=lambda p:str(p['date'])):
            day = str(p['date'])
            rows.append([t.software_name,t.license_pool_id,day,p['used'],p['capacity'],
                         100*p['used']/p['capacity'] if p['capacity']>0 else None,
                         *['Oui' if start<=day<=end else 'Non' for start,end in ranges]])
    return columns, rows


def export_table(context, page, query):
    if page in ('annual','flexlm','cases'):
        columns,rows = additional_rows(context,page,query)
        return {'content':csv_document(columns,rows),'filename':f'nexora-{page}.csv','type':'text/csv;charset=utf-8','base64':False}

    if page == 'savings':
        columns, rows = analysis_rows(context, query)
        kind = 'capacites' if query.get('view') == 'pools' else 'installations'
        return {'content':csv_document(columns,rows),'filename':f'nexora-analyses-{kind}.csv','type':'text/csv;charset=utf-8','base64':False}
    if page not in ('software','licenses'):
        raise BusinessError(400,'Cette vue ne propose pas d’export tabulaire.')
    items=products(context,include_installations=page=='software')
    if query.get('product'):
        items=[p for p in items if p['software_id']==query['product']]
    if query.get('pool'):
        items=[p for p in items if p.get('license_pool_id')==query['pool']]
    if page=='software':
        items=[p for p in items if software_matches(p,query)]
        columns=['Produit','Identifiant logiciel','Identifiant pool','Machines inventoriées']
        rows=[[p['name'],p['software_id'],p.get('license_pool_id'),p.get('machines')] for p in sorted(items,key=lambda p:p['name'].casefold())]
    else:
        items=[p for p in items if query.get('q','').casefold() in p['name'].casefold()]
        columns=['Produit','Identifiant logiciel','Filiale','Identifiant filiale','Quantité reçue','Unité','État']
        rows=[]
        for p in sorted(items,key=lambda p:p['name'].casefold()):
            rights=p.get('entitlements') or []
            if not rights: rows.append([p['name'],p['software_id'],'','','','','Non reçue dans ce périmètre'])
            for right in rights:
                metric=right['metric'];quantity=right.get('quantity')
                state='Sans décompte' if metric=='unmetered' else 'Remontée manquante' if quantity is None else 'Reçue'
                rows.append([p['name'],p['software_id'],right.get('subsidiary_name') or right.get('subsidiary_id') or 'Groupe',right.get('subsidiary_id'),
                    None if metric=='unmetered' else quantity,UNITS.get(metric,metric),state])
    return {'content':csv_document(columns,rows),'filename':f'nexora-{page}.csv','type':'text/csv;charset=utf-8','base64':False}
