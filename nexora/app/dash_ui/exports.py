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


def export_table(context, page, query):
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
