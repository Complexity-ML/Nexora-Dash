import pytest
from test_collection_runner import context, collect
from app.collection.runner import CollectionRunner
from app.collection.journal import Conflict
from app.collection.retention import journal_protection
from app.bi.catalog import prepare_pool_snapshot, publish_snapshot, publication


def prepare(context):
    return prepare_pool_snapshot(context[0].store,context[1],source='digimon-mock',scope='group',audience='cad',pool_ids=['flex-cad'])


def test_bi_publication_cas_and_retention_of_unpublished_candidates(context):
    pipeline,journal=context
    collect(CollectionRunner(pipeline,journal))
    first,second=prepare(context),prepare(context)
    publish_snapshot(pipeline.store,journal,first['snapshot_id'],expected_snapshot=None)
    with pytest.raises(Conflict,match='BI publication changed'):
        publish_snapshot(pipeline.store,journal,second['snapshot_id'],expected_snapshot=None)
    publish_snapshot(pipeline.store,journal,second['snapshot_id'],expected_snapshot=first['snapshot_id'])
    assert publish_snapshot(pipeline.store,journal,second['snapshot_id'],expected_snapshot=first['snapshot_id']) == second['snapshot_id']
    assert publication(journal,namespace=pipeline.store.prefix,audience='cad')['snapshot_id'] == second['snapshot_id']
    assert publication(journal,namespace=pipeline.store.prefix,audience='other') is None
    pending=prepare(context)
    report=journal_protection(pipeline.store,journal)
    assert all(item['manifest_key'] in report['objects'] for item in (first,second,pending))


def test_old_source_snapshot_cannot_become_new_bi_publication(context):
    pipeline,journal=context
    collect(CollectionRunner(pipeline,journal))
    old=prepare(context)
    collect(CollectionRunner(pipeline,journal),day=2)
    with pytest.raises(Conflict,match='Source publication changed'):
        publish_snapshot(pipeline.store,journal,old['snapshot_id'],expected_snapshot=None)
    with journal.store.connect() as db:
        assert db.execute('SELECT snapshot_id FROM bi_publications WHERE namespace=%s', (pipeline.store.prefix,)).fetchone() is None
