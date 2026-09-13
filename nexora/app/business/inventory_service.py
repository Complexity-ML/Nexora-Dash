from app.business.errors import BusinessError
"""Read the latest persisted inventory, scoped to the workspace software portfolio."""
from app.storage.table_reader import read_table
from io import BytesIO
import json
from typing import Literal
import pyarrow.parquet as pq
from app.business.workspace_service import current_user, get_business_store, member
from app.business.portfolio_service import read_portfolio
from app.dependencies import get_pipeline
from app.models.inventory import InventorySnapshot



def inventory_namespace(store):
    if hasattr(store,'collection'):
        manifest = store.collection.manifest
        return manifest.get('index_namespace') if manifest else None
    return store.prefix


def inventory_head(db, store):
    if hasattr(store,'collection'):
        manifest = store.collection.manifest
        if not manifest or not manifest.get('index_run'):
            return None
        row = db.execute('SELECT r.*,r.id AS run_id FROM inventory_runs r WHERE r.id=%s AND r.namespace=%s',
                          (manifest['index_run'],manifest['index_namespace'])).fetchone()
        if row and manifest.get('index_manifest_key'):
            row['manifest_key'] = manifest['index_manifest_key']
        return row
    return db.execute('SELECT r.*,r.id AS run_id FROM inventory_heads h JOIN inventory_runs r ON r.id=h.run_id WHERE h.namespace=%s',
                      (store.prefix,)).fetchone()


def latest_inventory(store):
    if hasattr(store,'collection'):
        return store.collection.inventory()
    if hasattr(store, 'delta'):
        from deltalake.exceptions import TableNotFoundError
        try:
            ref = store.delta.latest('silver/inventory_snapshots')
        except TableNotFoundError:
            pass
        else:
            values = store.delta.read(ref, columns=['observation_date'])['observation_date'].to_pylist()
            if not values:
                return None
            rows = store.delta.read(ref, filters=[('observation_date', '=', max(values))])
            return max((InventorySnapshot.model_validate_json(row['snapshot_json']) for row in rows.to_pylist()),
                       key=lambda value: value.captured_at)
    keys = store.list_keys('silver/inventory/')
    if not keys:
        return None
    day = max(key.split('/date=')[1].split('/')[0] for key in keys)
    candidates = []
    for key in keys:
        if f'/date={day}/' in key:
            for row in pq.read_table(BytesIO(store.get_bytes(key))).to_pylist():
                candidates.append(InventorySnapshot.model_validate(row))
    return max(candidates, key=lambda x: x.captured_at) if candidates else None


