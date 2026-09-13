"""Rebuild the read projection from the active versioned inventory generation."""
import json
from app.storage.table_reader import read_table
from app.config import get_settings
from app.dependencies import get_pipeline
from app.business.store import BusinessStore
from app.business.inventory_index import publish_index
from app.models.inventory import InventorySnapshot


def main():
    lake = get_pipeline().store
    store = BusinessStore(get_settings().database_url)
    with store.connect() as db:
        head = db.execute('SELECT r.* FROM inventory_heads h JOIN inventory_runs r ON r.id=h.run_id WHERE h.namespace=%s', (lake.prefix,)).fetchone()
    if not head or not head['manifest_key'].startswith('gold/enterprise/'):
        raise RuntimeError('No active enterprise inventory')
    manifest = json.loads(lake.get_bytes(head['manifest_key']))
    raw = {name:read_table(lake, item).to_pylist()
           for name,item in manifest['dimensions'].items()}
    latest = max(manifest['daily'], key=lambda item:item['date'])
    raw['observations'] = read_table(lake, latest).to_pylist()
    snapshot = InventorySnapshot(captured_at=head['captured_at'], source=head['source'], **raw)
    run = publish_index(store, lake.prefix, snapshot, head['manifest_key'], expected_run=head['id'], expected_manifest=head['manifest_key'])
    print(json.dumps({'run':run, 'products':len(snapshot.products), 'machines':len(snapshot.machines), 'manifest_preserved':True}), flush=True)


if __name__ == '__main__':
    main()
