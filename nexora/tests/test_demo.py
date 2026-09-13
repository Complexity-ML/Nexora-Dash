import asyncio
from datetime import datetime, timezone
import pytest
from app.connectors.demo import snapshot
from app.connectors.digimon import MockDigimonConnector, map_digimon_payload
from app.services.pipeline import SamPipeline


def test_demo_is_deterministic_and_has_twelve_valid_pools():
    at = datetime(2026, 9, 11, tzinfo=timezone.utc)
    assert snapshot(at) == snapshot(at)
    mapped = map_digimon_payload(snapshot(at))
    assert len(mapped.usage) == 12
    assert all(0 <= p.used <= p.capacity for p in mapped.usage)
    assert len({p.license_pool_id for p in mapped.usage}) == 12
    before = map_digimon_payload(snapshot(datetime(2026, 1, 1, tzinfo=timezone.utc)))
    assert next(p.capacity for p in before.usage if p.license_pool_id == 'flex-abaqus') > next(p.capacity for p in mapped.usage if p.license_pool_id == 'flex-abaqus')


class MemoryStore:
    def __init__(self): self.objects = {}
    def put_parquet(self, key, rows): self.objects[key] = rows


def test_generation_preserves_existing_objects_and_reuses_daily_partitions():
    store = MemoryStore()
    store.objects['silver/usage/existing.parquet'] = [{'preserved': True}]
    pipeline = SamPipeline(MockDigimonConnector(), store, None)
    report = asyncio.run(pipeline.generate_demo_history(30))
    assert report['usage_rows'] == 360
    assert store.objects['silver/usage/existing.parquet'] == [{'preserved': True}]
    generated = [k for k in store.objects if k.startswith('silver/usage/') and 'sam-demo-v2' in k]
    assert len(generated) == 30
    assert all(len(store.objects[k]) == 12 for k in generated)
    first_keys = set(store.objects)
    first_rows = {key: rows for key, rows in store.objects.items() if key.startswith(('bronze/', 'silver/'))}
    asyncio.run(pipeline.generate_demo_history(30))
    assert set(store.objects) == first_keys
    assert {key: rows for key, rows in store.objects.items() if key.startswith(('bronze/', 'silver/'))} == first_rows
    assert sum(len(rows) for key, rows in store.objects.items() if key.startswith('silver/usage/') and 'sam-demo-v2' in key) == report['usage_rows']
    assert len([key for key in store.objects if key.startswith('silver/usage/')]) == 31  # 30 partitions plus preserved object
    assert len([k for k in store.objects if k.startswith('silver/usage/') and 'sam-demo-v2' in k]) == 30
    with pytest.raises(ValueError): asyncio.run(pipeline.generate_demo_history(10000))
    with pytest.raises(ValueError): asyncio.run(SamPipeline(object(), store, None).generate_demo_history(30))


def test_pool_demo_never_injects_legacy_inventory():
    assert "inventory" not in snapshot(datetime(2026, 1, 1, tzinfo=timezone.utc))
