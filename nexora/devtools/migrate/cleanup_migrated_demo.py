"""Remove obsolete demo objects after verified Delta activation; dry-run by default."""
import argparse
import json
from app.config import get_settings
from app.dependencies import get_pipeline
from app.business.store import BusinessStore
from app.collection.maintenance_lock import protect_deletion
from devtools.migrate.activate_delta import business_fingerprint



def require_legacy_only(db):
    """Keep this pre-journal cleanup from deleting recovery dependencies.

    The caller must retain the transaction through deletion. SHARE blocks run
    registration and claims until cleanup finishes; an existing run blocks cleanup.
    """
    protect_deletion(db)
    if db.execute("SELECT to_regclass('collection_runs') AS relation").fetchone()['relation'] is None:
        raise RuntimeError('Migrate recovery metadata before checking cleanup safety')
    db.execute('LOCK TABLE collection_runs IN SHARE MODE')
    if db.execute('SELECT EXISTS (SELECT 1 FROM collection_runs) AS present').fetchone()['present']:
        raise RuntimeError('Legacy cleanup cannot delete objects referenced by collection recovery; use journal-aware maintenance')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    settings = get_settings()
    if settings.sam_data_source != 'mock':
        raise RuntimeError('Local demonstration only')
    lake = get_pipeline().store
    audit = json.loads(lake.get_bytes('gold/migrations/activation.json'))
    business = BusinessStore(settings.database_url)
    with business.connect() as db:
        require_legacy_only(db)
        head = db.execute('SELECT run_id FROM inventory_heads WHERE namespace=%s FOR UPDATE', (lake.prefix,)).fetchone()
        run = db.execute('SELECT manifest_key FROM inventory_runs WHERE id=%s FOR UPDATE', (head['run_id'],)).fetchone()
        if run['manifest_key'] != audit['inventory_manifest']:
            raise RuntimeError('Active inventory has changed; review cleanup again')
        if business_fingerprint(db) != audit['business_fingerprint']:
            raise RuntimeError('Business data differs from migration audit')
        manifest = json.loads(lake.get_bytes(run['manifest_key']))
        if manifest.get('storage_format') != 'delta':
            raise RuntimeError('Active inventory is not Delta')
        roots = set()
        def refs(value):
            if isinstance(value, dict):
                if value.get('format') == 'delta':
                    roots.add(value['path'].rstrip('/')+'/')
                if isinstance(value.get('key'), str):
                    roots.add(value['key'])
                for item in value.values():
                    refs(item)
            elif isinstance(value, list):
                for item in value:
                    refs(item)
        refs(manifest)
        roots.add(run['manifest_key'])
        old_exact = {'silver/catalog/demo-v2.parquet', 'gold/demo/manifest.parquet',
                     'gold/analytics/latest.parquet', 'gold/trends/latest.parquet', 'gold/daily/latest.parquet'}
        selected = []
        total_bytes = 0
        for page in lake.client.get_paginator('list_objects_v2').paginate(Bucket=lake.bucket):
            for item in page.get('Contents', []):
                key = item['Key']
                total_bytes += item['Size']
                test = key.startswith(('delta-validation/', 'delta-fresh-validation/'))
                obsolete_generation = key.startswith('demo-generations/') and not key.startswith(lake.prefix)
                relative = key[len(lake.prefix):] if key.startswith(lake.prefix) else None
                obsolete = relative is not None and (relative in old_exact or relative.startswith(('silver/usage/', 'silver/inventory/')))
                if relative and relative.startswith(('silver/enterprise/', 'gold/enterprise/')):
                    obsolete = not any(relative == root or (root.endswith('/') and relative.startswith(root)) for root in roots)
                if test or obsolete_generation or obsolete:
                    selected.append(item)
        report = {'apply': args.apply, 'objects': len(selected), 'bytes': sum(i['Size'] for i in selected),
                  'bucket_bytes_before': total_bytes, 'active_prefix': lake.prefix,
                  'active_bronze_preserved': True, 'delta_versions_preserved': True}
        print(json.dumps(report), flush=True)
        if args.apply:
            for offset in range(0, len(selected), 1000):
                result = lake.client.delete_objects(Bucket=lake.bucket, Delete={
                    'Objects': [{'Key': i['Key']} for i in selected[offset:offset+1000]], 'Quiet': True})
                if result.get('Errors'):
                    raise RuntimeError('Some objects could not be removed')
            lake.put_json('gold/migrations/cleanup.json', report)


if __name__ == '__main__':
    main()
