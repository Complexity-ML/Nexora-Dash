"""Rebuildable PostgreSQL projection of a Parquet inventory snapshot."""
from collections import defaultdict
import json
from uuid import uuid4
from psycopg.types.json import Jsonb


def entity_rows(snapshot):
    from app.business.software_estate import snapshot_installations
    products, installed = snapshot_installations(snapshot)
    subsidiaries = {s.subsidiary_id:s.name for s in snapshot.subsidiaries}
    subsidiary_codes = {s.subsidiary_id:s.code for s in snapshot.subsidiaries}
    sites = {s.site_id:s for s in snapshot.sites}
    observations = defaultdict(list)
    user_observations = defaultdict(list)
    site_pools = defaultdict(set)
    machine_sites = {m.machine_id:m.site_id for m in snapshot.machines}
    user_sites = {u.user_id:u.site_id for u in snapshot.users}
    machine_keys = defaultdict(set)
    user_keys = defaultdict(set)
    for machine_id, software_ids in installed.items():
        for software_id in software_ids:
            key = products[software_id].get('license_pool_id') or software_id
            machine_keys[machine_id].add(key)
            site_pools[machine_sites[machine_id]].add(key)
    for o in snapshot.observations:
        observations[o.machine_id].append(o)
        if o.user_id:
            user_observations[o.user_id].append(o)
            user_keys[o.user_id].update(machine_keys[o.machine_id])
            site_pools[user_sites[o.user_id]].update(machine_keys[o.machine_id])
        site_pools[machine_sites[o.machine_id]].add(o.license_pool_id)
        if o.user_id: site_pools[user_sites[o.user_id]].add(o.license_pool_id)
    for entity,items in [('machines',snapshot.machines),('users',snapshot.users),('sites',snapshot.sites)]:
        for item in items:
            value = item.model_dump(mode='json')
            if entity == 'machines':
                value['installed_products'] = [products[sid] for sid in sorted(installed[item.machine_id])]
            identifier = value[{'machines':'machine_id','users':'user_id','sites':'site_id'}[entity]]
            site = sites.get(item.site_id)
            obs = observations[identifier] if entity == 'machines' else user_observations[identifier] if entity == 'users' else []
            pools = sorted(site_pools[item.site_id]) if entity == 'sites' else sorted({o.license_pool_id for o in obs})
            scope_keys = set(pools) | (machine_keys[identifier] if entity == 'machines' else user_keys[identifier] if entity == 'users' else set())
            value.update({'software':pools,'used_software':sorted({o.license_pool_id for o in obs if o.used}),
                          'relationships':[o.model_dump(mode='json') for o in obs],
                          'site':site.name if site else None,
                          'subsidiary':subsidiaries.get(site.subsidiary_id) if site else None,
                          'subsidiary_code':subsidiary_codes.get(site.subsidiary_id) if site else None,
                          'country':site.country if site else None,'region':site.region if site else None})
            name = value.get('name',value.get('display_name',identifier))
            yield (entity,identifier,name,site.subsidiary_id if site else None,
                   value['country'],value['region'],item.site_id,value.get('kind'),
                   value.get('operating_system'),value.get('environment'),sorted(scope_keys),
                   json.dumps({**{k:v for k,v in value.items() if k not in ('software','used_software','relationships')}, 'scope_keys':sorted(scope_keys)},ensure_ascii=False).casefold(),value)


def publish_index(store, namespace, snapshot, manifest_key, expected_run=None, expected_manifest=None):
    run_id = str(uuid4())
    with store.connect() as db:
        if expected_run is not None:
            current = db.execute('SELECT run_id FROM inventory_heads WHERE namespace=%s FOR UPDATE', (namespace,)).fetchone()
            if not current or current['run_id'] != expected_run:
                raise RuntimeError('Active inventory changed while rebuilding the index')
            current_run = db.execute('SELECT manifest_key FROM inventory_runs WHERE id=%s', (expected_run,)).fetchone()
            if expected_manifest is not None and current_run['manifest_key'] != expected_manifest:
                raise RuntimeError('Active usage manifest changed while rebuilding the index')
        db.execute('INSERT INTO inventory_runs VALUES(%s,%s,%s,%s,%s)',
                   (run_id,namespace,snapshot.captured_at,snapshot.source,manifest_key))
        with db.cursor().copy('COPY inventory_entities FROM STDIN') as copy:
            for row in entity_rows(snapshot):
                copy.write_row((run_id,*row[:-1],Jsonb(row[-1])))
        from app.business.software_counts import rebuild_summary
        rebuild_summary(db, run_id)
        db.execute('INSERT INTO inventory_heads VALUES(%s,%s) ON CONFLICT(namespace) DO UPDATE SET run_id=EXCLUDED.run_id',
                   (namespace,run_id))
    return run_id


