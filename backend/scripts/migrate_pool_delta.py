"""Prepare daily Delta capacity history; activate only with collectors stopped."""
import argparse
from collections import defaultdict
from datetime import date
import json
import pyarrow as pa
from app.dependencies import get_pipeline
from app.storage import pool_tables
from app.storage.table_reader import read_table
from scripts.migrate_enterprise_delta import verify


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--activate', action='store_true')
    args = parser.parse_args()
    pipeline = get_pipeline()
    lake = pipeline.store
    if pool_tables.enabled(lake):
        print(json.dumps({'already_delta': True}), flush=True)
        return
    revision = lake.usage_revision()
    grouped = defaultdict(list)
    for key in lake.list_keys('silver/usage/'):
        if key.endswith('.parquet'):
            grouped[key.split('/date=')[1].split('/')[0]].append(key)
    rows = 0
    for day, keys in sorted(grouped.items()):
        table = pa.concat_tables([read_table(lake, key) for key in sorted(keys)], promote_options='permissive')
        ref = lake.delta.replace_day(pool_tables.PATH, date.fromisoformat(day), table).to_dict()
        ref['observation_date'] = day
        verify(table, read_table(lake, ref))
        rows += table.num_rows
    # Keep the original inventory snapshots as well as the enterprise inventory.
    grouped_inventory = defaultdict(list)
    for key in lake.list_keys('silver/inventory/'):
        if key.endswith('.parquet'):
            grouped_inventory[key.split('/date=')[1].split('/')[0]].append(key)
    for day, keys in sorted(grouped_inventory.items()):
        values = [json.dumps(row, default=str) for key in sorted(keys) for row in read_table(lake, key).to_pylist()]
        table = pa.table({'snapshot_json': values})
        ref = lake.delta.replace_day('silver/inventory_snapshots', date.fromisoformat(day), table).to_dict()
        ref['observation_date'] = day
        verify(table, read_table(lake, ref))
    for key in lake.list_keys('silver/catalog/'):
        if key.endswith('.parquet'):
            table = read_table(lake, key)
            ref = lake.delta.replace(key.removesuffix('.parquet'), table).to_dict()
            verify(table, read_table(lake, ref))
    if lake.usage_revision() != revision:
        raise RuntimeError('Pool history changed during migration; not activated')
    report = {'format': 'delta', 'path': pool_tables.PATH, 'days': len(grouped),
              'rows': rows, 'source_revision': revision,
              'version': lake.delta.latest(pool_tables.PATH).version}
    lake.put_json('gold/migrations/pool-delta-prepared.json', report)
    if args.activate:
        lake.put_json(pool_tables.MARKER, report)
    print(json.dumps({**report, 'activated': args.activate}), flush=True)


if __name__ == '__main__':
    main()