def inventory_view(snapshot, pools, entity, query, offset, limit, subsidiary="", country="", region="", site="", kind="", environment="", detail_id=""):
    if snapshot is None:
        return {'available':False,'captured_at':None,'rows':[],'total':0,'counts':{'machines':0,'users':0,'sites':0}}
    observations = [o for o in snapshot.observations if pools is None or o.license_pool_id in pools]
    machine_ids = {o.machine_id for o in observations}
    product_ids = {p.software_id for p in snapshot.products if pools is None or (p.license_pool_id or p.software_id) in pools}
    machine_ids.update(i.machine_id for i in snapshot.installations if i.software_id in product_ids)
    from app.business.software_estate import snapshot_installations
    catalog, installations = snapshot_installations(snapshot)
    machine_ids.update(mid for mid,names in installations.items()
                       if pools is None or any((catalog[name].get('license_pool_id') or catalog[name]['software_id']) in pools for name in names))
    user_ids = {o.user_id for o in snapshot.observations if o.user_id and o.machine_id in machine_ids}
    machines = [m for m in snapshot.machines if pools is None or m.machine_id in machine_ids]
    users = [u for u in snapshot.users if pools is None or u.user_id in user_ids]
    site_ids = {x.site_id for x in [*machines,*users] if x.site_id}
    sites = [s for s in snapshot.sites if pools is None or s.site_id in site_ids]
    options = {
        'subsidiaries': [{'value': s.subsidiary_id, 'label': s.name} for s in snapshot.subsidiaries if any(x.subsidiary_id == s.subsidiary_id for x in sites)],
        'countries': sorted({s.country for s in sites if s.country}),
        'regions': sorted({s.region for s in sites if s.region}),
        'sites': [{'value': s.site_id, 'label': s.name} for s in sites],
    }
    sites = [s for s in sites if (not subsidiary or s.subsidiary_id == subsidiary)
             and (not country or s.country == country) and (not region or s.region == region)
             and (not site or s.site_id == site)]
    if subsidiary or country or region or site:
        selected_sites = {s.site_id for s in sites}
        machines = [m for m in machines if m.site_id in selected_sites]
        users = [u for u in users if u.site_id in selected_sites]
    subsidiaries = {s.subsidiary_id:s.name for s in snapshot.subsidiaries}
    locations = {s.site_id: {'site':s.name, 'country':s.country, 'region':s.region,
                  'subsidiary':subsidiaries.get(s.subsidiary_id)} for s in sites}
    machine_obs = {}
    user_obs = {}
    for observation in observations:
        machine_obs.setdefault(observation.machine_id, []).append(observation)
        user_obs.setdefault(observation.user_id, []).append(observation)
    if kind or environment:
        machines = [m for m in machines if (not kind or m.kind == kind) and (not environment or m.environment == environment)]
    names = {u.user_id:u.display_name for u in users}
    rows = []
    if entity == 'machines':
        for machine in machines:
            obs = machine_obs.get(machine.machine_id, [])
            rows.append({**machine.model_dump(), **locations.get(machine.site_id, {}),
                'installed_products':[catalog[sid] for sid in sorted(installations[machine.machine_id])],
                'software':sorted({o.license_pool_id for o in obs}),
                'used_software':sorted({o.license_pool_id for o in obs if o.used}),
                'users':sorted({names[o.user_id] for o in obs if o.user_id in names})})
    elif entity == 'users':
        for user in users:
            obs = user_obs.get(user.user_id, [])
            rows.append({**user.model_dump(), **locations.get(user.site_id, {}),
                'machines':sorted({o.machine_id for o in obs}),
                'software':sorted({o.license_pool_id for o in obs}),
                'used_software':sorted({o.license_pool_id for o in obs if o.used})})
    else:
        rows = [{**s.model_dump(), 'subsidiary':subsidiaries.get(s.subsidiary_id), 'machines':sum(m.site_id == s.site_id for m in machines),
                 'users':sum(u.site_id == s.site_id for u in users)} for s in sites]
    if detail_id:
        id_key = {'machines':'machine_id','users':'user_id','sites':'site_id'}[entity]
        rows = [row for row in rows if row[id_key] == detail_id]
    filtered = [row for row in rows if query.casefold() in json.dumps(row,ensure_ascii=False).casefold()]
    return {'available':True,'is_demo':snapshot.source == 'digimon-mock','captured_at':snapshot.captured_at,'rows':filtered[offset:offset+limit],
            'filters':options,'total':len(filtered),'counts':{'machines':len(machines),'users':len(users),'sites':len(sites)}}


def inventory(wid: str, entity: Literal['machines','users','sites']='machines',
              subsidiary: str='', country: str='', region: str='', site: str='',
              kind: str='', environment: str='', detail: str='',
              q: str='', offset: int=0,
              limit: int=25, user=None,
              store=None, pipeline=None):
    with store.connect() as db:
        member(db,wid,user)
        selection = read_portfolio(db,wid)
    pools = None if selection['all_catalog'] else selection['pool_ids']
    if hasattr(pipeline.store, 'prefix'):
        from app.business.inventory_index import read_index
        with store.connect() as db:
            indexed = read_index(db,inventory_namespace(pipeline.store),pools,entity,q,offset,limit,
                                 dict(subsidiary=subsidiary,country=country,region=region,site=site,kind=kind,environment=environment),detail or None,
                                 expected_run=(pipeline.store.collection.manifest or {}).get('index_run') if hasattr(pipeline.store,'collection') else None)
        if indexed is not None:
            return indexed
    return inventory_view(latest_inventory(pipeline.store),pools,entity,q,offset,limit,subsidiary,country,region,site,kind,environment,detail)


