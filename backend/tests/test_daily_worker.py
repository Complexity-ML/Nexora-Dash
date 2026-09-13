from datetime import datetime, timezone
import pytest
from test_collection_runner import context
from test_collection_daily import Source
from test_collection_worker import Stop
from app.collection.daily_worker import run_daily_worker
from app.collection.reader import PublishedCollection


def test_periodic_poll_collects_delayed_day_and_revision_without_duplicates(context):
    pipeline, journal = context
    adapter = Source()
    reports = []
    def emit(report):
        reports.append(report)
        adapter.pending.clear()
        adapter.revision = '2'
        adapter.used = 7
    run_daily_worker(pipeline, journal, adapter, Stop(3), emit, source='digimon-mock', scope='group',
                     clock=lambda: datetime(2026,1,3,tzinfo=timezone.utc), lookback_days=3, interval=1)
    assert reports[0]['results'][1]['status'] == 'source_pending'
    assert all(r['status'] == 'ok' for r in reports)
    assert reports[1]['results'] == reports[2]['results']
    reader = PublishedCollection(pipeline.store, journal, 'digimon-mock', 'group')
    assert reader.usage().num_rows == 36
    assert reader.usage().to_pylist()[0]['used'] == 7


def test_stop_during_day_finishes_it_without_polling_next(context):
    pipeline, journal = context
    stop = Stop(10)
    class Stopping(Source):
        def ready_snapshot(self, day):
            stop.stopped = True
            return super().ready_snapshot(day)
    reports = []
    run_daily_worker(pipeline, journal, Stopping(), stop, reports.append,
                     source='digimon-mock', scope='group',
                     clock=lambda: datetime(2026,1,3,tzinfo=timezone.utc), lookback_days=3)
    assert len(reports) == 1
    assert len(reports[0]['results']) == 1
    assert reports[0]['results'][0]['status'] == 'published'


def test_invalid_clock_never_contacts_source(context):
    class Unreachable:
        def ready_snapshot(self, day):
            pytest.fail('source must not be contacted')
    reports = []
    run_daily_worker(*context, Unreachable(), Stop(1), reports.append, source='test', scope='group',
                     clock=lambda: datetime(2026,1,1))
    assert reports[0]['error_code'] == 'DAILY_COLLECTION_PASS_FAILED'


def test_historical_rotation_survives_worker_restart_and_pending_day(context):
    from datetime import date
    pipeline, journal = context
    class Recording(Source):
        def __init__(self):
            super().__init__()
            self.pending = {1}
            self.calls = []
        def ready_snapshot(self, day):
            self.calls.append(day)
            return super().ready_snapshot(day)
    adapter = Recording()
    for _ in range(2):
        run_daily_worker(pipeline, journal, adapter, Stop(1), lambda _: None,
                         source='digimon-mock', scope='group',
                         clock=lambda: datetime(2026,1,5,tzinfo=timezone.utc), lookback_days=1,
                         history_start=date(2026,1,1), catchup_limit=1)
    assert adapter.calls == [date(2026,1,5), date(2026,1,1), date(2026,1,5), date(2026,1,2)]
    assert PublishedCollection(pipeline.store, journal, 'digimon-mock', 'group').usage().num_rows == 24
    adapter.pending.clear()
    run_daily_worker(pipeline, journal, adapter, Stop(3), lambda _: None,
                     source='digimon-mock', scope='group',
                     clock=lambda: datetime(2026,1,5,tzinfo=timezone.utc), lookback_days=1,
                     history_start=date(2026,1,1), catchup_limit=1)
    assert adapter.calls[-1] == date(2026,1,1)
    assert PublishedCollection(pipeline.store, journal, 'digimon-mock', 'group').usage().num_rows == 60


def test_daily_supervision_does_not_count_as_recovery_presence(context):
    from app.collection.daily_worker import run_supervised_daily_worker
    from test_collection_status import status
    pipeline,journal=context
    seen=[]
    def emit(report):
        with journal.store.connect() as db:
            row=db.execute("SELECT * FROM recovery_workers WHERE namespace=%s AND kind='daily'",(pipeline.store.prefix,)).fetchone()
        assert row['state'] == 'waiting' and row['pass_finished_at'] is not None
        assert status(context,require_worker=True)['recovery_workers']['missing_required']
        seen.append(report)
    assert run_supervised_daily_worker(pipeline,journal,Source(),Stop(1),emit,
        source='digimon-mock',scope='group',clock=lambda:datetime(2026,1,3,tzinfo=timezone.utc),lookback_days=1)
    assert seen[0]['status'] == 'ok'
    with journal.store.connect() as db:
        row=db.execute("SELECT state FROM recovery_workers WHERE namespace=%s AND kind='daily'",(pipeline.store.prefix,)).fetchone()
    assert row['state'] == 'stopped'


def test_daily_supervision_records_failed_exit(context):
    from app.collection.daily_worker import run_supervised_daily_worker
    pipeline,journal=context
    def broken_output(report):
        raise RuntimeError('output unavailable')
    with pytest.raises(RuntimeError,match='output unavailable'):
        run_supervised_daily_worker(pipeline,journal,Source(),Stop(1),broken_output,
            source='digimon-mock',scope='group',clock=lambda:datetime(2026,1,3,tzinfo=timezone.utc),lookback_days=1)
    with journal.store.connect() as db:
        row=db.execute("SELECT state,next_pass_at FROM recovery_workers WHERE namespace=%s AND kind='daily'",(pipeline.store.prefix,)).fetchone()
    assert row['state'] == 'failed' and row['next_pass_at'] is None
