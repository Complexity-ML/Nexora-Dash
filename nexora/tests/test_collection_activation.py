from contextlib import contextmanager
from types import SimpleNamespace
import pytest
from app.business.errors import BusinessError as HTTPException
from app.config import Settings
from app.dependencies import get_pipeline


@pytest.mark.parametrize('existing', ['index','delta','parquet','empty','imported'])
def test_activation_requires_import_before_hiding_existing_history(monkeypatch,existing):
    settings=Settings(collection_enabled=True,database_url='test',sam_data_source='mock')
    monkeypatch.setattr('app.dependencies.get_settings',lambda:settings)
    monkeypatch.setattr('app.business.analysis_preferences.read_settings',lambda store:{'threshold':.35,'buffer':.1})
    class Store:
        def __init__(self,url): pass
        @contextmanager
        def connect(self): yield self
        def execute(self,sql,params=None):
            value={'prefix':'demo/'} if 'demo_generation' in sql else ({'run_id':'old'} if existing=='index' else None)
            return SimpleNamespace(fetchone=lambda:value)
    monkeypatch.setattr('app.business.store.BusinessStore',Store)
    lake=SimpleNamespace(prefix='demo/',list_keys=lambda prefix:['old.parquet'] if existing=='parquet' else [])
    monkeypatch.setattr('app.dependencies.S3ParquetStore',lambda *args:lake)
    monkeypatch.setattr('app.storage.pool_tables.reference',lambda store:'old-delta' if existing=='delta' else None)
    monkeypatch.setattr('app.collection.reader.PublishedCollection',lambda *args:SimpleNamespace(manifest={'run_id':'imported'} if existing=='imported' else None))
    if existing in ('empty','imported'):
        assert get_pipeline().store is lake
    else:
        with pytest.raises(HTTPException) as error: get_pipeline()
        assert error.value.status_code==503
