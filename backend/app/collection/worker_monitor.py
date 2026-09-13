"""Worker presence is not evidence that a collection has made progress."""
from threading import Event, Thread
from uuid import uuid4


class WorkerMonitor:
    def __init__(self, store, namespace, source, scope, stop, *, kind="recovery"):
        if kind not in ("recovery", "daily"):
            raise ValueError("Invalid worker kind")
        self.kind = kind
        self.store, self.stream, self.stop = store, (namespace, source, scope), stop
        self.id = str(uuid4())
        self.done = Event()
        self.failed = Event()
        self.thread = None

    def start(self):
        with self.store.connect() as db:
            db.execute("INSERT INTO recovery_workers(id,namespace,source,scope,kind,state) VALUES (%s,%s,%s,%s,%s,'working')",
                       (self.id, *self.stream, self.kind))
        self.thread = Thread(target=self._heartbeat, name='recovery-presence', daemon=True)
        self.thread.start()
        return self

    def beat(self):
        with self.store.connect() as db:
            db.execute("UPDATE recovery_workers SET heartbeat_at=clock_timestamp() WHERE id=%s AND state IN ('working','waiting')", (self.id,))

    def _heartbeat(self):
        while not self.done.wait(30):
            try:
                self.beat()
            except Exception:
                # Stop taking work if operational presence cannot be recorded.
                self.failed.set()
                self.stop.set()
                return

    def begin(self):
        with self.store.connect() as db:
            db.execute("""UPDATE recovery_workers SET state='working',pass_started_at=clock_timestamp(),
                next_pass_at=NULL,heartbeat_at=clock_timestamp() WHERE id=%s""", (self.id,))

    def report(self, report):
        outcome = report['status']
        delay = report['next_pass_seconds']
        if outcome not in ('ok', 'retry', 'attention') or not 1 <= delay <= 86400:
            raise ValueError('Invalid worker report')
        with self.store.connect() as db:
            db.execute("""UPDATE recovery_workers SET state='waiting',pass_finished_at=clock_timestamp(),
                heartbeat_at=clock_timestamp(),last_outcome=%s,
                next_pass_at=clock_timestamp()+(%s * interval '1 second') WHERE id=%s""",
                (outcome, delay, self.id))

    def close(self, failed=False):
        self.done.set()
        if self.thread is not None:
            self.thread.join(timeout=5)
        with self.store.connect() as db:
            db.execute("UPDATE recovery_workers SET state=%s,next_pass_at=NULL,heartbeat_at=clock_timestamp() WHERE id=%s",
                       ('failed' if failed else 'stopped', self.id))
