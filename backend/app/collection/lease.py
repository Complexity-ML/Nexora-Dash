"""Renew processing leases while CPU or storage work is in progress."""
from threading import Event, Thread
from app.collection.journal import LeaseLost


class LeaseHeartbeat:
    def __init__(self,journal,run_id,fence,seconds):
        self.journal,self.run_id,self.fence,self.seconds=journal,run_id,fence,seconds
        self.stopped=Event(); self.failed=Event()
        self.thread=Thread(target=self._run,name='collection-lease',daemon=True)

    def start(self):
        self.thread.start()
        return self

    def _run(self):
        while not self.stopped.wait(self.seconds/3):
            try:
                self.journal.renew(self.run_id,self.fence,self.seconds)
            except Exception:
                self.failed.set()
                return

    def check(self):
        if self.failed.is_set():
            raise LeaseLost('Collection lease renewal failed')

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=5)
