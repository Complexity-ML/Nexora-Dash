"""Export a self-contained Gold snapshot for an explicitly selected BI audience."""
from datetime import date
import json
import re
from uuid import uuid4
import pyarrow as pa
from app.collection.reader import PublishedCollection
from app.collection.journal import fingerprint
from app.collection.runner import encoded
from app.collection.maintenance_lock import protect_backup
from app.storage.table_reader import read_table

SCHEMA = pa.schema([
    ('day', pa.date32()), ('software_id', pa.string()), ('license_pool_id', pa.string()),
    ('software_name', pa.string()), ('capacity', pa.int64()), ('used', pa.int64()), ('available', pa.int64())])


def export_pool_snapshot(lake, journal, *, source, scope, audience, pool_ids):
    """Return an immutable candidate, without granting access or changing BI pointers.

    The operator must authorize the pool selection for this audience. These are
    pool observations, not enterprise-wide installations, rights or savings.
    """
    if not isinstance(audience, str) or not re.fullmatch('[a-zA-Z0-9_-]{1,64}', audience):
        raise ValueError('Invalid BI audience')
    if not isinstance(pool_ids, (list, set, tuple)) or not pool_ids or any(not isinstance(p, str) or not p.strip() for p in pool_ids):
        raise ValueError('An explicit non-empty pool selection is required')
    selected = set(pool_ids)
    with journal.store.connect() as protection:
        protect_backup(protection)
        reader = PublishedCollection(lake, journal, source, scope)
        if reader.manifest is None:
            raise ValueError('No published collection')
        rows, observed = [], set()
        for day, item in sorted(reader.manifest['daily'].items()):
            for row in read_table(lake, item['usage']).to_pylist():
                if row['license_pool_id'] in selected:
                    observed.add(row['license_pool_id'])
                    rows.append({'day':date.fromisoformat(day), **{name:row[name] for name in SCHEMA.names if name != 'day'}})
        if observed != selected:
            raise ValueError('Some selected pools are absent from published history')
        table = pa.Table.from_pylist(rows, schema=SCHEMA)
        prefix = f'gold/bi/{audience}/{uuid4()}'
        reference = lake.delta.replace(prefix+'/pool_usage', table)
        if not lake.delta.read(reference).equals(table):
            raise ValueError('BI snapshot verification failed')
        manifest = {'schema_version':1, 'audience':audience, 'source':source, 'scope':scope,
                    'source_run_id':reader.manifest['run_id'],
                    'source_manifest_fingerprint':fingerprint(encoded(reader.manifest)),
                    'pool_ids':sorted(selected), 'tables':{'pool_usage':reference.to_dict()},
                    'rows':len(rows), 'content':'pool_capacity_observations'}
        key = prefix+'/manifest.json'
        lake.put_json(key, manifest)
        if json.loads(lake.get_bytes(key)) != manifest:
            raise ValueError('BI manifest verification failed')
        return {'source_manifest_key':reader.manifest_key, 'manifest_key':key, 'fingerprint':fingerprint(encoded(manifest)), 'manifest':manifest}
