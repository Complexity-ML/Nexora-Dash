from datetime import date
from test_collection_runner import context, collect
from app.collection.runner import CollectionRunner
from app.collection.status import collection_status
import pytest


def status(context, scope='group', **kwargs):
    pipeline, journal = context
    return collection_status(pipeline.store, journal, source='digimon-mock', scope=scope,
                             start=date(2026,1,1), end=date(2026,1,3), **kwargs)


def test_status_reports_holes_without_filling_zero(context):
    pipeline, journal = context
    collect(CollectionRunner(pipeline, journal), day=1)
    collect(CollectionRunner(pipeline, journal), day=3)
    result = status(context)
    assert result['missing_days'] == ['2026-01-02']
    assert result['observed_days'] == 2 and result['needs_attention']
    assert result['issues'] == []
    assert status(context, scope='other')['observed_days'] == 0


def test_status_counts_expired_workers_and_bounds_details(context):
    pipeline, journal = context
    for sid in ('a', 'b'):
        run = journal.register(namespace=pipeline.store.prefix, source='digimon-mock', scope='group',
            snapshot_id=sid, source_revision='1', fingerprint='a'*64, mapping_version='1', schema_version='1')
        fence = journal.claim(run['id'], 'worker')
        with journal.store.connect() as db:
            db.execute("UPDATE collection_runs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (run['id'],))
    result = status(context, limit=1)
    assert result['expired_leases'] == 2 and result['issues_total'] == 2
    assert len(result['issues']) == 1 and result['issues_truncated']
    assert result['issues'][0]['lease_expired']
    assert 'fingerprint' not in result['issues'][0]


def test_status_rejects_unbounded_window(context):
    pipeline, journal = context
    with pytest.raises(ValueError):
        collection_status(pipeline.store, journal, source='digimon-mock', scope='group',
                          start=date(2000,1,1), end=date(2050,1,1))


def test_status_bounds_quality_dimensions_without_erasing_journal(context):
    from app.collection.quality import CoverageRejected
    pipeline, journal = context
    pipeline.collection_quality_policy = {'minimum_counts': {
        f'machines/subsidiary/missing-{i}': 10 for i in range(5)}}
    runner = CollectionRunner(pipeline, journal)
    with pytest.raises(CoverageRejected):
        collect(runner)
    result = status(context, quality_limit=2)
    quality = result['issues'][0]['quality']
    assert quality['shortfalls_total'] == 5
    assert len(quality['shortfalls']) == 2 and quality['shortfalls_truncated']
    assert quality['shortfalls'][0]['received'] == 0 and quality['shortfalls'][0]['minimum'] == 10
    assert quality['minimum_counts_total'] == 5
    assert 'minimum_counts' not in quality['policy']
    assert quality['decreases_total'] == 0 and not quality['decreases_truncated']
    assert result['needs_attention']
    full = journal.checkpoints(runner.run_id)['validated']['quality']
    assert len(full['shortfalls']) == 5 and len(full['policy']['minimum_counts']) == 5


def test_corrected_same_day_resolves_alert_but_preserves_rejected_run(context):
    from app.collection.quality import CoverageRejected
    pipeline, journal = context
    pipeline.collection_quality_policy = {'minimum_counts': {'machines':139}}
    rejected = CollectionRunner(pipeline, journal)
    with pytest.raises(CoverageRejected):
        collect(rejected)
    pipeline.collection_quality_policy = {}
    # Publishing another day must not hide the rejection.
    collect(CollectionRunner(pipeline, journal), day=2)
    assert status(context)['issues_total'] == 1
    from enterprise_fixture import snapshot
    from datetime import datetime, timezone
    CollectionRunner(pipeline, journal).run(snapshot(datetime(2026,1,1,tzinfo=timezone.utc)),
        source='digimon-mock', scope='group', snapshot_id='unrelated', source_revision='1')
    assert status(context)['issues_total'] == 1
    collect(CollectionRunner(pipeline, journal), day=1, revision='2')
    report = status(context)
    assert report['issues_total'] == 0 and report['issues'] == []
    assert report['resolved_quality_rejections'] == 1
    assert report['runs_by_state']['rejected'] == 1
    assert not journal.checkpoints(rejected.run_id)['validated']['quality']['accepted']


def test_unfinished_poll_alerts_even_when_day_is_already_published(context):
    from app.collection.polls import DailyPolls
    pipeline, journal = context
    for day in (1, 2, 3):
        collect(CollectionRunner(pipeline, journal), day=day)
    polls = DailyPolls(journal.store, pipeline.store.prefix, 'digimon-mock', 'group')
    attempt = polls.begin(date(2026,1,1))
    assert not status(context)['needs_attention']
    with journal.store.connect() as db:
        db.execute("UPDATE daily_collection_polls SET started_at=clock_timestamp()-interval '2 hours' WHERE namespace=%s", (pipeline.store.prefix,))
    report = status(context)
    assert report['missing_days'] == [] and report['needs_attention']
    assert report['polls_by_status'] == {'overdue':1}
    assert report['polls'][0]['attempt_status'] == 'fetching'
    assert not status(context, poll_timeout_seconds=10800)['needs_attention']
    assert polls.finish(date(2026,1,1), attempt, 'source_pending')
    assert not status(context)['needs_attention']
