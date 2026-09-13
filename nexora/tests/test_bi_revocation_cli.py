import json
from types import SimpleNamespace
import pytest
from test_collection_runner import context
from app.bi.auth import issue_reader, authenticate_reader, BIUnauthorized
from app.commands import revoke_bi_reader as cli


def test_targeted_revocation_preserves_other_readers(context, monkeypatch, capsys):
    pipeline, journal = context
    namespace = pipeline.store.prefix
    old = issue_reader(journal.store, namespace=namespace, audience='finance')
    replacement = issue_reader(journal.store, namespace=namespace, audience='finance')
    monkeypatch.setattr(cli, 'get_settings', lambda:SimpleNamespace(database_url='test'))
    monkeypatch.setattr(cli, 'BusinessStore', lambda _:journal.store)
    def invoke(scope):
        monkeypatch.setattr('sys.argv', ['revoke', '--namespace', scope, '--reader-id', old['id']])
        return cli.main()
    assert invoke(namespace + 'other') == 1
    assert authenticate_reader(journal.store, namespace=namespace, token=old['token'])
    assert invoke(namespace) == 0
    assert invoke(namespace) == 0  # Repeating a completed revocation is safe.
    with pytest.raises(BIUnauthorized):
        authenticate_reader(journal.store, namespace=namespace, token=old['token'])
    assert authenticate_reader(journal.store, namespace=namespace, token=replacement['token'])
    output = capsys.readouterr().out
    assert old['token'] not in output and replacement['token'] not in output
    assert [json.loads(row)['status'] for row in output.splitlines()] == ['not_found','revoked','revoked']


def test_invalid_identity_never_opens_database(monkeypatch):
    monkeypatch.setattr('sys.argv', ['revoke', '--root', '--reader-id', 'invalid'])
    monkeypatch.setattr(cli, 'BusinessStore', lambda _:pytest.fail('Unexpected database access'))
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
