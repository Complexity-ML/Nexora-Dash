"""Export source entitlement rows without inferring quantities from installations."""
from datetime import date
import json
import re
from uuid import uuid4
import pyarrow as pa
from app.collection.reader import PublishedCollection
from app.collection.maintenance_lock import protect_backup
from app.collection.journal import fingerprint
from app.collection.runner import encoded
from app.storage.table_reader import read_table

SCHEMA=pa.schema([
    ('day',pa.date32()),('entitlement_id',pa.string()),('software_id',pa.string()),
    ('software_name',pa.string()),('subsidiary_id',pa.string()),('subsidiary_name',pa.string()),
    ('metric',pa.string()),('quantity',pa.int64()),('annual_unit_cost_cents',pa.int64()),
    ('currency',pa.string()),('synthetic',pa.bool_())])


def export_license_snapshot(lake,journal,*,source,scope,audience,software_ids,subsidiary_ids,include_global=False):
    if not isinstance(audience,str) or not re.fullmatch('[a-zA-Z0-9_-]{1,64}',audience):
        raise ValueError('Invalid BI audience')
    if type(include_global) is not bool:
        raise ValueError('include_global must be an explicit boolean')
    for selection in (software_ids,subsidiary_ids):
        if not isinstance(selection,(list,tuple,set)) or any(not isinstance(v,str) or not v.strip() for v in selection):
            raise ValueError('Explicit products and subsidiaries are required')
    if not software_ids or (not subsidiary_ids and not include_global):
        raise ValueError('Select products and at least one subsidiary or global rights')
    selected_products,selected_subsidiaries=set(software_ids),set(subsidiary_ids)
    with journal.store.connect() as db:
        protect_backup(db)
        reader=PublishedCollection(lake,journal,source,scope)
        if not reader.manifest or not reader.manifest['daily']:
            raise ValueError('No published history')
        day=max(reader.manifest['daily'])
        dimensions=reader.manifest['daily'][day].get('dimensions',{})
        if not all(name in dimensions for name in ('products','subsidiaries','entitlements')):
            raise ValueError('Published license dimensions unavailable')
        products={r['software_id']:r for r in read_table(lake,dimensions['products']).to_pylist()}
        subsidiaries={r['subsidiary_id']:r for r in read_table(lake,dimensions['subsidiaries']).to_pylist()}
        if not selected_products <= products.keys() or not selected_subsidiaries <= subsidiaries.keys():
            raise ValueError('Unknown product or subsidiary selection')
        rows=[]; excluded_global=0
        for right in read_table(lake,dimensions['entitlements']).to_pylist():
            if right['software_id'] not in selected_products:
                continue
            if right['subsidiary_id'] is None:
                if not include_global:
                    excluded_global+=1
                    continue
            elif right['subsidiary_id'] not in selected_subsidiaries:
                continue
            rows.append({'day':date.fromisoformat(day),
                **{k:right[k] for k in SCHEMA.names if k not in ('day','software_name','subsidiary_name')},
                'software_name':products[right['software_id']]['name'],
                'subsidiary_name':subsidiaries[right['subsidiary_id']]['name'] if right['subsidiary_id'] is not None else None})
        table=pa.Table.from_pylist(rows,schema=SCHEMA)
        prefix=f'gold/bi/{audience}/{uuid4()}'
        ref=lake.delta.replace(prefix+'/license_entitlements',table)
        if not lake.delta.read(ref).equals(table):
            raise ValueError('BI license verification failed')
        manifest={'schema_version':1,'audience':audience,'source':source,'scope':scope,
            'source_run_id':reader.manifest['run_id'],'source_manifest_fingerprint':fingerprint(encoded(reader.manifest)),
            'software_ids':sorted(selected_products),'subsidiary_ids':sorted(selected_subsidiaries),
            'includes_global_entitlements':include_global,'excluded_global_entitlements':excluded_global,'tables':{'license_entitlements':ref.to_dict()},
            'rows':len(rows),'content':'source_license_entitlements'}
        key=prefix+'/manifest.json';lake.put_json(key,manifest)
        if json.loads(lake.get_bytes(key)) != manifest:
            raise ValueError('BI license manifest verification failed')
        return {'source_manifest_key':reader.manifest_key,'manifest_key':key,
                'fingerprint':fingerprint(encoded(manifest)),'manifest':manifest}
