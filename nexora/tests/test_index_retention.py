import pytest
from uuid import uuid4
from psycopg.types.json import Jsonb
from test_collection_runner import context
from app.business.index_retention import referenced_runs,prune_index_cache


def test_references_are_found_in_nested_recovery_metadata():
    assert referenced_runs([{'old':{'index_run':'a'}},['b']],{'a','b','c'})=={'a','b'}


def test_retention_keeps_active_and_archived_recovery_indexes(context):
    pipeline,journal=context[:2]
    lake=pipeline.store
    store=journal.store
    active, obsolete, recovery = (str(uuid4()) for _ in range(3))
    with store.connect() as db:
        for rid in (active,obsolete,recovery):
            db.execute('INSERT INTO inventory_runs VALUES (%s,%s,now(),%s,%s)',(rid,lake.prefix,'test','gold/'+rid+'.json'))
            db.execute("INSERT INTO inventory_entities(run_id,entity,id,name,pool_ids,search,data) VALUES (%s,'machines','m','Machine',ARRAY[]::text[],'machine','{}'::jsonb)",(rid,))
        db.execute('INSERT INTO inventory_heads VALUES (%s,%s)',(lake.prefix,active))
    run=journal.register(namespace=lake.prefix,source='test',scope='group',snapshot_id='r',source_revision='1',fingerprint='a'*64,mapping_version='1',schema_version='1')
    fence=journal.claim(run['id'],'test')
    with pytest.raises(RuntimeError,match='running'):prune_index_cache(store,lake)
    journal.fail(run['id'],fence,'TEST')
    lake.put_json('gold/recovery-reference.json',{'index_run':recovery})
    with store.connect() as db:
        db.execute('INSERT INTO collection_step_history(run_id,stage,artifact,fence,reason) VALUES (%s,%s,%s,%s,%s)',(run['id'],'gold',Jsonb({'manifest_key':'gold/recovery-reference.json'}),fence,'test'))
    plan=prune_index_cache(store,lake)
    assert plan['obsolete_runs']==[obsolete]
    assert plan['protected_runs']==sorted([active,recovery])
    assert not plan['applied'] and plan['projection_rows']==1
    applied=prune_index_cache(store,lake,apply=True)
    assert applied['lake_objects_deleted']==0 and applied['run_metadata_deleted']==0
    with store.connect() as db:
        assert {r['run_id'] for r in db.execute('SELECT run_id FROM inventory_entities WHERE run_id IN (%s,%s,%s)',(active,obsolete,recovery))}=={active,recovery}
        assert db.execute('SELECT count(*) AS n FROM inventory_runs WHERE namespace=%s',(lake.prefix,)).fetchone()['n']==3


def test_missing_dependency_prevents_deleting_projections(context):
    pipeline,journal=context
    lake,store=pipeline.store,journal.store
    rid=str(uuid4())
    run=journal.register(namespace=lake.prefix,source='test',scope='group',snapshot_id='r',source_revision='1',fingerprint='b'*64,mapping_version='1',schema_version='1')
    with store.connect() as db:
        db.execute('INSERT INTO inventory_runs VALUES (%s,%s,now(),%s,%s)',(rid,lake.prefix,'test','gold/obsolete.json'))
        db.execute("INSERT INTO inventory_entities(run_id,entity,id,name,pool_ids,search,data) VALUES (%s,'machines','m','Machine',ARRAY[]::text[],'machine','{}'::jsonb)",(rid,))
        db.execute('INSERT INTO collection_step_history(run_id,stage,artifact,fence,reason) VALUES (%s,%s,%s,%s,%s)',(run['id'],'gold',Jsonb({'manifest_key':'gold/missing.json'}),0,'test'))
    with pytest.raises(FileNotFoundError):
        prune_index_cache(store,lake,apply=True)
    with store.connect() as db:
        assert db.execute('SELECT count(*) AS n FROM inventory_entities WHERE run_id=%s',(rid,)).fetchone()['n']==1
