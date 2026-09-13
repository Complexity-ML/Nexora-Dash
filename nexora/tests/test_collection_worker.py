import pytest
from app.collection.worker import run_worker


class Stop:
    def __init__(self, passes):
        self.passes = passes
        self.waits = []
        self.stopped = False
    def is_set(self):
        return self.stopped
    def wait(self, delay):
        self.waits.append(delay)
        return self.stopped or len(self.waits) >= self.passes


def test_worker_backs_off_caps_delay_and_resets_after_success():
    stop = Stop(6)
    reports = []
    outcomes = iter([RuntimeError('secret database URL'), [{'status': 'failed'}],
                     [{'status': 'failed'}], [{'status': 'failed'}], [], []])
    def recover():
        value = next(outcomes)
        if isinstance(value, Exception):
            raise value
        return value
    run_worker(recover, stop, reports.append, interval=2, max_interval=5)
    assert stop.waits == [2, 4, 5, 5, 2, 2]
    assert 'secret' not in str(reports)
    assert reports[0]['error_code'] == 'RECOVERY_PASS_FAILED'
    assert reports[-1]['status'] == 'ok'


def test_stop_during_pass_does_not_start_another_pass():
    stop = Stop(10)
    calls = []
    def recover():
        calls.append('completed')
        stop.stopped = True
        return [{'status': 'published'}]
    run_worker(recover, stop, lambda report: None)
    assert calls == ['completed']


def test_stopped_worker_does_not_read_storage():
    stop = Stop(1); stop.stopped = True
    run_worker(lambda: pytest.fail('unexpected pass'), stop, lambda _: None)


@pytest.mark.parametrize('interval,maximum', [(0, 5), (6, 5), (1, 86401)])
def test_invalid_worker_delays_fail_before_work(interval, maximum):
    with pytest.raises(ValueError):
        run_worker(lambda: pytest.fail('unexpected pass'), Stop(1), lambda _: None,
                   interval=interval, max_interval=maximum)


def test_operator_action_is_reported_without_delaying_other_candidates():
    reports = []
    stop = Stop(2)
    run_worker(lambda: [{'status': 'configuration_changed'}], stop, reports.append,
               interval=2, max_interval=10)
    assert [r['status'] for r in reports] == ['attention', 'attention']
    assert stop.waits == [2, 2]


@pytest.mark.parametrize('signal_name', ['SIGTERM', 'SIGINT'])
@pytest.mark.parametrize('phase', ['working', 'waiting'])
def test_cli_handles_real_signals_without_abandoning_current_pass(signal_name, phase):
    import json
    import select
    import signal
    import subprocess
    import sys
    from pathlib import Path
    # Exercise the real CLI and its signal handlers in a child process; no source or DB access.
    code = '''
import sys
import time
from types import SimpleNamespace
from scripts import recover_collections as cli
phase = sys.argv[-1]
cli.get_settings = lambda: SimpleNamespace(collection_enabled=True)
cli.get_pipeline = lambda: SimpleNamespace(collection_journal=SimpleNamespace(store=None), store=SimpleNamespace(prefix='test'), collection_source='test', collection_scope='test')
cli.WorkerMonitor = lambda *args: SimpleNamespace(failed=SimpleNamespace(is_set=lambda: False), start=lambda: None, begin=lambda: None, report=lambda report: None, close=lambda **kwargs: None)
def recover(*args, **kwargs):
    print('entered', flush=True)
    if phase == 'working':
        sys.stdin.readline()
        deadline = time.monotonic() + 5
        while not kwargs['stop_requested']() and time.monotonic() < deadline:
            time.sleep(.01)
        assert kwargs['stop_requested'](), 'signal did not request shutdown'
    return [{'status': 'published', 'run_id': 'completed'}]
cli.recover_once = recover
sys.argv = ['recover', '--watch', '--interval', '3600']
raise SystemExit(cli.main())
'''
    process = subprocess.Popen([sys.executable, '-u', '-c', code, phase],
        cwd=Path(__file__).parents[1], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
    try:
        assert select.select([process.stdout], [], [], 15)[0], 'worker did not enter a pass'
        assert process.stdout.readline().strip() == b'entered'
        report = None
        if phase == 'waiting':
            assert select.select([process.stdout], [], [], 15)[0], 'pass did not finish'
            report = json.loads(process.stdout.readline())
        process.send_signal(getattr(signal, signal_name))
        # Signal delivery can race stdin: the child waits for stop_requested before returning.
        stdout, stderr = process.communicate(input=b'continue\n', timeout=15)
        assert process.returncode == 0, stderr
        assert b'entered' not in stdout, 'worker started another pass after stop'
        report = report or json.loads(stdout)
        assert report['results'] == [{'status': 'published', 'run_id': 'completed'}]
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
