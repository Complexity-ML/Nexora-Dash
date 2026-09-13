import json
import stat
import pytest
from test_collection_runner import context
from app.commands import issue_bi_reader as cli
from app.bi.auth import authenticate_reader, BIUnauthorized


def test_private_file_contains_scoped_credential_without_stdout(context, tmp_path, capsys):
    pipeline, journal = context
    path = tmp_path / 'reader.json'
    result = cli.provision(journal.store, namespace=pipeline.store.prefix,
                           audience='finance', output=path)
    secret = json.loads(path.read_text())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert 'token' not in result and secret['id'] == result['id']
    assert authenticate_reader(journal.store, namespace=pipeline.store.prefix,
                               token=secret['token'])['audience'] == 'finance'
    with pytest.raises(BIUnauthorized):
        authenticate_reader(journal.store, namespace='another', token=secret['token'])
    assert capsys.readouterr().out == ''
    with pytest.raises(FileExistsError):
        cli.provision(journal.store, namespace=pipeline.store.prefix, audience='finance', output=path)
    assert json.loads(path.read_text()) == secret


@pytest.mark.parametrize('failure_call', [1, 2])
def test_failed_delivery_rolls_back_reader(context, tmp_path, monkeypatch, failure_call):
    pipeline, journal = context
    path = tmp_path / 'reader.json'
    calls = 0
    sync = cli.os.fsync
    def failed_sync(fd):
        nonlocal calls
        calls += 1
        if calls == failure_call:
            raise OSError('disk failure')
        sync(fd)
    monkeypatch.setattr(cli.os, 'fsync', failed_sync)
    with pytest.raises(OSError):
        cli.provision(journal.store, namespace=pipeline.store.prefix, audience='finance', output=path)
    secret = json.loads(path.read_text())
    with journal.store.connect() as db:
        assert db.execute('SELECT id FROM bi_readers WHERE id=%s', (secret['id'],)).fetchone() is None
    with pytest.raises(BIUnauthorized):
        authenticate_reader(journal.store, namespace=pipeline.store.prefix, token=secret['token'])


def test_cli_sanitizes_failure(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['issue', '--root', '--audience', 'finance', '--output', '/unused'])
    def failure(*args, **kwargs):
        raise RuntimeError('secret must not appear')
    monkeypatch.setattr(cli, 'provision', failure)
    assert cli.main() == 1
    output = capsys.readouterr()
    assert 'secret' not in output.out + output.err
    assert json.loads(output.out)['error_code'] == 'BI_PROVISIONING_FAILED'


def test_symlink_destination_never_issues_credential(tmp_path, monkeypatch):
    target = tmp_path / 'existing'
    target.write_text('unchanged')
    link = tmp_path / 'link'
    link.symlink_to(target)
    def unexpected(*args, **kwargs):
        pytest.fail('Credential must not be issued')
    monkeypatch.setattr(cli, 'issue_reader', unexpected)
    with pytest.raises(FileExistsError):
        cli.provision(None, namespace='', audience='finance', output=link)
    assert target.read_text() == 'unchanged'


def test_reader_is_not_visible_until_delivery_finishes(context):
    from app.bi.auth import issue_reader
    pipeline, journal = context
    def deliver(credential):
        with pytest.raises(BIUnauthorized):
            authenticate_reader(journal.store, namespace=pipeline.store.prefix, token=credential['token'])
    credential = issue_reader(journal.store, namespace=pipeline.store.prefix,
                              audience='finance', deliver=deliver)
    assert authenticate_reader(journal.store, namespace=pipeline.store.prefix, token=credential['token'])


def test_process_killed_after_delivery_cannot_activate_reader(context, tmp_path):
    import os
    import select
    import signal
    import subprocess
    import sys
    pipeline, journal = context
    path = tmp_path / 'interrupted.json'
    code = '''
import os, signal, stat
from app.commands import issue_bi_reader as cli
from app.business.store import BusinessStore
original = os.fsync
def pause_after_directory_sync(fd):
    original(fd)
    if stat.S_ISDIR(os.fstat(fd).st_mode):
        print('delivery-durable', flush=True)
        signal.pause()
cli.os.fsync = pause_after_directory_sync
cli.provision(BusinessStore(os.environ['BI_TEST_DATABASE']),
              namespace=os.environ['BI_TEST_NAMESPACE'], audience='finance',
              output=os.environ['BI_TEST_OUTPUT'])
'''
    process = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, env={**os.environ,
                               'BI_TEST_DATABASE':journal.store.url,
                               'BI_TEST_NAMESPACE':pipeline.store.prefix,
                               'BI_TEST_OUTPUT':str(path)})
    try:
        ready, _, _ = select.select([process.stdout], [], [], 15)
        assert ready, 'Provisioning never reached the delivery checkpoint'
        assert process.stdout.readline().strip() == 'delivery-durable'
        process.kill()
        assert process.wait(timeout=10) == -signal.SIGKILL
        secret = json.loads(path.read_text())
        with pytest.raises(BIUnauthorized):
            authenticate_reader(journal.store, namespace=pipeline.store.prefix, token=secret['token'])
        with journal.store.connect() as db:
            assert db.execute('SELECT id FROM bi_readers WHERE id=%s', (secret['id'],)).fetchone() is None
        fresh_path = tmp_path / 'replacement.json'
        cli.provision(journal.store, namespace=pipeline.store.prefix, audience='finance', output=fresh_path)
        fresh = json.loads(fresh_path.read_text())
        assert authenticate_reader(journal.store, namespace=pipeline.store.prefix, token=fresh['token'])
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        process.stdout.close()
