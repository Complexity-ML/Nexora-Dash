"""Read only the pinned, self-contained table of an audience publication."""
import csv
import json
import re
from io import StringIO
from app.bi.license_snapshot import SCHEMA as LICENSE_SCHEMA
from app.bi.snapshot import SCHEMA as POOL_SCHEMA
from app.bi.inventory_snapshot import SCHEMA as INVENTORY_SCHEMA
from app.collection.journal import fingerprint
from app.collection.runner import encoded
from app.storage.table_reader import read_table


class TableUnavailable(ValueError):
    pass


TABLES = {'license_entitlements': (LICENSE_SCHEMA, 'source_license_entitlements'),'pool_usage': (POOL_SCHEMA, 'pool_capacity_observations'),
          'inventory_counts': (INVENTORY_SCHEMA, 'inventory_machine_counts')}


def verified_manifest(lake, artifact, audience):
    key = artifact['manifest_key']
    if not re.fullmatch(r'gold/bi/' + re.escape(audience) + r'/[a-zA-Z0-9_-]+/manifest.json', key):
        raise ValueError('Invalid BI manifest path')
    manifest = json.loads(lake.get_bytes(key))
    if fingerprint(encoded(manifest)) != artifact['fingerprint']:
        raise ValueError('Invalid BI manifest fingerprint')
    if (manifest['audience'] != audience or type(manifest['schema_version']) is not int
            or manifest['schema_version'] != 1 or type(manifest['rows']) is not int
            or manifest['rows'] < 0 or not manifest['tables']):
        raise ValueError('Invalid BI manifest metadata')
    for name, reference in manifest['tables'].items():
        if name not in TABLES or manifest.get('content') != TABLES[name][1]:
            raise ValueError('Invalid BI content type')
        if (reference.get('format') != 'delta'
                or reference.get('path') != key.removesuffix('/manifest.json') + '/' + name
                or type(reference.get('version')) is not int or reference['version'] < 0
                or reference.get('observation_date') is not None):
            raise ValueError('Invalid BI table reference')
    return manifest


def publication_description(lake, artifact, audience):
    manifest = verified_manifest(lake, artifact, audience)
    fields = ('schema_version','audience','source','scope','source_run_id',
              'source_manifest_fingerprint','content','rows','pool_ids','software_ids',
              'subsidiary_ids','includes_global_entitlements','excluded_global_entitlements')
    result = {key:manifest[key] for key in fields if key in manifest}
    result['tables'] = {name:{'version':ref['version'],
        'columns':[{'name':field.name,'type':str(field.type)} for field in TABLES[name][0]]}
        for name,ref in manifest['tables'].items()}
    return result


def snapshot_csv(lake, artifact, audience, table_name):
    schema, _ = TABLES[table_name]
    manifest = verified_manifest(lake, artifact, audience)
    if table_name not in manifest['tables']:
        raise TableUnavailable('Table absent from this publication')
    reference = manifest['tables'][table_name]
    table = read_table(lake, reference)
    if table.schema != schema or table.num_rows != manifest['rows']:
        raise ValueError('Invalid BI table schema or row count')
    buffer = StringIO(newline='')
    writer = csv.writer(buffer)
    writer.writerow(schema.names)
    for row in table.to_pylist():
        writer.writerow([row[name] for name in schema.names])
    return buffer.getvalue()


def pool_csv(lake, artifact, audience):
    return snapshot_csv(lake, artifact, audience, 'pool_usage')
