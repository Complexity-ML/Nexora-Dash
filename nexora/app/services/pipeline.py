import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile
import json
import hashlib
from botocore.exceptions import ClientError

import pyarrow as pa
from app.storage import pool_tables
from app.analytics import SparkAnalytics
from app.connectors.digimon import DigimonConnector, MockDigimonConnector, map_digimon_payload
from app.models.canonical import AnalyticsSummary, UsageSnapshot
from app.storage.object_store import ObjectStore, partition_key


class SamPipeline:
    def __init__(self, connector: DigimonConnector, store: ObjectStore, analytics: SparkAnalytics):
        self.connector, self.store, self.analytics = connector, store, analytics

    def put_table(self, key, rows):
        if not hasattr(self.store, 'delta'):
            return self.store.put_parquet(key, rows)
        table = pa.Table.from_pylist(rows)
        # This metric is nullable even when a whole generation has no prior period.
        if 'previous_period_change' in table.column_names:
            index = table.column_names.index('previous_period_change')
            table = table.set_column(index, 'previous_period_change', table[index].cast(pa.float64()))
        return self.store.delta.replace(key.removesuffix('.parquet'), table)

    def collect_recoverable(self, raw, journal, **identity):
        """Opt-in journaled publication, isolated from legacy live pointers."""
        from app.collection.runner import CollectionRunner
        return CollectionRunner(self, journal).run(raw, **identity)

    async def sync(self) -> UsageSnapshot:
        raw = await self.connector.get_raw_snapshot()
        if hasattr(self, 'collection_journal'):
            from app.collection.runner import encoded
            from app.collection.journal import fingerprint
            is_mock = isinstance(self.connector, MockDigimonConnector)
            snapshot_id = raw.get('snapshotId') or (raw.get('capturedAt') if is_mock else None)
            revision = raw.get('sourceRevision') or (fingerprint(encoded(raw)) if is_mock else None)
            if not snapshot_id or not revision:
                raise ValueError('DIGIMON snapshotId and sourceRevision must be mapped before enabling collection')
            manifest = await asyncio.to_thread(self.collect_recoverable,raw,self.collection_journal,
                source=self.collection_source,scope=self.collection_scope,
                snapshot_id=str(snapshot_id),source_revision=str(revision))
            snapshot = map_digimon_payload(raw)
            snapshot.snapshot_id = manifest['run_id']
            return snapshot
        return self.persist_snapshot(raw)

    def persist_snapshot(self, raw: dict, snapshot_id: str | None = None) -> UsageSnapshot:
        from app.models.inventory import map_inventory_payload
        inventory = map_inventory_payload(raw)
        snapshot = map_digimon_payload(raw)
        if snapshot_id is not None:
            snapshot.snapshot_id = snapshot_id
        day, sid = snapshot.timestamp.date(), snapshot.snapshot_id
        self.store.put_parquet(partition_key("bronze", "digimon", day, f"{sid}.parquet"),
                               [{"snapshot_id": sid, "timestamp": snapshot.timestamp.isoformat(),
                                 "payload_json": json.dumps(raw)}])
        rows = [item.model_dump(mode="json") for item in snapshot.usage]
        if hasattr(self.store, 'delta'):
            pool_tables.persist(self.store, day, rows)
        else:
            self.store.put_parquet(partition_key("silver", "usage", day, f"{sid}.parquet"), rows)
        if inventory is not None:
            if hasattr(self.store, 'delta'):
                self.store.delta.replace_day('silver/inventory_snapshots', day,
                    pa.table({'snapshot_json': [inventory.model_dump_json()]}))
            else:
                self.store.put_parquet(partition_key("silver", "inventory", day, f"{sid}.parquet"),
                                       [inventory.model_dump(mode="json")])
        return snapshot

    async def bootstrap_mock_history(self, days: int = 120) -> None:
        if hasattr(self.store, "collection"):
            return
        if not isinstance(self.connector, MockDigimonConnector):
            return
        if (pool_tables.enabled(self.store) and pool_tables.reference(self.store)) or self.store.list_keys("silver/usage/"):
            return
        await self.generate_demo_history(days)

    async def generate_demo_history(self, days: int = 365, end_date: date | None = None) -> dict:
        if not isinstance(self.connector, MockDigimonConnector):
            raise ValueError("Demo generation is only available with the mock connector")
        if not 30 <= days <= 730:
            raise ValueError("Demo history must contain between 30 and 730 days")
        from app.connectors.demo import CATALOG, VERSION, snapshot
        now = datetime.now(timezone.utc)
        end = datetime.combine(end_date or now.date(), datetime.min.time(), timezone.utc)
        for offset in reversed(range(days)):
            at = end - timedelta(days=offset)
            self.persist_snapshot(snapshot(at), f"{VERSION}-{at.date()}")
        self.put_table("silver/catalog/demo-v2.parquet", [
            {"license_pool_id": pool, "software_name": name, "base_capacity": capacity,
             "scenario": scenario, "is_demo": True, "generator": VERSION}
            for pool, name, capacity, scenario in CATALOG])
        report = {"version": VERSION, "days": days, "pools": len(CATALOG),
            "usage_rows": days * len(CATALOG), "generated_at": now.isoformat(),
            "first_date": (end - timedelta(days=days - 1)).date().isoformat(),
            "last_date": end.date().isoformat()}
        self.put_table("gold/demo/manifest.parquet", [report])
        return report

    def run_analytics(self, pool_ids: list[str] | None = None) -> AnalyticsSummary:
        if hasattr(self.store, 'collection'):
            reader = self.store.collection
            if reader.manifest is None:
                return self.analytics.compute([],pool_ids)
            settings = {'threshold':self.analytics.threshold,'reserve':self.analytics.buffer_rate}
            if pool_ids is None and reader.manifest.get('analysis_settings') == settings:
                return reader.summary()
            return self.analytics.compute_table(reader.usage(),pool_ids)
        # Persist the result across requests and backend restarts. The namespace
        # follows the active generation, and content revisions detect corrections.
        if hasattr(self.store, 'usage_revision'):
            scope = None if pool_ids is None else sorted(set(pool_ids))
            cache_key = 'gold/cache/' + hashlib.sha256(json.dumps(scope).encode()).hexdigest() + '.json'
            signature = [1, self.store.usage_revision(), self.analytics.threshold,
                         self.analytics.buffer_rate, scope]
            try:
                cached = json.loads(self.store.get_bytes(cache_key))
            except ClientError as exc:
                if exc.response['Error']['Code'] not in ('NoSuchKey', '404'):
                    raise
            else:
                if cached['signature'] == signature:
                    return AnalyticsSummary.model_validate(cached['summary'])
            summary = self._compute_analytics(pool_ids)
            self.store.put_json(cache_key, {'signature': signature,
                'summary': summary.model_dump(mode='json')})
            return summary
        return self._compute_analytics(pool_ids)

    def _compute_analytics(self, pool_ids: list[str] | None = None) -> AnalyticsSummary:
        if pool_tables.enabled(self.store):
            reference = pool_tables.reference(self.store)
            summary = (self.analytics.compute_table(self.store.delta.read(reference), pool_ids)
                       if reference else self.analytics.compute([], pool_ids))
        else:
            keys = self.store.list_keys("silver/usage/")
            with tempfile.TemporaryDirectory(prefix="sam-silver-") as directory:
                paths=[]
                for index,key in enumerate(keys):
                    path=Path(directory)/f"part-{index}.parquet"
                    path.write_bytes(self.store.get_bytes(key)); paths.append(str(path))
                summary=self.analytics.compute(paths) if pool_ids is None else self.analytics.compute(paths,pool_ids)
        if pool_ids is not None:
            return summary  # Never overwrite the shared Gold snapshot with a partial portfolio.
        # One self-describing Gold record; nested DTOs are serialized for broad Parquet compatibility.
        self.put_table("gold/analytics/latest.parquet", [{
            "generated_at": summary.generated_at.isoformat(), "total_capacity": summary.total_capacity,
            "total_used": summary.total_used, "total_available": summary.total_available,
            "utilization_rate": summary.utilization_rate, "pools_at_risk": summary.pools_at_risk,
            "pools_total": summary.pools_total, "recovery_potential": summary.recovery_potential,
            "trends_json": json.dumps([x.model_dump(mode="json") for x in summary.trends]),
            "inactive_json": json.dumps([x.model_dump(mode="json") for x in summary.inactive]),
            "risks_json": json.dumps([x.model_dump(mode="json") for x in summary.risks])}])
        if summary.trends:
            self.put_table("gold/trends/latest.parquet", [
                t.model_dump(mode="json", exclude={"daily"}) for t in summary.trends])
            self.put_table("gold/daily/latest.parquet", [
                {"license_pool_id": t.license_pool_id, "software_name": t.software_name, **point}
                for t in summary.trends for point in t.daily])
        return summary
