"""Latest availability attempt per day; not a publication pointer or worker lease."""


class DailyPolls:
    def __init__(self, store, namespace, source, scope):
        self.store, self.stream = store, (namespace, source, scope)

    def begin(self, day):
        with self.store.connect() as db:
            return db.execute('''INSERT INTO daily_collection_polls(namespace,source,scope,day,status)
                VALUES (%s,%s,%s,%s,'fetching') ON CONFLICT(namespace,source,scope,day)
                DO UPDATE SET attempt=daily_collection_polls.attempt+1,status='fetching',
                started_at=clock_timestamp(),finished_at=NULL,run_id=NULL RETURNING attempt''',
                (*self.stream,day)).fetchone()['attempt']

    def finish(self, day, attempt, status, run_id=None):
        if status not in ('source_pending','published','quality_rejected','conflict','failed'):
            raise ValueError('Invalid poll outcome')
        with self.store.connect() as db:
            # A late HTTP response must not replace a newer attempt's diagnostic.
            return db.execute('''UPDATE daily_collection_polls SET status=%s,run_id=%s,finished_at=clock_timestamp()
                WHERE namespace=%s AND source=%s AND scope=%s AND day=%s AND attempt=%s AND status='fetching'
                RETURNING attempt''', (status,run_id,*self.stream,day,attempt)).fetchone() is not None

    def catchup_days(self, start, end, limit=10):
        """Revisit least recently attempted days, including absent and pending days.

        Selection is not a lease: concurrent collectors may select the same day;
        the journal still controls execution and publication.
        """
        if not 1 <= limit <= 100 or end < start or (end-start).days >= 3660:
            raise ValueError('Expected at most 3660 historical days and a limit of 1..100')
        with self.store.connect() as db:
            rows = db.execute("""SELECT (%s::date + n)::date AS day
                FROM generate_series(0, %s::date - %s::date) AS n
                LEFT JOIN daily_collection_polls p ON p.namespace=%s AND p.source=%s
                    AND p.scope=%s AND p.day=(%s::date + n)
                ORDER BY p.started_at ASC NULLS FIRST, n ASC LIMIT %s""",
                (start, end, start, *self.stream, start, limit)).fetchall()
        return [r['day'] for r in rows]
