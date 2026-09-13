"""Periodic recovery; wait after each pass, never overlap work in one process."""


def run_worker(recover, stop, emit, *, interval=300, max_interval=3600,
               success_statuses=("published", "busy_or_superseded"),
               error_code="RECOVERY_PASS_FAILED"):
    if not 1 <= interval <= max_interval <= 86400:
        raise ValueError('Expected 1 <= interval <= max_interval <= 86400 seconds')
    delay = interval
    while not stop.is_set():
        try:
            results = recover()
            failed = any(row['status'] == 'failed' for row in results)
            attention = any(row['status'] not in success_statuses for row in results)
            report = {'status': 'retry' if failed else 'attention' if attention else 'ok', 'results': results}
        except Exception:
            # Raw storage/database exceptions may contain credentials or source data.
            failed = True
            report = {'status': 'retry', 'error_code': error_code}
        if not failed:
            delay = interval
        report['next_pass_seconds'] = delay
        emit(report)
        if stop.wait(delay):
            break
        delay = min(delay * 2, max_interval) if failed else interval
