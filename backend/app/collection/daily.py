"""Bounded daily batch over an explicit source availability contract.

Adapters return a ready, complete snapshot for a requested business day or None.
The real DIGIMON adapter must supply this contract; timestamp alone is not readiness.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol
from app.collection.runner import CollectionRunner
from app.collection.journal import Conflict
from app.collection.quality import CoverageRejected
from app.collection.polls import DailyPolls


@dataclass(frozen=True)
class ReadySnapshot:
    day: date
    snapshot_id: str
    revision: str
    payload: dict


class DailySource(Protocol):
    def ready_snapshot(self, day: date) -> ReadySnapshot | None: ...


def collect_days(pipeline, journal, adapter: DailySource, *, source, scope, start, end, stop_requested=None):
    if end < start or (end - start).days >= 366:
        raise ValueError('Collect an ordered window of at most 366 days')
    results = []
    polls = DailyPolls(journal.store, pipeline.store.prefix, source, scope)
    # Re-query already published days in the window: they may have new revisions.
    for offset in range((end - start).days + 1):
        if stop_requested is not None and stop_requested():
            break
        day = start + timedelta(days=offset)
        result = {'day': day.isoformat()}
        attempt = polls.begin(day)
        runner = None
        try:
            ready = adapter.ready_snapshot(day)
            if ready is None:
                result['status'] = 'source_pending'
            else:
                if ready.day != day or not ready.snapshot_id.strip() or not ready.revision.strip():
                    raise ValueError('Invalid source readiness identity')
                runner = CollectionRunner(pipeline, journal)
                manifest = runner.run(ready.payload, source=source,
                    scope=scope, snapshot_id=ready.snapshot_id, source_revision=ready.revision, expected_day=day.isoformat())
                result.update(status='published', run_id=manifest['run_id'])
        except CoverageRejected:
            result['status'] = 'quality_rejected'
        except Conflict:
            # A concurrent worker or a changed identity requires a later pass/inspection.
            result['status'] = 'conflict'
        except Exception:
            result['status'] = 'failed'
        if runner is not None and runner.run_id is not None:
            result.setdefault('run_id', runner.run_id)
        polls.finish(day, attempt, result['status'], result.get('run_id'))
        results.append(result)
    return results
