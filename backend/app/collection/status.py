"""Read-only operational status from committed manifests and collection journal."""
from datetime import timedelta
from psycopg.types.json import Jsonb
from app.collection.reader import PublishedCollection


def collection_status(lake, journal, *, source, scope, start, end, limit=100, require_worker=False, require_daily_worker=False, quality_limit=100, poll_timeout_seconds=3600):
    if end < start or (end - start).days >= 3660 or not 1 <= limit <= 1000 or not 1 <= quality_limit <= 1000:
        raise ValueError('Use an ordered window of at most 3660 days and a bounded issue limit')
    if type(poll_timeout_seconds) is not int or not 1 <= poll_timeout_seconds <= 604800:
        raise ValueError('Expected a poll attention threshold of 1..604800 seconds')
    reader = PublishedCollection(lake, journal, source, scope)
    observed = set(reader.manifest['daily']) if reader.manifest else set()
    expected = [(start + timedelta(days=i)).isoformat() for i in range((end-start).days+1)]
    missing = [day for day in expected if day not in observed]
    stream = (lake.prefix, source, scope)
    current_bronze = {day: item.get('bronze', {}).get('key')
                      for day, item in (reader.manifest or {}).get('daily', {}).items()}
    resolved = """r.state='rejected' AND r.error_code='COVERAGE_DECREASE' AND EXISTS (
        SELECT 1 FROM collection_runs corrected
        JOIN collection_steps bronze ON bronze.run_id=corrected.id AND bronze.stage='bronze'
        WHERE corrected.namespace=r.namespace AND corrected.source=r.source AND corrected.scope=r.scope
          AND corrected.snapshot_id=r.snapshot_id AND corrected.state='published'
          AND corrected.created_at > r.created_at
          AND bronze.artifact->>'key' = (%s::jsonb)->>(s.artifact->>'day'))"""
    with journal.store.connect() as db:
        counts = db.execute("""SELECT state,count(*) AS count FROM collection_runs
            WHERE namespace=%s AND source=%s AND scope=%s GROUP BY state""", stream).fetchall()
        expired = db.execute("""SELECT count(*) AS count FROM collection_runs
            WHERE namespace=%s AND source=%s AND scope=%s
            AND state='running' AND lease_until <= clock_timestamp()""", stream).fetchone()['count']
        resolved_count = db.execute("""SELECT count(*) AS count FROM collection_runs r
            LEFT JOIN collection_steps s ON s.run_id=r.id AND s.stage='validated'
            WHERE r.namespace=%s AND r.source=%s AND r.scope=%s AND (""" + resolved + ')',
            (*stream, Jsonb(current_bronze))).fetchone()['count']
        rows = db.execute("""SELECT r.id,r.state,r.error_code,
            r.state='running' AND r.lease_until <= clock_timestamp() AS lease_expired,
            CASE WHEN s.artifact->'quality' IS NULL THEN NULL ELSE jsonb_build_object(
                'accepted', s.artifact->'quality'->'accepted',
                'baseline_available', s.artifact->'quality'->'baseline_available',
                'policy', jsonb_build_object('minimum_retained_fraction',
                    s.artifact->'quality'->'policy'->'minimum_retained_fraction'),
                'minimum_counts_total', (SELECT count(*) FROM jsonb_object_keys(
                    COALESCE(s.artifact->'quality'->'policy'->'minimum_counts','{}'::jsonb))),
                'decreases_total', jsonb_array_length(COALESCE(s.artifact->'quality'->'decreases','[]'::jsonb)),
                'shortfalls_total', jsonb_array_length(COALESCE(s.artifact->'quality'->'shortfalls','[]'::jsonb)),
                'decreases', COALESCE((SELECT jsonb_agg(value ORDER BY ordinal) FROM (
                    SELECT value,ordinal FROM jsonb_array_elements(s.artifact->'quality'->'decreases')
                        WITH ORDINALITY AS d(value,ordinal) ORDER BY ordinal LIMIT %s) bounded), '[]'::jsonb),
                'shortfalls', COALESCE((SELECT jsonb_agg(value ORDER BY ordinal) FROM (
                    SELECT value,ordinal FROM jsonb_array_elements(s.artifact->'quality'->'shortfalls')
                        WITH ORDINALITY AS d(value,ordinal) ORDER BY ordinal LIMIT %s) bounded), '[]'::jsonb)
            ) END AS quality
            FROM collection_runs r LEFT JOIN collection_steps s ON s.run_id=r.id AND s.stage='validated'
            WHERE r.namespace=%s AND r.source=%s AND r.scope=%s
            AND (r.state IN ('rejected','retryable') OR (r.state='running' AND r.lease_until <= clock_timestamp()))
            AND NOT (""" + resolved + """)
            ORDER BY r.created_at DESC,r.id LIMIT %s""", (quality_limit, quality_limit, *stream, Jsonb(current_bronze), limit)).fetchall()
        poll_cte = """WITH attempts AS (
            SELECT p.*,p.status AS attempt_status,r.state AS run_state,
                CASE WHEN p.status IN ('failed','conflict') AND r.state='published'
                     THEN 'recovered'
                     WHEN p.status='fetching' AND p.started_at < clock_timestamp()-(%s * interval '1 second')
                     THEN 'overdue' ELSE p.status END AS effective_status
            FROM daily_collection_polls p LEFT JOIN collection_runs r ON r.id=p.run_id
            WHERE p.namespace=%s AND p.source=%s AND p.scope=%s AND p.day BETWEEN %s AND %s)
            """
        poll_counts = db.execute(poll_cte +
            'SELECT effective_status AS status,count(*) AS count FROM attempts GROUP BY effective_status',
            (poll_timeout_seconds, *stream, start, end)).fetchall()
        polls = db.execute(poll_cte + """SELECT day,attempt,effective_status AS status,attempt_status,
            run_state,started_at,finished_at,run_id FROM attempts ORDER BY day DESC LIMIT %s""",
            (poll_timeout_seconds, *stream, start, end, limit)).fetchall()
        worker, workers, worker_alert = worker_status(db, stream, 'recovery', require_worker)
        daily_worker, daily_workers, daily_alert = worker_status(db, stream, 'daily', require_daily_worker)
    for row in rows:
        quality = row['quality']
        if quality is not None:
            quality['decreases_truncated'] = quality['decreases_total'] > len(quality['decreases'])
            quality['shortfalls_truncated'] = quality['shortfalls_total'] > len(quality['shortfalls'])
    for poll in polls:
        for key in ('day', 'started_at', 'finished_at'):
            poll[key] = poll[key].isoformat() if poll[key] else None
    poll_states = {row['status']: row['count'] for row in poll_counts}
    poll_failure = any(poll_states.get(state, 0) for state in ('failed', 'conflict', 'quality_rejected', 'overdue'))
    by_state = {row['state']: row['count'] for row in counts}
    issues_total = by_state.get('rejected', 0) + by_state.get('retryable', 0) + expired - resolved_count
    return {'source': source, 'scope': scope,
            'published_run': reader.manifest['run_id'] if reader.manifest else None,
            'window': {'from': start.isoformat(), 'through': end.isoformat()},
            'expected_days': len(expected), 'observed_days': len(expected)-len(missing),
            'missing_days': missing, 'runs_by_state': by_state, 'expired_leases': expired,
            'resolved_quality_rejections': resolved_count, 'issues': rows, 'issues_total': issues_total, 'issues_truncated': issues_total > len(rows),
            'polls': polls, 'polls_by_status': poll_states, 'poll_timeout_seconds': poll_timeout_seconds,
            'polls_truncated': sum(poll_states.values()) > len(polls),
            'recovery_worker': worker, 'recovery_workers': workers,
            'daily_worker': daily_worker, 'daily_workers': daily_workers,
            'needs_attention': bool(missing or issues_total or worker_alert or daily_alert or poll_failure)}


