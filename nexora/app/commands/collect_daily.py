"""Supervised polling of an adapter's explicit daily readiness contract."""
import argparse
from datetime import date, datetime
import json
import signal
from threading import Event
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from app.config import get_settings
from app.dependencies import get_pipeline
from app.collection.daily_worker import run_supervised_daily_worker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timezone', required=True, help='Business timezone, e.g. Europe/Paris')
    parser.add_argument('--lookback-days', type=int, default=7, choices=range(1,367), metavar='1..366')
    parser.add_argument('--history-start', type=date.fromisoformat)
    parser.add_argument('--catchup-limit', type=int, default=10, choices=range(1,101), metavar='1..100')
    parser.add_argument('--interval', type=int, default=300)
    parser.add_argument('--max-interval', type=int, default=3600)
    parser.add_argument('--once', action='store_true', help='Finish one pass and exit')
    args = parser.parse_args()
    if not 1 <= args.interval <= args.max_interval <= 86400:
        parser.error('Expected 1 <= interval <= max-interval <= 86400')
    try:
        zone = ZoneInfo(args.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        parser.error('Unknown business timezone')
    today = datetime.now(zone).date()
    if args.history_start and not 0 <= (today-args.history_start).days < 3660:
        parser.error('history-start must be within the last 3660 days')
    if not get_settings().collection_enabled:
        print(json.dumps({'status':'disabled','error_code':'COLLECTION_NOT_ACTIVATED'}))
        return 1
    stop = Event()
    previous = {}
    last_outcome = 'ok'
    try:
        pipeline = get_pipeline()
        if not callable(getattr(pipeline.connector, 'ready_snapshot', None)):
            print(json.dumps({'status':'unavailable','error_code':'DAILY_READINESS_CONTRACT_REQUIRED'}))
            return 1
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous[sig] = signal.signal(sig, lambda *_: stop.set())
        def emit(report):
            nonlocal last_outcome
            last_outcome = report['status']
            print(json.dumps(report), flush=True)
            if args.once:
                stop.set()
        healthy = run_supervised_daily_worker(pipeline, pipeline.collection_journal,
            pipeline.connector, stop, emit, source=pipeline.collection_source, scope=pipeline.collection_scope,
            clock=lambda: datetime.now(zone), lookback_days=args.lookback_days,
            history_start=args.history_start, catchup_limit=args.catchup_limit,
            interval=args.interval, max_interval=args.max_interval)
        return 0 if healthy and last_outcome == 'ok' else 1
    except Exception:
        print(json.dumps({'status':'failed','error_code':'DAILY_SERVICE_FAILED'}))
        return 1
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    raise SystemExit(main())
