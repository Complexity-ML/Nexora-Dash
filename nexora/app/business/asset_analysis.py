"""Scoped analytical projections from one published inventory manifest.

Dash consumes these Python services; navigation does not perform data joins.
Delta reads keep the manifest's version and push product/machine predicates down.
"""
from collections import Counter, defaultdict
import json
from app.business import inventory_service as inventory
from app.business.portfolio_service import read_portfolio
from app.business.workspace_service import member
from app.storage.table_reader import read_table


def _publication(wid, user, store, pipeline):
    with store.connect() as db:
        member(db, wid, user)
        selection = read_portfolio(db, wid)
        head = inventory.inventory_head(db, pipeline.store)
    if not head or not head['manifest_key'].startswith('gold/enterprise/'):
        return None
    manifest = json.loads(pipeline.store.get_bytes(head['manifest_key']))
    products = read_table(pipeline.store, manifest['dimensions']['products']).to_pylist()
    products = {p['software_id']: p for p in products if selection['all_catalog'] or
                (p.get('license_pool_id') or p['software_id']) in selection['pool_ids']}
    return manifest, products


def _evidence(lake, manifest, filters):
    meta = manifest.get('installation_usage')
    if not meta:
        return {}, []
    report = json.loads(lake.get_bytes(meta['key']))
    ref = meta.get('detail_key') or report.get('detail_key')
    return report, read_table(lake, ref, filters=filters).to_pylist() if ref else []


def activity_groups(rows):
    """Disjoint activity groups, keeping incomplete zero-usage evidence unknown."""
    counts = Counter()
    for r in rows:
        if r['active_days'] > 0:
            counts['active'] += 1
        elif r['complete_coverage'] and r['observed_days'] == r['period_days'] and r['period_days'] > 0:
            counts['inactive'] += 1
        else:
            counts['unknown'] += 1
    return dict(counts)


def product_analysis(wid, software_id, user=None, store=None, pipeline=None):
    publication = _publication(wid, user, store, pipeline)
    if not publication:
        return {'available': False}
    manifest, products = publication
    if software_id not in products:
        return {'available': False}
    lake = pipeline.store
    product = products[software_id]
    # Older reports are keyed by pool; newer ones carry the explicit product ID.
    meta = manifest.get('installation_usage')
    report = json.loads(lake.get_bytes(meta['key'])) if meta else {}
    id_key = 'software_id' if any(r.get('software_id') == software_id for r in report.get('products', [])) else 'license_pool_id'
    identity = software_id if id_key == 'software_id' else product.get('license_pool_id')
    report, evidence = _evidence(lake, manifest, [(id_key, '=', identity)]) if identity else ({}, [])
    dims = manifest['dimensions']
    installations = read_table(lake, dims['installations'], filters=[('software_id', '=', software_id)]).to_pylist() if dims.get('installations') else []
    machine_ids = sorted({i['machine_id'] for i in installations} | {r['machine_id'] for r in evidence})
    machines = read_table(lake, dims['machines'], columns=['machine_id', 'site_id'], filters=[('machine_id', 'in', machine_ids)]).to_pylist() if machine_ids else []
    sites = {s['site_id']: s for s in read_table(lake, dims['sites']).to_pylist()}
    subsidiaries = {s['subsidiary_id']: s['name'] for s in read_table(lake, dims['subsidiaries']).to_pylist()}
    footprint = Counter(subsidiaries.get(sites.get(m.get('site_id'), {}).get('subsidiary_id'), 'Implantation non renseignée') for m in machines)
    # Return compact distributions rather than all installation records to Dash.
    frequency = Counter(r['active_days'] for r in evidence if r['complete_coverage'])
    coverage = Counter((r['observed_days'], r['period_days']) for r in evidence)
    return {'available': True, 'period_start': report.get('period_start'), 'period_end': report.get('period_end'),
            'days': report.get('days'), 'activity': activity_groups(evidence), 'analyzed': len(evidence),
            'unobserved': len(set(machine_ids) - {r['machine_id'] for r in evidence}),
            'footprint': sorted(footprint.items(), key=lambda r: -r[1]),
            'frequency': sorted(frequency.items()),
            'coverage': [{'observed': o, 'expected': e, 'count': n} for (o, e), n in sorted(coverage.items())]}


def machine_analysis(wid, machine_id, user=None, store=None, pipeline=None):
    publication = _publication(wid, user, store, pipeline)
    if not publication:
        return inventory.inventory(wid, entity='machines', detail=machine_id, user=user, store=store, pipeline=pipeline)
    manifest, products = publication
    lake = pipeline.store
    dims = manifest['dimensions']
    machines = read_table(lake, dims['machines'], filters=[('machine_id', '=', machine_id)]).to_pylist()
    empty = {'available': True, 'rows': [], 'total': 0}
    if not machines:
        return empty
    row = machines[0]
    base = {'available': True, 'rows': [row], 'total': 1}
    report, evidence = _evidence(lake, manifest, [('machine_id', '=', machine_id)])
    by_pool = {p.get('license_pool_id'): sid for sid, p in products.items() if p.get('license_pool_id')}
    evidence = [{**r, 'software_id': r.get('software_id') or by_pool.get(r.get('license_pool_id'))} for r in evidence]
    evidence = [r for r in evidence if r['software_id'] in products]
    dims = manifest['dimensions']
    installed = read_table(lake, dims['installations'], filters=[('machine_id', '=', machine_id)]).to_pylist() if dims.get('installations') else []
    versions = defaultdict(set)
    for i in installed:
        if i.get('version'): versions[i['software_id']].add(i['version'])
    latest = max(manifest.get('daily', []), key=lambda r: r['date'], default=None)
    observations = read_table(lake, latest, filters=[('machine_id', '=', machine_id)]).to_pylist() if latest else []
    relationships = [r for r in observations if r.get('license_pool_id') in by_pool]
    for r in relationships:
        if r.get('software_version'): versions[by_pool[r['license_pool_id']]].add(r['software_version'])
    user_ids = sorted({r['user_id'] for r in relationships if r.get('user_id')})
    users = read_table(lake, dims['users'], filters=[('user_id', 'in', user_ids)]).to_pylist() if user_ids else []
    ids = {i['software_id'] for i in installed} | {r['software_id'] for r in evidence} | {by_pool[r['license_pool_id']] for r in relationships}
    ids &= products.keys()
    if not ids:
        return empty
    sites = read_table(lake, dims['sites'], filters=[('site_id', '=', row['site_id'])]).to_pylist() if row.get('site_id') else []
    if sites:
        site = sites[0]
        row.update(site=site['name'], country=site.get('country'))
        subsidiaries = read_table(lake, dims['subsidiaries']).to_pylist()
        row['subsidiary'] = next((r['name'] for r in subsidiaries if r['subsidiary_id'] == site.get('subsidiary_id')), None)
    row['relationships'] = relationships
    row['analysis'] = {'period_start': report.get('period_start'), 'period_end': report.get('period_end'),
                       'evidence': [{**r, 'name': products[r['software_id']]['name']} for r in evidence],
                       'users': users, 'products': [{**products[sid], 'versions': sorted(versions[sid])} for sid in sorted(ids) if sid in products]}
    return base
