from datetime import date, datetime, timezone
from test_collection_runner import context
from app.collection.daily import ReadySnapshot, collect_days
from app.collection.reader import PublishedCollection
from app.connectors.demo import snapshot
import pytest


class Source:
    def __init__(self):
        self.pending = {2}
        self.revision = '1'
        self.used = None

    def ready_snapshot(self, day):
        if day.day in self.pending:
            return None
        raw = snapshot(datetime(day.year, day.month, day.day, tzinfo=timezone.utc))
        if self.used is not None and day.day == 1:
            raw['pools'][0]['consumed'] = self.used
        return ReadySnapshot(day, day.isoformat(), self.revision if day.day == 1 else '1', raw)


def batch(context, source):
    pipeline, journal = context
    return collect_days(pipeline, journal, source, source='digimon-mock', scope='group',
                        start=date(2026,1,1), end=date(2026,1,3))


def test_delayed_day_is_collected_later_without_duplicates(context):
    source = Source()
    first = batch(context, source)
    assert [row['status'] for row in first] == ['published', 'source_pending', 'published']
    pipeline, journal = context
    assert PublishedCollection(pipeline.store, journal, 'digimon-mock', 'group').usage().num_rows == 24
    source.pending.clear()
    second = batch(context, source)
    assert second[0]['run_id'] == first[0]['run_id'] and second[2]['run_id'] == first[2]['run_id']
    assert PublishedCollection(pipeline.store, journal, 'digimon-mock', 'group').usage().num_rows == 36
    third = batch(context, source)
    assert third == second


def test_batch_applies_source_correction_without_replacing_other_days(context):
    source = Source(); source.pending.clear()
    first = batch(context, source)
    source.revision = '2'; source.used = 7
    second = batch(context, source)
    assert second[0]['run_id'] != first[0]['run_id']
    pipeline, journal = context
    reader = PublishedCollection(pipeline.store, journal, 'digimon-mock', 'group')
    assert reader.usage().num_rows == 36
    rows = reader.usage().to_pylist()
    assert rows[0]['used'] == 7


def test_batch_rejects_wrong_day_before_publication(context):
    class Wrong(Source):
        def ready_snapshot(self, day):
            return super().ready_snapshot(date(2026,1,1))
    results = batch(context, Wrong())
    assert [r['status'] for r in results] == ['published', 'failed', 'failed']


def test_batch_window_is_bounded(context):
    pipeline, journal = context
    with pytest.raises(ValueError):
        collect_days(pipeline, journal, Source(), source='digimon-mock', scope='group',
                     start=date(2020,1,1), end=date(2026,1,1))


def test_payload_date_mismatch_is_archived_and_rejected(context):
    class WrongPayload(Source):
        def ready_snapshot(self, day):
            raw = snapshot(datetime(2025,1,1,tzinfo=timezone.utc))
            return ReadySnapshot(day, day.isoformat(), '1', raw)
    assert all(row['status'] == 'failed' for row in batch(context, WrongPayload()))
    pipeline, journal = context
    assert len(list(pipeline.store.root.glob('bronze/**/payload.json'))) == 3
    assert journal.head(pipeline.store.prefix, 'digimon-mock', 'group') is None


def test_naive_payload_timestamp_is_archived_without_publication(context):
    class Naive(Source):
        def ready_snapshot(self, day):
            raw = snapshot(datetime(day.year, day.month, day.day, tzinfo=timezone.utc))
            raw['capturedAt'] = day.isoformat() + 'T04:00:00'
            return ReadySnapshot(day, day.isoformat(), '1', raw)
    results = batch(context, Naive())
    assert all(row['status'] == 'failed' for row in results)
    pipeline, journal = context
    for result in results:
        assert set(journal.checkpoints(result['run_id'])) == {'bronze'}
    assert journal.head(pipeline.store.prefix, 'digimon-mock', 'group') is None
    assert journal.recovery_candidates(pipeline.store.prefix, 'digimon-mock', 'group') == []
