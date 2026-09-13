from app.business.errors import BusinessError
import asyncio

from app.dependencies import get_pipeline
from app.business.portfolio_service import selected_pools
from app.business.workspace_service import current_user, source_operator
from app.models.canonical import AnalyticsSummary, LicenseStock, LicenseUsage, Trend, InactiveCandidate, UsageSnapshot, PlatformStatus, DemoGenerationRequest
from app.services.pipeline import SamPipeline


async def sync(pipeline: SamPipeline=None):
    return await pipeline.sync()

async def summary(pipeline: SamPipeline, pool_ids=None) -> AnalyticsSummary:
    await pipeline.bootstrap_mock_history()
    return await asyncio.to_thread(pipeline.run_analytics) if pool_ids is None else await asyncio.to_thread(pipeline.run_analytics,pool_ids)

async def analytics_summary(pool_ids=None, pipeline: SamPipeline=None): return await summary(pipeline,pool_ids)

async def live(pool_ids=None, pipeline: SamPipeline=None):
    if hasattr(pipeline.store,'collection'):
        snapshot = await asyncio.to_thread(pipeline.store.collection.latest_snapshot)
        values = snapshot.usage if snapshot else []
    else:
        values = await pipeline.connector.get_current_usage()
    return values if pool_ids is None else [v for v in values if v.license_pool_id in pool_ids]

async def stock(pool_ids=None, pipeline: SamPipeline=None):
    if hasattr(pipeline.store,'collection'):
        snapshot = await asyncio.to_thread(pipeline.store.collection.latest_snapshot)
        values = snapshot.stock if snapshot else []
    else:
        values = await pipeline.connector.get_license_stock()
    return values if pool_ids is None else [v for v in values if v.license_pool_id in pool_ids]

async def history(pool_ids=None, pipeline: SamPipeline=None): return (await summary(pipeline,pool_ids)).trends

async def trends(pool_ids=None, pipeline: SamPipeline=None): return (await summary(pipeline,pool_ids)).trends

async def inactive(pool_ids=None, pipeline: SamPipeline=None): return (await summary(pipeline,pool_ids)).inactive


def platform(pipeline: SamPipeline = None):
    from datetime import datetime, timezone
    import re
    from app.config import get_settings
    from app.models.canonical import PlatformStatus, StorageLayer

    settings = get_settings()
    layers = []
    for name in ("bronze", "silver", "gold"):
        keys = sorted(pipeline.store.list_keys(f"{name}/"))
        dates = sorted({match.group(1) for key in keys
                        if (match := re.search(r"date=(\d{4}-\d{2}-\d{2})/", key))})
        layers.append(StorageLayer(name=name, count=len(keys),
            first_date=dates[0] if dates else None, last_date=dates[-1] if dates else None,
            sample_keys=[getattr(pipeline.store,'prefix','')+key for key in keys[-12:]]))
    return PlatformStatus(mode=settings.sam_data_source,
        demo_tools_enabled=settings.demo_tools_enabled and settings.sam_data_source == "mock",
        checked_at=datetime.now(timezone.utc), spark_master=settings.spark_master,
        underutilization_threshold=pipeline.analytics.threshold,
        recovery_buffer_rate=pipeline.analytics.buffer_rate, layers=layers)


async def generate_demo(body: DemoGenerationRequest, pipeline: SamPipeline = None):
    from app.connectors.digimon import MockDigimonConnector
    from app.config import get_settings
    if not get_settings().demo_tools_enabled or get_settings().sam_data_source != "mock" or not isinstance(pipeline.connector, MockDigimonConnector):
        raise BusinessError(status_code=409, detail="La génération est réservée au mode démonstration.")
    return await pipeline.generate_demo_history(body.days)
