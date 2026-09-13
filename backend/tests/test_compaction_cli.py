import json
from types import SimpleNamespace
import pytest
from test_collection_runner import context
from test_collection_compaction import fragmented
from scripts import compact_collection as cli
from app.collection.reader import PublishedCollection


def test_preview_does_not_write_then_apply_publishes(context, monkeypatch, capsys):
    lake, journal, _, key = fragmented(context)
    monkeypatch.setattr(cli, 'get_settings', lambda: SimpleNamespace(collection_enabled=True))
    monkeypatch.setattr(cli, 'get_pipeline', lambda: SimpleNamespace(store=lake, collection_journal=journal,
                        collection_source='digimon-mock', collection_scope='group'))
    monkeypatch.setattr('sys.argv', ['compact', '--day', '2026-01-01'])
    version = lake.delta.latest('silver/fragmented').version
    assert cli.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'preview' and report['table_files'] == 4 and not report['apply']
    assert lake.delta.latest('silver/fragmented').version == version
    assert PublishedCollection(lake, journal, 'digimon-mock', 'group').manifest_key == key
    monkeypatch.setattr('sys.argv', ['compact', '--day', '2026-01-01', '--apply'])
    assert cli.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report['status'] == 'published' and report['apply']
    assert PublishedCollection(lake, journal, 'digimon-mock', 'group').manifest_key == report['manifest_key']


def test_legacy_mode_never_opens_pipeline(monkeypatch):
    monkeypatch.setattr('sys.argv', ['compact', '--day', '2026-01-01', '--apply'])
    monkeypatch.setattr(cli, 'get_settings', lambda: SimpleNamespace(collection_enabled=False))
    monkeypatch.setattr(cli, 'get_pipeline', lambda: pytest.fail('unexpected access'))
    with pytest.raises(RuntimeError, match='activated'):
        cli.main()


def test_storage_failure_is_sanitized(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['compact', '--day', '2026-01-01'])
    monkeypatch.setattr(cli, 'get_settings', lambda: SimpleNamespace(collection_enabled=True))
    def fail():
        raise RuntimeError('postgresql://private:secret@host/db')
    monkeypatch.setattr(cli, 'get_pipeline', fail)
    assert cli.main() == 1
    assert json.loads(capsys.readouterr().out) == {'status':'failed', 'error_code':'COMPACTION_FAILED'}
