"""Enrich an existing mock lake with deterministic inventory, preserving license data."""
from datetime import datetime, timezone
from app.config import get_settings
from app.dependencies import get_pipeline
from app.connectors.demo import snapshot
from app.models.inventory import map_inventory_payload
from app.storage.object_store import partition_key
import json
import pyarrow as pa
from app.storage import pool_tables


def main():
    if get_settings().sam_data_source != 'mock':
        raise RuntimeError('Inventory seeding requires the mock data source')
    store = get_pipeline().store
    if pool_tables.enabled(store):
        reference = pool_tables.reference(store)
        days = sorted({str(day) for day in store.delta.read(reference, columns=['observation_date'])['observation_date'].to_pylist()}) if reference else []
    else:
        days = sorted({key.split('/date=')[1].split('/')[0]
                       for key in store.list_keys('silver/usage/')})
    for day in days:
        at = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
        raw = snapshot(at)
        value = map_inventory_payload(raw)
        name = 'demo-inventory-v1.parquet'
        store.put_parquet(partition_key('bronze','inventory',at.date(),name),
                          [{'captured_at':at.isoformat(),'payload_json':json.dumps(raw['inventory'])}])
        store.delta.replace_day('silver/inventory_snapshots', at.date(),
                                pa.table({'snapshot_json': [value.model_dump_json()]}))
    print(f'Inventory added to {len(days)} existing daily partitions; license observations unchanged.')


if __name__ == '__main__':
    main()
