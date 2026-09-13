"""Exercise a completely empty MinIO namespace without changing the active lake."""
import asyncio
import json
from uuid import uuid4
from app.analytics import SparkAnalytics
from app.business.demo_service import REFERENCE_END, verify_reference
from app.business.inventory_service import latest_inventory
from app.config import get_settings
from app.connectors.digimon import MockDigimonConnector
from app.services.pipeline import SamPipeline
from app.storage.object_store import S3ParquetStore
from app.storage.pool_tables import reference


def main():
    settings = get_settings()
    if settings.sam_data_source != 'mock':
        raise RuntimeError('Only run against the local mock environment')
    prefix = 'delta-fresh-validation/' + str(uuid4()) + '/'
    def lake():
        return S3ParquetStore(settings.s3_endpoint_url, settings.s3_access_key,
                              settings.s3_secret_key, settings.s3_bucket, settings.s3_region, prefix)
    store = lake()
    assert store.list_keys('') == []
    pipeline = SamPipeline(MockDigimonConnector(), store, SparkAnalytics('local[1]', .35, .1))
    asyncio.run(pipeline.generate_demo_history(365, REFERENCE_END))
    summary = pipeline.run_analytics()
    verify_reference(summary)
    reopened = lake()
    pinned = reference(reopened)
    rows = reopened.delta.read(pinned)
    assert rows.num_rows == 4380
    assert len(set(rows['observation_date'].to_pylist())) == 365
    assert latest_inventory(reopened) is not None
    assert reopened.list_keys('silver/usage/') == []
    assert reopened.list_keys('silver/inventory/') == []
    # New process-equivalent readers must retrieve the persisted Gold cache.
    replay = SamPipeline(MockDigimonConnector(), reopened, SparkAnalytics('local[1]', .35, .1))
    assert replay.run_analytics() == summary
    assert 'spark' not in replay.analytics.__dict__
    for path in ('gold/analytics/latest', 'gold/trends/latest', 'gold/daily/latest'):
        assert reopened.delta.read(reopened.delta.latest(path)).num_rows > 0
    print(json.dumps({'verified': True, 'prefix': prefix, 'days': 365, 'rows': 4380,
                      'legacy_silver_files': 0, 'persistent_gold': True}), flush=True)


if __name__ == '__main__':
    main()
