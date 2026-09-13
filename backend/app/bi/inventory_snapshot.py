"""Aggregate a pinned inventory index without exporting individual identities."""
import json
import re
from uuid import uuid4
import pyarrow as pa
from app.collection.reader import PublishedCollection
from app.collection.maintenance_lock import protect_backup
from app.collection.journal import fingerprint
from app.collection.runner import encoded

SCHEMA = pa.schema([
    ('captured_at', pa.timestamp('us', tz='UTC')),
    ('subsidiary_id', pa.string()), ('subsidiary_name', pa.string()),
    ('site_id', pa.string()), ('site_name', pa.string()), ('country', pa.string()),
    ('region', pa.string()), ('machine_kind', pa.string()),
    ('operating_system', pa.string()), ('environment', pa.string()), ('machines', pa.int64())])


def export_inventory_snapshot(lake, journal, *, source, scope, audience, subsidiary_ids):
    if not isinstance(audience, str) or not re.fullmatch('[a-zA-Z0-9_-]{1,64}', audience):
        raise ValueError('Invalid BI audience')
    if not isinstance(subsidiary_ids, (list,tuple,set)) or not subsidiary_ids or any(
            not isinstance(s,str) or not s.strip() for s in subsidiary_ids):
        raise ValueError('An explicit subsidiary selection is required')
    selected = sorted(set(subsidiary_ids))
    with journal.store.connect() as db:
        protect_backup(db)
        reader = PublishedCollection(lake,journal,source,scope)
        manifest = reader.manifest
        if not manifest or not manifest.get('index_run'):
            raise ValueError('No published inventory index')
        index = db.execute('SELECT * FROM inventory_runs WHERE id=%s AND namespace=%s AND manifest_key=%s',
            (manifest['index_run'],manifest['index_namespace'],manifest['index_manifest_key'])).fetchone()
        if index is None:
            raise ValueError('Published inventory index unavailable')
        found = {r['subsidiary'] for r in db.execute(
            "SELECT DISTINCT subsidiary FROM inventory_entities WHERE run_id=%s AND entity='sites' AND subsidiary=ANY(%s)",
            (index['id'],selected)).fetchall()}
        if found != set(selected):
            raise ValueError('Some selected subsidiaries are absent from the index')
        rows = inventory_counts(db,index['id'],selected)
        table = pa.Table.from_pylist([{'captured_at':index['captured_at'],**r} for r in rows],schema=SCHEMA)
        prefix = f'gold/bi/{audience}/{uuid4()}'
        ref = lake.delta.replace(prefix+'/inventory_counts',table)
        if not lake.delta.read(ref).equals(table):
            raise ValueError('BI inventory verification failed')
        exported = {'schema_version':1,'audience':audience,'source':source,'scope':scope,
            'source_run_id':manifest['run_id'],'source_manifest_fingerprint':fingerprint(encoded(manifest)),
            'subsidiary_ids':selected,'tables':{'inventory_counts':ref.to_dict()},
            'rows':len(rows),'content':'inventory_machine_counts'}
        key=prefix+'/manifest.json'
        lake.put_json(key,exported)
        if json.loads(lake.get_bytes(key)) != exported:
            raise ValueError('BI inventory manifest verification failed')
        return {'source_manifest_key':reader.manifest_key,'manifest_key':key,
                'fingerprint':fingerprint(encoded(exported)),'manifest':exported}


def inventory_counts(db, index_run, selected):
    """Internal aggregation; caller validates publication and authorized selection."""
    return db.execute("""WITH machine_counts AS MATERIALIZED (
        SELECT site,kind,os,environment,count(*) AS machines FROM inventory_entities
        WHERE run_id=%s AND entity='machines' AND subsidiary=ANY(%s)
        GROUP BY site,kind,os,environment)
        SELECT s.subsidiary AS subsidiary_id,s.data->>'subsidiary' AS subsidiary_name,
            s.id AS site_id,s.name AS site_name,s.country,s.region,
            m.kind AS machine_kind,m.os AS operating_system,m.environment,
            COALESCE(m.machines,0) AS machines
        FROM inventory_entities s LEFT JOIN machine_counts m ON m.site=s.id
        WHERE s.run_id=%s AND s.entity='sites' AND s.subsidiary=ANY(%s)
        ORDER BY s.subsidiary,s.id,m.kind,m.os,m.environment""",
        (index_run,selected,index_run,selected)).fetchall()
