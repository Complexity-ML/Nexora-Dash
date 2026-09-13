"""Bounded recovery pass; safe to invoke again after a process interruption."""
import argparse
import json
import signal
from threading import Event
from app.collection.worker import run_worker
from app.collection.worker_monitor import WorkerMonitor
from app.config import get_settings
from app.dependencies import get_pipeline
from app.collection.recovery import recover_once


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=10, choices=range(1, 101), metavar='1..100')
    parser.add_argument('--watch', action='store_true', help='Repeat recovery until SIGTERM or SIGINT')
    parser.add_argument('--interval', type=int, default=300, help='Seconds between completed passes')
    parser.add_argument('--max-interval', type=int, default=3600, help='Maximum failure backoff in seconds')
    args = parser.parse_args()
    if not 1 <= args.interval <= args.max_interval <= 86400:
        parser.error('Expected 1 <= interval <= max-interval <= 86400 seconds')
    if not get_settings().collection_enabled:
        raise RuntimeError('Enable journaled collection only after validating the existing history import')
    pipeline = get_pipeline()
    stop = Event()
    def recover():
        return recover_once(pipeline, pipeline.collection_journal, source=pipeline.collection_source,
                            scope=pipeline.collection_scope, limit=args.limit, stop_requested=stop.is_set)
    if args.watch:
        previous = {sig: signal.signal(sig, lambda *_: stop.set()) for sig in (signal.SIGTERM, signal.SIGINT)}
        monitor = WorkerMonitor(pipeline.collection_journal.store, pipeline.store.prefix,
                                pipeline.collection_source, pipeline.collection_scope, stop)
        failed = True
        try:
            monitor.start()
            def monitored_recover():
                monitor.begin()
                return recover()
            def emit(report):
                monitor.report(report)
                print(json.dumps(report), flush=True)
            run_worker(monitored_recover, stop, emit, interval=args.interval, max_interval=args.max_interval)
            failed = monitor.failed.is_set()
        finally:
            try:
                monitor.close(failed=failed)
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)
        return 1 if failed else 0
    results = recover()
    print(json.dumps({'results': results}))
    return 1 if any(row['status'] not in ('published', 'busy_or_superseded') for row in results) else 0


if __name__ == '__main__':
    raise SystemExit(main())
