"""Publish a prepared migration while the local backend and collectors are stopped."""
import argparse
import hashlib
import json
from app.business.store import BusinessStore
from app.config import get_settings
from app.dependencies import get_pipeline
from app.storage import pool_tables
from app.storage.table_reader import read_table


def business_fingerprint(db):
    result = {}
    for table in ('users', 'workspaces', 'members', 'cases', 'events', 'workspace_costs', 'workspace_portfolios'):
        rows = db.execute(f'SELECT to_jsonb(t)::text AS value FROM {table} t ORDER BY 1').fetchall()
        result[table] = hashlib.sha256('\n'.join(r['value'] for r in rows).encode()).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', required=True)
    args = parser.parse_args()
    if not args.manifest.startswith('gold/enterprise/delta-') or not args.manifest.endswith('/manifest.json'):
        raise ValueError('Expected a prepared Delta migration manifest')
    lake = get_pipeline().store
    manifest = json.loads(lake.get_bytes(args.manifest))
    pools = json.loads(lake.get_bytes('gold/migrations/pool-delta-prepared.json'))
    if manifest.get('storage_format') != 'delta':
        raise ValueError('Inventory migration is not prepared')
    pool_revision_matches = pools['source_revision'] == lake.usage_revision()
    already_delta = pool_tables.enabled(lake) and pool_tables.reference(lake).version == pools['version']
    if not pool_revision_matches and not already_delta:
        raise RuntimeError('Pool history changed since preparation')
    for item in manifest['dimensions'].values():
        if read_table(lake, item).num_rows != item['rows']:
            raise RuntimeError('Prepared dimension has changed')
    business = BusinessStore(get_settings().database_url)
    with business.connect() as db:
        before = business_fingerprint(db)
        current = db.execute('SELECT run_id FROM inventory_heads WHERE namespace=%s FOR UPDATE', (lake.prefix,)).fetchone()
        if not current or str(current['run_id']) != manifest['migration_source_run']:
            raise RuntimeError('Inventory changed since preparation')
        run = db.execute('SELECT manifest_key FROM inventory_runs WHERE id=%s FOR UPDATE', (current['run_id'],)).fetchone()
        if run['manifest_key'] not in (manifest['migration_source_manifest'], args.manifest):
            raise RuntimeError('Inventory manifest changed since preparation')
        db.execute('UPDATE inventory_runs SET manifest_key=%s WHERE id=%s', (args.manifest, current['run_id']))
        if business_fingerprint(db) != before:
            raise RuntimeError('Business data changed during migration')
    # Readers must remain stopped until both independent dataset pointers are published.
    lake.put_json(pool_tables.MARKER, pools)
    lake.put_json('gold/migrations/activation.json', {'inventory_manifest': args.manifest,
                  'business_fingerprint': before, 'pool_version': pools['version']})
    print(json.dumps({'activated': True, 'business_data_unchanged': True,
                      'inventory_manifest': args.manifest, 'pool_rows': pools['rows']}), flush=True)


if __name__ == '__main__':
    main()
