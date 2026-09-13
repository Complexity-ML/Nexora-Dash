from types import SimpleNamespace
import pytest
from devtools.demo import initialize_demo as seed


def test_existing_generation_is_never_reinitialized(monkeypatch):
    monkeypatch.setattr(seed.demo_service,'check_mode',lambda:None)
    monkeypatch.setattr(seed,'get_settings',lambda:SimpleNamespace(demo_accounts_enabled=True,collection_enabled=False))
    monkeypatch.setattr(seed.workspace_service,'get_business_store',lambda:object())
    monkeypatch.setattr(seed.demo_service,'generation',lambda _:dict(version=1,prefix='active/'))
    monkeypatch.setattr(seed,'get_pipeline',lambda:pytest.fail('Must not access lake'))
    with pytest.raises(RuntimeError,match='already exists'):seed.initialize()


def test_nonempty_lake_is_preserved(monkeypatch):
    monkeypatch.setattr(seed.demo_service,'check_mode',lambda:None)
    monkeypatch.setattr(seed,'get_settings',lambda:SimpleNamespace(demo_accounts_enabled=True,collection_enabled=False))
    monkeypatch.setattr(seed.workspace_service,'get_business_store',lambda:object())
    monkeypatch.setattr(seed.demo_service,'generation',lambda _:dict(version=0,prefix=''))
    monkeypatch.setattr(seed,'get_pipeline',lambda:SimpleNamespace(store=SimpleNamespace(list_keys=lambda _:['silver/existing'])))
    monkeypatch.setattr(seed.demo_service,'reset',lambda *a:pytest.fail('Must not publish'))
    with pytest.raises(RuntimeError,match='not empty'):seed.initialize()
