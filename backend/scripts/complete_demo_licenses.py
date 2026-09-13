"""Publish complete fictitious license models without regenerating usage history."""
import json
from uuid import uuid4
from app.config import get_settings
from app.dependencies import get_pipeline
from app.business.store import BusinessStore
from app.connectors.enterprise_software import demo_entitlements
from app.storage.inventory_tables import inventory_table
from app.storage.table_reader import read_table
from app.models.inventory import map_inventory_payload


def main():
    settings = get_settings()
    if settings.sam_data_source != 'mock':
        raise RuntimeError('Fictitious data only')
    pipeline = get_pipeline()
    lake = pipeline.store
    business = BusinessStore(settings.database_url)
    with business.connect() as db:
        head = db.execute('SELECT r.* FROM inventory_heads h JOIN inventory_runs r ON r.id=h.run_id WHERE h.namespace=%s', (lake.prefix,)).fetchone()
    manifest = json.loads(lake.get_bytes(head['manifest_key']))
    products = read_table(lake, manifest['dimensions']['products']).to_pylist()
    subsidiaries = read_table(lake, manifest['dimensions']['subsidiaries']).to_pylist()
    rows = demo_entitlements(products, subsidiaries)
    source_key = 'bronze/demo-licenses/'+str(uuid4())+'.json'
    lake.put_json(source_key, {'capturedAt':head['captured_at'].isoformat(),
        'provider':'digimon-mock', 'inventory':{'products':products,
        'subsidiaries':subsidiaries, 'entitlements':rows}})
    snapshot = map_inventory_payload(json.loads(lake.get_bytes(source_key)))
    rows = [r.model_dump(mode='json') for r in snapshot.entitlements]
    root = 'silver/enterprise/demo-licenses-'+str(uuid4())
    reference = lake.delta.replace(root, inventory_table('entitlements', rows)).to_dict()
    sort_rows = lambda values: sorted(values, key=lambda row: row['entitlement_id'])
    if sort_rows(read_table(lake, reference).to_pylist()) != sort_rows(inventory_table('entitlements', rows).to_pylist()):
        raise RuntimeError('Incomplete license models')
    updated = {**manifest, 'license_source_key':source_key, 'dimensions':{**manifest['dimensions'], 'entitlements':{**reference,'rows':len(rows)}}}
    key = 'gold/enterprise/demo-licenses-'+str(uuid4())+'/manifest.json'
    lake.put_json(key, updated)
    with business.connect() as db:
        current = db.execute('SELECT run_id FROM inventory_heads WHERE namespace=%s FOR UPDATE', (lake.prefix,)).fetchone()
        run = db.execute('SELECT manifest_key FROM inventory_runs WHERE id=%s FOR UPDATE', (head['id'],)).fetchone()
        if current['run_id'] != head['id'] or run['manifest_key'] != head['manifest_key']:
            raise RuntimeError('Inventory changed; update not published')
        db.execute('UPDATE inventory_runs SET manifest_key=%s WHERE id=%s', (key,head['id']))
    print(json.dumps({'products':len(products),'license_models':len(rows),'history_unchanged':True}))


if __name__ == '__main__':
    main()