def worker_status(db, stream, kind, required=False):
    workers = db.execute("""WITH active AS (
        SELECT heartbeat_at < clock_timestamp()-interval '90 seconds' AS silent,
            state='waiting' AND (next_pass_at IS NULL OR
                next_pass_at < clock_timestamp()-interval '90 seconds') AS overdue
        FROM recovery_workers WHERE namespace=%s AND source=%s AND scope=%s AND kind=%s
            AND state IN ('working','waiting'))
        SELECT count(*) AS active,
            count(*) FILTER (WHERE silent) AS silent,
            count(*) FILTER (WHERE overdue) AS overdue,
            count(*) FILTER (WHERE NOT silent AND NOT overdue) AS responsive
        FROM active""", (*stream, kind)).fetchone()
    worker = db.execute("""SELECT id,state,last_outcome,heartbeat_at,pass_started_at,
        pass_finished_at,next_pass_at,heartbeat_at < clock_timestamp()-interval '90 seconds' AS silent
        FROM recovery_workers WHERE namespace=%s AND source=%s AND scope=%s AND kind=%s
        ORDER BY started_at DESC,id DESC LIMIT 1""", (*stream, kind)).fetchone()
    if worker:
        worker['silent'] = worker['silent'] and worker['state'] in ('working', 'waiting')
        for key in ('heartbeat_at', 'pass_started_at', 'pass_finished_at', 'next_pass_at'):
            worker[key] = worker[key].isoformat() if worker[key] else None
    workers['required'] = required
    workers['missing_required'] = required and workers['responsive'] == 0
    worker_alert = bool(workers['silent'] or workers['overdue'] or workers['missing_required'] or
                        (worker and worker['state'] == 'failed' and workers['responsive'] == 0))
    return worker, workers, worker_alert