def read_index(db, namespace, pools, entity, query, offset, limit, filters, detail_id=None, expected_run=None):
    head = (db.execute('SELECT * FROM inventory_runs WHERE id=%s AND namespace=%s',(expected_run,namespace)).fetchone()
            if expected_run else db.execute('SELECT r.* FROM inventory_heads h JOIN inventory_runs r ON r.id=h.run_id WHERE h.namespace=%s',(namespace,)).fetchone())
    if not head: return None
    conditions = ['run_id=%s']
    params = [head['id']]
    if pools is not None:
        conditions.append('pool_ids && %s::text[]'); params.append(pools)
    for key in ('subsidiary','country','region','site','kind','environment'):
        if filters.get(key):
            conditions.append(f'{key}=%s'); params.append(filters[key])
    where = ' AND '.join(conditions)
    counts = {key:0 for key in ('machines','users','sites')}
    for row in db.execute(f'SELECT entity,count(*) AS n FROM inventory_entities WHERE {where} GROUP BY entity',params):
        counts[row['entity']] = row['n']
    option_where = 'run_id=%s' + (' AND pool_ids && %s::text[]' if pools is not None else '')
    option_params = [head['id']] + ([pools] if pools is not None else [])
    locations = db.execute(f"SELECT DISTINCT subsidiary,country,region,site,data->>'subsidiary' AS subsidiary_name,data->>'subsidiary_code' AS subsidiary_code,data->>'site' AS site_name FROM inventory_entities WHERE {option_where} AND entity='sites'",option_params).fetchall()
    options = {
        'subsidiaries':sorted([{'value':k,'label':v[0] or v[1],'description':v[1]} for k,v in {r['subsidiary']:(r['subsidiary_code'],r['subsidiary_name']) for r in locations if r['subsidiary']}.items()],key=lambda x:x['label']),
        'countries':sorted({r['country'] for r in locations if r['country']}),
        'regions':sorted({r['region'] for r in locations if r['region']}),
        'sites':sorted([{'value':r['site'],'label':r['site_name']} for r in locations],key=lambda x:x['label']),
    }
    conditions.append('entity=%s'); params.append(entity)
    if query:
        conditions.append('strpos(search,%s)>0'); params.append(query.casefold())
    if detail_id:
        conditions.append('id=%s');params.append(detail_id)
    where = ' AND '.join(conditions)
    total = db.execute(f'SELECT count(*) AS n FROM inventory_entities WHERE {where}',params).fetchone()['n']
    rows = []
    for record in db.execute(f'SELECT data FROM inventory_entities WHERE {where} ORDER BY name,id LIMIT %s OFFSET %s',[*params,limit,offset]):
        value = record['data']
        allowed = set(value['software']) if pools is None else set(pools)
        value['software'] = [p for p in value['software'] if p in allowed]
        value['used_software'] = [p for p in value['used_software'] if p in allowed]
        relationships = [r for r in value.pop('relationships') if r['license_pool_id'] in allowed]
        if detail_id:
            value['relationships'] = relationships
        if entity == 'sites':
            value['machines'] = db.execute("SELECT count(*) AS n FROM inventory_entities WHERE run_id=%s AND entity='machines' AND site=%s" + (' AND pool_ids && %s::text[]' if pools is not None else ''), [head['id'],value['site_id']] + ([pools] if pools is not None else [])).fetchone()['n']
            value['users'] = db.execute("SELECT count(*) AS n FROM inventory_entities WHERE run_id=%s AND entity='users' AND site=%s" + (' AND pool_ids && %s::text[]' if pools is not None else ''), [head['id'],value['site_id']] + ([pools] if pools is not None else [])).fetchone()['n']
        rows.append(value)
    return {'available':True,'is_demo':head['source']=='digimon-mock','captured_at':head['captured_at'],
            'rows':rows,'total':total,'counts':counts,'filters':options}
