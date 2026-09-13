from datetime import date
import pytest
from test_collection_runner import context
from test_collection_daily import Source, batch
from test_collection_status import status
from app.collection.polls import DailyPolls


def test_delayed_day_and_retry_remain_visible(context):
    source = Source()
    batch(context, source)
    report = status(context)
    assert report['polls_by_status'] == {'published': 2, 'source_pending': 1}
    assert len(report['polls']) == 3
    assert report['polls'][1]['attempt'] == 1
    source.pending.clear()
    batch(context, source)
    report = status(context)
    assert report['polls_by_status'] == {'published': 3}
    assert all(row['attempt'] == 2 for row in report['polls'])
    assert report['missing_days'] == []
    assert status(context, scope='other')['polls'] == []
    assert status(context, limit=1)['polls_truncated']


def test_late_attempt_cannot_overwrite_newer_outcome(context):
    pipeline, journal = context
    polls = DailyPolls(journal.store, pipeline.store.prefix, 'digimon-mock', 'group')
    day = date(2026,1,1)
    first = polls.begin(day)
    second = polls.begin(day)
    assert polls.finish(day, second, 'source_pending')
    assert not polls.finish(day, first, 'failed')
    assert status(context)['polls_by_status'] == {'source_pending': 1}


def test_process_interruption_keeps_unfinished_attempt(context):
    class Interrupted(Source):
        def ready_snapshot(self, day):
            raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        batch(context, Interrupted())
    row = status(context)['polls'][0]
    assert row['status'] == 'fetching' and row['finished_at'] is None
    assert row['run_id'] is None


def test_successful_recovery_clears_failed_poll_alert_without_erasing_attempt(context, monkeypatch):
    from app.collection import daily
    from app.collection.runner import CollectionRunner
    from app.collection.recovery import recover_once
    def crash(stage):
        if stage == 'after_checkpoint_bronze':
            raise RuntimeError('interrupted after source received')
    monkeypatch.setattr(daily, 'CollectionRunner', lambda pipeline, journal: CollectionRunner(pipeline, journal, crash))
    source = Source(); source.pending.clear()
    results = batch(context, source)
    assert all(row['status'] == 'failed' and row['run_id'] for row in results)
    assert status(context)['needs_attention']
    pipeline, journal = context
    recovered = recover_once(pipeline, journal, source='digimon-mock', scope='group')
    assert len(recovered) == 3 and all(row['status'] == 'published' for row in recovered)
    report = status(context)
    assert not report['needs_attention']
    assert report['polls_by_status'] == {'recovered': 3}
    assert all(row['attempt_status'] == 'failed' and row['run_state'] == 'published' for row in report['polls'])


def test_failure_before_receiving_source_remains_an_alert(context):
    class Unavailable(Source):
        def ready_snapshot(self, day):
            raise RuntimeError('source unavailable')
    batch(context, Unavailable())
    report = status(context)
    assert report['needs_attention'] and report['polls_by_status'] == {'failed': 3}
    assert all(row['run_id'] is None for row in report['polls'])
