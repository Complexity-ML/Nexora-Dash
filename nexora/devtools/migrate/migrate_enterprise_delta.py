"""Migrate the active inventory without deleting source files or changing its index."""
import argparse
from datetime import date
import json
from uuid import uuid4
import pyarrow as pa
import pyarrow.compute as pc
from app.business.store import BusinessStore
from app.config import get_settings
from app.dependencies import get_pipeline
from app.storage.inventory_tables import inventory_table
from app.storage.delta_tables import DeltaReference
from app.storage.table_reader import read_table


def verify(expected, actual):
    actual = actual.select(expected.column_names).cast(expected.schema)
    keys = [(name, 'ascending') for name in expected.column_names
            if not pa.types.is_nested(expected.schema.field(name).type)]
    if not keys or not expected.take(pc.sort_indices(expected, sort_keys=keys)).equals(
            actual.take(pc.sort_indices(actual, sort_keys=keys))):
        raise RuntimeError('Delta migration changed table content')


def migrate(lake, manifest, root, resume=False):
    updated = {**manifest, 'storage_format': 'delta'}
    dimensions = {}
    for name, item in manifest['dimensions'].items():
        table = inventory_table(name, read_table(lake, item))
        ref = lake.delta.replace(f'silver/enterprise/{root}/{name}', table).to_dict()
        verify(table, read_table(lake, ref))
        dimensions[name] = {**ref, 'rows': table.num_rows}
        print(json.dumps({'dimension_verified': name, 'rows': table.num_rows}), flush=True)
    updated['dimensions'] = dimensions
    for field in ('daily', 'product_usage_daily'):
        partitions = []
        existing = None
        if resume:
            from deltalake.exceptions import TableNotFoundError
            try:
                existing = lake.delta.latest(f'silver/enterprise/{root}/{field}').to_dict()
                lake.delta.open(DeltaReference(
                    existing['path'], existing['version'])).create_checkpoint()
            except TableNotFoundError:
                pass
        for i, item in enumerate(manifest.get(field, []), 1):
            table = read_table(lake, item)
            if field == 'daily':
                table = inventory_table('observations', table.drop(['observation_date'])
                                        if 'observation_date' in table.column_names else table)
            ref = {**existing, 'observation_date': item['date']} if existing else None
            persisted = read_table(lake, ref) if ref else None
            if persisted is None or persisted.num_rows == 0:
                ref = lake.delta.replace_day(f'silver/enterprise/{root}/{field}',
                                             date.fromisoformat(item['date']), table).to_dict()
                ref['observation_date'] = item['date']
            verify(table, read_table(lake, ref))
            partitions.append({**ref, 'date': item['date'], 'rows': table.num_rows})
            if i % 10 == 0:
                print(json.dumps({'table': field, 'days_verified': i}), flush=True)
        if partitions:
            # All days refer to the same final version: compaction can subsequently
            # advance this table and its manifest together without keeping 365 versions.
            final_version = partitions[-1]['version']
            for item in partitions:
                item['version'] = final_version
            updated[field] = partitions
    report_meta = manifest.get('installation_usage')
    if report_meta:
        report = json.loads(lake.get_bytes(report_meta['key']))
        table = read_table(lake, report_meta.get('detail_key') or report['detail_key'])
        ref = lake.delta.replace(f'gold/enterprise/{root}/installation_usage', table).to_dict()
        verify(table, read_table(lake, ref))
        report_key = f'gold/enterprise/{root}/installation-usage.json'
        lake.put_json(report_key, {**report, 'detail_key': ref})
        updated['installation_usage'] = {**report_meta, 'key': report_key, 'detail_key': ref}
    return updated


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--activate', action='store_true')
    parser.add_argument('--resume-root')
    args = parser.parse_args()
    lake = get_pipeline().store
    business = BusinessStore(get_settings().database_url)
    with business.connect() as db:
        head = db.execute('SELECT r.* FROM inventory_heads h JOIN inventory_runs r ON r.id=h.run_id WHERE h.namespace=%s', (lake.prefix,)).fetchone()
    if not head:
        raise RuntimeError('No active inventory')
    manifest = json.loads(lake.get_bytes(head['manifest_key']))
    if manifest.get('storage_format') == 'delta':
        print('Active inventory already uses Delta', flush=True)
        return
    root = args.resume_root or 'delta-' + str(uuid4())
    updated = migrate(lake, manifest, root, resume=bool(args.resume_root))
    updated['migration_source_manifest'] = head['manifest_key']
    updated['migration_source_run'] = str(head['id'])
    key = f'gold/enterprise/{root}/manifest.json'
    lake.put_json(key, updated)
    if not args.activate:
        print(json.dumps({'prepared': True, 'manifest': key, 'activated': False}), flush=True)
        return
    with business.connect() as db:
        current = db.execute('SELECT run_id FROM inventory_heads WHERE namespace=%s FOR UPDATE', (lake.prefix,)).fetchone()
        if not current or current['run_id'] != head['id']:
            raise RuntimeError('Inventory changed; migration was not activated')
        run = db.execute('SELECT manifest_key FROM inventory_runs WHERE id=%s FOR UPDATE', (head['id'],)).fetchone()
        if run['manifest_key'] != head['manifest_key']:
            raise RuntimeError('Manifest changed; migration was not activated')
        db.execute('UPDATE inventory_runs SET manifest_key=%s WHERE id=%s', (key, head['id']))
    print(json.dumps({'activated': True, 'manifest': key, 'previous_manifest': head['manifest_key']}), flush=True)


if __name__ == '__main__':
    main()