def inventory_software(wid: str, include_installations: bool=True, user=None, store=None, pipeline=None):
    """Installed systems and components in the authorized inventory projection."""
    with store.connect() as db:
        member(db, wid, user)
        selection = read_portfolio(db, wid)
        head = inventory_head(db,pipeline.store)
        if not head:
            from app.business.software_estate import snapshot_software
            pools = None if selection['all_catalog'] else selection['pool_ids']
            return snapshot_software(latest_inventory(pipeline.store), pools)
        # Licences need only small versioned dimensions, not a scan of all machines.
        if not include_installations and head['manifest_key'].startswith('gold/enterprise/'):
            from app.business.software_estate import enrich_software
            manifest = json.loads(pipeline.store.get_bytes(head['manifest_key']))
            products = enrich_software(None, manifest, pipeline.store, selection['all_catalog'])
            selected = set(selection['pool_ids'])
            return [p for p in products if selection['all_catalog'] or
                    (p.get('license_pool_id') or p.get('software_id')) in selected]
        from app.business.software_counts import read_counts
        rows = read_counts(db, head['run_id'], None if selection['all_catalog'] else selection['pool_ids'])

        # Legacy small demo has no enterprise dimensions manifest.
        if not head['manifest_key'].startswith('gold/enterprise/'):
            return rows
        from app.business.software_estate import enrich_software
        manifest = json.loads(pipeline.store.get_bytes(head['manifest_key']))
        enriched = enrich_software(rows, manifest, pipeline.store, selection['all_catalog'])
        if not selection['all_catalog']:
            selected = set(selection['pool_ids'])
            enriched = [p for p in enriched if (p.get('license_pool_id') or p.get('software_id')) in selected]
        return enriched


def installation_usage(wid: str, user=None, store=None, pipeline=None):
    with store.connect() as db:
        member(db,wid,user)
        selection = read_portfolio(db,wid)
        head = inventory_head(db,pipeline.store)
    if not head or not head['manifest_key'].startswith('gold/enterprise/'):
        return {'available':False,'products':[]}
    manifest = json.loads(pipeline.store.get_bytes(head['manifest_key']))
    report = manifest.get('installation_usage')
    if not report:
        return {'available':False,'products':[]}
    value = json.loads(pipeline.store.get_bytes(report['key']))
    products = read_table(pipeline.store, manifest['dimensions']['products']).to_pylist()
    names = {p['license_pool_id']:p['name'] for p in products if p.get('license_pool_id')}
    names_by_id = {p['software_id']:p['name'] for p in products if p.get('software_id')}
    value['products'] = [{**p,'software_name':names_by_id.get(p.get('software_id')) or names.get(p.get('license_pool_id')) or p.get('software_id') or p.get('license_pool_id')}
                         for p in value['products'] if selection['all_catalog'] or (p.get('license_pool_id') or p.get('software_id')) in selection['pool_ids']]
    value.pop('detail_key',None)
    return {'available':True,**value}


def installation_usage_machines(
    wid: str, pool: str=None,
    offset: int=0, limit: int=25,
    user=None, store=None, pipeline=None,
):
    """Return current, scoped machines with complete evidence of no usage."""
    empty = {'available':False,'rows':[],'total':0}
    with store.connect() as db:
        member(db,wid,user)
        selection = read_portfolio(db,wid)
        if not selection['all_catalog'] and pool not in selection['pool_ids']:
            return empty
        head = inventory_head(db,pipeline.store)
        if not head or not head['manifest_key'].startswith('gold/enterprise/'):
            return empty
        manifest = json.loads(pipeline.store.get_bytes(head['manifest_key']))
        report_meta = manifest.get('installation_usage')
        if not report_meta:
            return empty
        report = json.loads(pipeline.store.get_bytes(report_meta['key']))
        detail_key = report_meta.get('detail_key') or report.get('detail_key')
        if not detail_key:
            return empty
        products = read_table(pipeline.store, manifest['dimensions']['products']).to_pylist() if manifest.get('dimensions', {}).get('products') else []
        identity_column = 'software_id' if any(p['software_id'] == pool for p in products) else 'license_pool_id'
        evidence = read_table(
            pipeline.store, detail_key,
            filters=[(identity_column,'=',pool),('active_days','=',0),('complete_coverage','=',True)],
        ).to_pylist()
        records = {r['machine_id']:r for r in evidence
                   if r['observed_days'] == report['days'] and r['period_days'] == report['days'] and report['days'] > 0}
        params = (head['id'],list(records),[pool])
        where = "run_id=%s AND entity='machines' AND id=ANY(%s::text[]) AND pool_ids && %s::text[]"
        total = db.execute('SELECT count(*) AS n FROM inventory_entities WHERE '+where, params).fetchone()['n']
        machines = db.execute('SELECT id,name,data FROM inventory_entities WHERE '+where+' ORDER BY name,id LIMIT %s OFFSET %s', (*params,limit,offset)).fetchall()
        return {'available':True,'total':total,'days':report['days'],
                'period_start':report.get('period_start'),'period_end':report.get('period_end'),
                'rows':[{'machine_id':m['id'],'name':m['name'],
                         'site':m['data'].get('site'),'subsidiary':m['data'].get('subsidiary'),
                         'observed_days':records[m['id']]['observed_days']} for m in machines]}
