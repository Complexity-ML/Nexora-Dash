import json
from types import SimpleNamespace
import pytest
from test_collection_runner import context
from test_collection_daily import Source
from app.collection.reader import PublishedCollection
from scripts import collect_daily as cli


def setup(monkeypatch, pipeline):
    monkeypatch.setattr('sys.argv',['collect','--timezone','Europe/Paris','--lookback-days','1','--once'])
    monkeypatch.setattr(cli,'get_settings',lambda:SimpleNamespace(collection_enabled=True))
    monkeypatch.setattr(cli,'get_pipeline',lambda:pipeline)


def test_one_pass_repeated_without_duplicates(context,monkeypatch,capsys):
    pipeline,journal=context
    pipeline.connector=Source(); pipeline.connector.pending.clear()
    pipeline.collection_journal=journal
    pipeline.collection_source='digimon-mock'; pipeline.collection_scope='group'
    setup(monkeypatch,pipeline)
    assert cli.main() == 0
    first=json.loads(capsys.readouterr().out)
    assert first['status'] == 'ok'
    assert cli.main() == 0
    assert json.loads(capsys.readouterr().out)['results'] == first['results']
    assert PublishedCollection(pipeline.store,journal,'digimon-mock','group').usage().num_rows == 12
    with journal.store.connect() as db:
        rows=db.execute("SELECT state FROM recovery_workers WHERE namespace=%s AND kind='daily'",(pipeline.store.prefix,)).fetchall()
    assert len(rows) == 2 and all(r['state']=='stopped' for r in rows)


def test_absent_readiness_does_not_fetch_snapshot(monkeypatch,capsys):
    class Legacy:
        def get_raw_snapshot(self):
            pytest.fail('must not infer readiness')
    setup(monkeypatch,SimpleNamespace(connector=Legacy()))
    assert cli.main() == 1
    assert json.loads(capsys.readouterr().out)['error_code'] == 'DAILY_READINESS_CONTRACT_REQUIRED'


def test_disabled_does_not_open_pipeline(monkeypatch,capsys):
    setup(monkeypatch,None)
    monkeypatch.setattr(cli,'get_settings',lambda:SimpleNamespace(collection_enabled=False))
    monkeypatch.setattr(cli,'get_pipeline',lambda:pytest.fail('must not access lake'))
    assert cli.main() == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'disabled'


def test_startup_failure_is_sanitized(monkeypatch,capsys):
    setup(monkeypatch,None)
    def fail():
        raise RuntimeError('private storage credentials')
    monkeypatch.setattr(cli,'get_pipeline',fail)
    assert cli.main() == 1
    assert 'private' not in capsys.readouterr().out


def test_signal_finishes_current_day_and_restores_handlers(context,monkeypatch,capsys):
    import os
    import signal
    pipeline,journal=context
    class Stopping(Source):
        def ready_snapshot(self,day):
            os.kill(os.getpid(),signal.SIGTERM)
            return super().ready_snapshot(day)
    pipeline.connector=Stopping(); pipeline.connector.pending.clear()
    pipeline.collection_journal=journal
    pipeline.collection_source='digimon-mock'; pipeline.collection_scope='group'
    setup(monkeypatch,pipeline)
    monkeypatch.setattr('sys.argv',['collect','--timezone','Europe/Paris','--lookback-days','3'])
    before=signal.getsignal(signal.SIGTERM)
    assert cli.main() == 0
    assert signal.getsignal(signal.SIGTERM) == before
    report=json.loads(capsys.readouterr().out)
    assert len(report['results']) == 1 and report['results'][0]['status'] == 'published'
