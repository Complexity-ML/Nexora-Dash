from threading import Event
from test_collection_runner import context
from app.collection.worker_monitor import WorkerMonitor
from test_collection_status import status


def test_presence_reports_lifecycle_and_silence_without_claiming_progress(context):
    pipeline, journal = context
    monitor = WorkerMonitor(journal.store, pipeline.store.prefix, 'digimon-mock', 'group', Event()).start()
    try:
        monitor.begin()
        first = status(context)['recovery_worker']
        assert first['state'] == 'working' and not first['silent']
        assert first['pass_finished_at'] is None
        with journal.store.connect() as db:
            db.execute("UPDATE recovery_workers SET heartbeat_at=clock_timestamp()-interval '100 seconds' WHERE id=%s", (monitor.id,))
        assert status(context)['recovery_worker']['silent']
        monitor.beat()
        assert not status(context)['recovery_worker']['silent']
        assert status(context)['recovery_worker']['pass_finished_at'] is None
        monitor.report({'status': 'attention', 'next_pass_seconds': 300})
        waiting = status(context)['recovery_worker']
        assert waiting['state'] == 'waiting' and waiting['last_outcome'] == 'attention'
        assert waiting['pass_finished_at'] and waiting['next_pass_at']
        assert status(context, scope='other')['recovery_worker'] is None
    finally:
        monitor.close()
    stopped = status(context)['recovery_worker']
    assert stopped['state'] == 'stopped' and stopped['next_pass_at'] is None


def test_worker_failure_remains_visible(context):
    pipeline, journal = context
    monitor = WorkerMonitor(journal.store, pipeline.store.prefix, 'digimon-mock', 'group', Event()).start()
    monitor.close(failed=True)
    assert status(context)['recovery_worker']['state'] == 'failed'


def test_presence_failure_requests_shutdown():
    from types import SimpleNamespace
    stop = Event()
    monitor = WorkerMonitor(None, 'test', 'test', 'test', stop)
    monitor.done = SimpleNamespace(wait=lambda _: False)
    def unavailable():
        raise RuntimeError('unavailable')
    monitor.beat = unavailable
    monitor._heartbeat()
    assert stop.is_set() and monitor.failed.is_set()


def test_required_worker_detects_absence_and_clean_stop(context):
    assert status(context, require_worker=True)['recovery_workers']['missing_required']
    assert not status(context)['recovery_workers']['missing_required']
    pipeline, journal = context
    monitor = WorkerMonitor(journal.store, pipeline.store.prefix, 'digimon-mock', 'group', Event()).start()
    try:
        assert not status(context, require_worker=True)['recovery_workers']['missing_required']
    finally:
        monitor.close()
    assert status(context, require_worker=True)['recovery_workers']['missing_required']


def test_stopped_new_instance_does_not_hide_older_silent_worker(context):
    pipeline, journal = context
    first = WorkerMonitor(journal.store, pipeline.store.prefix, 'digimon-mock', 'group', Event()).start()
    second = WorkerMonitor(journal.store, pipeline.store.prefix, 'digimon-mock', 'group', Event()).start()
    try:
        second.close()
        with journal.store.connect() as db:
            db.execute("UPDATE recovery_workers SET heartbeat_at=clock_timestamp()-interval '100 seconds' WHERE id=%s", (first.id,))
        result = status(context, require_worker=True)
        assert result['recovery_worker']['state'] == 'stopped'
        assert result['recovery_workers']['silent'] == 1
        assert result['recovery_workers']['missing_required']
        first.beat()
        assert status(context, require_worker=True)['recovery_workers']['responsive'] == 1
        assert status(context, scope='other')['recovery_workers']['active'] == 0
    finally:
        first.close()
        second.close()


def test_fresh_heartbeat_does_not_hide_missed_scheduled_pass(context):
    pipeline, journal = context
    monitor = WorkerMonitor(journal.store, pipeline.store.prefix, 'digimon-mock', 'group', Event()).start()
    try:
        monitor.report({'status': 'ok', 'next_pass_seconds': 300})
        with journal.store.connect() as db:
            db.execute("UPDATE recovery_workers SET next_pass_at=clock_timestamp()-interval '100 seconds' WHERE id=%s", (monitor.id,))
        monitor.beat()
        workers = status(context, require_worker=True)['recovery_workers']
        assert workers['silent'] == 0 and workers['overdue'] == 1 and workers['missing_required']
        monitor.begin()
        assert status(context, require_worker=True)['recovery_workers']['responsive'] == 1
    finally:
        monitor.close()


def test_worker_requirement_controls_alert_with_complete_published_history(context):
    from test_collection_runner import collect
    from app.collection.runner import CollectionRunner
    pipeline, journal = context
    for day in (1, 2, 3):
        collect(CollectionRunner(pipeline, journal), day=day)
    assert not status(context)['needs_attention']
    assert status(context, require_worker=True)['needs_attention']
    monitor = WorkerMonitor(journal.store, pipeline.store.prefix, 'digimon-mock', 'group', Event()).start()
    try:
        assert not status(context, require_worker=True)['needs_attention']
    finally:
        monitor.close()
    assert status(context, require_worker=True)['needs_attention']
    assert not status(context)['needs_attention']


def test_daily_and_recovery_requirements_are_independent(context):
    pipeline,journal=context
    recovery=WorkerMonitor(journal.store,pipeline.store.prefix,'digimon-mock','group',Event()).start()
    daily=WorkerMonitor(journal.store,pipeline.store.prefix,'digimon-mock','group',Event(),kind='daily')
    try:
        result=status(context,require_worker=True,require_daily_worker=True)
        assert not result['recovery_workers']['missing_required']
        assert result['daily_workers']['missing_required']
        daily.start()
        result=status(context,require_worker=True,require_daily_worker=True)
        assert not result['daily_workers']['missing_required']
        assert result['daily_workers']['active'] == result['recovery_workers']['active'] == 1
        with journal.store.connect() as db:
            db.execute("UPDATE recovery_workers SET heartbeat_at=clock_timestamp()-interval '100 seconds' WHERE id=%s",(daily.id,))
        result=status(context,require_worker=True,require_daily_worker=True)
        assert result['daily_workers']['silent'] == 1
        assert result['daily_workers']['missing_required']
        assert not result['recovery_workers']['missing_required']
        assert result['needs_attention']
        daily.beat()
        daily.report({'status':'ok','next_pass_seconds':300})
        with journal.store.connect() as db:
            db.execute("UPDATE recovery_workers SET next_pass_at=clock_timestamp()-interval '100 seconds' WHERE id=%s",(daily.id,))
        result=status(context,require_daily_worker=True)
        assert result['daily_workers']['overdue'] == 1
        assert result['daily_workers']['responsive'] == 0
        assert result['daily_worker']['pass_finished_at']
    finally:
        recovery.close()
        daily.close()
    assert status(context,require_daily_worker=True)['daily_workers']['missing_required']
