import pytest
from test_collection_runner import context
from app.bi.auth import issue_reader, authenticate_reader, revoke_reader, BIUnauthorized


def test_reader_is_hashed_scoped_and_revocable(context):
    pipeline,journal=context
    namespace=pipeline.store.prefix
    credential=issue_reader(journal.store,namespace=namespace,audience='cad')
    principal=authenticate_reader(journal.store,namespace=namespace,token=credential['token'])
    assert principal == {'id':credential['id'],'namespace':namespace,'audience':'cad'}
    with journal.store.connect() as db:
        row=db.execute('SELECT * FROM bi_readers WHERE id=%s',(credential['id'],)).fetchone()
    assert credential['token'] not in str(row) and len(row['token_hash']) == 64
    with pytest.raises(BIUnauthorized):
        authenticate_reader(journal.store,namespace=namespace+'other',token=credential['token'])
    assert not revoke_reader(journal.store,namespace=namespace+'other',reader_id=credential['id'])
    assert revoke_reader(journal.store,namespace=namespace,reader_id=credential['id'])
    assert revoke_reader(journal.store,namespace=namespace,reader_id=credential['id'])
    with pytest.raises(BIUnauthorized):
        authenticate_reader(journal.store,namespace=namespace,token=credential['token'])


def test_expired_reader_is_rejected(context):
    pipeline,journal=context
    credential=issue_reader(journal.store,namespace=pipeline.store.prefix,audience='cad')
    with journal.store.connect() as db:
        db.execute("UPDATE bi_readers SET created_at=clock_timestamp()-interval '2 hours',expires_at=clock_timestamp()-interval '1 hour' WHERE id=%s",(credential['id'],))
    with pytest.raises(BIUnauthorized):
        authenticate_reader(journal.store,namespace=pipeline.store.prefix,token=credential['token'])


@pytest.mark.parametrize('token',[None,'','admin@sam.demo','Bearer secret'])
def test_invalid_token_never_queries_database(token):
    with pytest.raises(BIUnauthorized):
        authenticate_reader(None,namespace='test',token=token)


def test_publication_audience_comes_from_credential(context):
    from app.collection.runner import CollectionRunner
    from test_collection_runner import collect
    from test_bi_catalog import prepare
    from app.bi.catalog import publish_snapshot
    from app.bi.auth import reader_publication
    pipeline,journal=context
    collect(CollectionRunner(pipeline,journal))
    prepared=prepare(context)
    publish_snapshot(pipeline.store,journal,prepared['snapshot_id'],expected_snapshot=None)
    allowed=issue_reader(journal.store,namespace=pipeline.store.prefix,audience='cad')
    other=issue_reader(journal.store,namespace=pipeline.store.prefix,audience='other')
    assert reader_publication(journal,namespace=pipeline.store.prefix,token=allowed['token'])['snapshot_id'] == prepared['snapshot_id']
    assert reader_publication(journal,namespace=pipeline.store.prefix,token=other['token']) is None


def test_restored_namespace_retirement_preview_scope_and_reissue(context):
    from app.bi.auth import revoke_namespace_readers
    pipeline,journal=context
    namespace=pipeline.store.prefix
    old=issue_reader(journal.store,namespace=namespace,audience='cad')
    other=issue_reader(journal.store,namespace=namespace+'other',audience='cad')
    assert revoke_namespace_readers(journal.store,namespace=namespace) == {'applied':False,'readers':1}
    assert authenticate_reader(journal.store,namespace=namespace,token=old['token'])
    assert revoke_namespace_readers(journal.store,namespace=namespace,apply=True) == {'applied':True,'readers':1}
    with pytest.raises(BIUnauthorized):
        authenticate_reader(journal.store,namespace=namespace,token=old['token'])
    assert authenticate_reader(journal.store,namespace=namespace+'other',token=other['token'])
    assert revoke_namespace_readers(journal.store,namespace=namespace,apply=True)['readers'] == 0
    new=issue_reader(journal.store,namespace=namespace,audience='cad')
    assert authenticate_reader(journal.store,namespace=namespace,token=new['token'])


def test_empty_root_namespace_is_exact_not_a_wildcard(context):
    from app.bi.auth import revoke_namespace_readers
    pipeline,journal=context
    root=issue_reader(journal.store,namespace='',audience='cad')
    nested=issue_reader(journal.store,namespace=pipeline.store.prefix,audience='cad')
    try:
        assert authenticate_reader(journal.store,namespace='',token=root['token'])['namespace'] == ''
        with pytest.raises(BIUnauthorized):
            authenticate_reader(journal.store,namespace=pipeline.store.prefix,token=root['token'])
        revoke_namespace_readers(journal.store,namespace='',apply=True)
        with pytest.raises(BIUnauthorized):
            authenticate_reader(journal.store,namespace='',token=root['token'])
        assert authenticate_reader(journal.store,namespace=pipeline.store.prefix,token=nested['token'])
    finally:
        with journal.store.connect() as db:
            db.execute('DELETE FROM bi_readers WHERE id IN (%s,%s)',(root['id'],nested['id']))
