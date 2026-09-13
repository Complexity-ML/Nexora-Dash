"""Periodic availability polling; the adapter owns the source readiness contract."""
from datetime import date, datetime, timedelta
from app.collection.polls import DailyPolls
from app.collection.daily import collect_days
from app.collection.worker import run_worker


def run_daily_worker(pipeline, journal, adapter, stop, emit, *, source, scope,
                     clock, lookback_days=7, interval=300, max_interval=3600,
                     history_start=None, catchup_limit=10, before_pass=None):
    """Poll today and recent days in the explicitly supplied business clock zone.

    Readiness (including today's publication) belongs to the adapter. Historical
    gaps outside this rolling window are revisited when history_start is set.
    """
    if isinstance(lookback_days, bool) or not isinstance(lookback_days, int) or not 1 <= lookback_days <= 366:
        raise ValueError('Expected 1..366 lookback days')

    if history_start is not None and type(history_start) is not date:
        raise ValueError("history_start must be a date")
    if type(catchup_limit) is not int or not 1 <= catchup_limit <= 100:
        raise ValueError("Expected 1..100 catchup limit")

    def poll():
        if before_pass is not None:
            before_pass()
        now = clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError('Daily collection clock requires an explicit timezone')
        end = now.date()
        start = end-timedelta(days=lookback_days-1)
        if history_start is not None and (history_start > end or (end-history_start).days >= 3660):
            raise ValueError('Expected history_start within the last 3660 days')
        results = collect_days(pipeline, journal, adapter, source=source, scope=scope,
                               start=max(start, history_start) if history_start else start, end=end,
                               stop_requested=stop.is_set)
        if history_start is not None and history_start < start and not stop.is_set():
            polls = DailyPolls(journal.store, pipeline.store.prefix, source, scope)
            for day in polls.catchup_days(history_start, start-timedelta(days=1), catchup_limit):
                if stop.is_set():
                    break
                results.extend(collect_days(pipeline, journal, adapter, source=source, scope=scope,
                                            start=day, end=day, stop_requested=stop.is_set))
        return results

    run_worker(poll, stop, emit, interval=interval, max_interval=max_interval,
               success_statuses=('published', 'source_pending'), error_code='DAILY_COLLECTION_PASS_FAILED')


def run_supervised_daily_worker(pipeline, journal, adapter, stop, emit, *, source, scope, **options):
    """Record daily presence and stop accepting work when monitoring fails."""
    from app.collection.worker_monitor import WorkerMonitor
    monitor = WorkerMonitor(journal.store, pipeline.store.prefix, source, scope, stop, kind='daily')
    failed = True
    try:
        monitor.start()
        def report(value):
            monitor.report(value)
            emit(value)
        run_daily_worker(pipeline, journal, adapter, stop, report, source=source, scope=scope,
                         before_pass=monitor.begin, **options)
        failed = monitor.failed.is_set()
    finally:
        monitor.close(failed=failed)
    return not failed
