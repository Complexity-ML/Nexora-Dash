import pytest
from test_collection_runner import context,collect
from app.collection.runner import CollectionRunner
from app.collection.reader import PublishedCollection
from app.bi.inventory_snapshot import export_inventory_snapshot,SCHEMA
from app.storage.delta_tables import DeltaReference


def test_inventory_export_is_scoped_and_uses_published_index(context):
    pipeline,journal=context
    collect(CollectionRunner(pipeline,journal))
    reader=PublishedCollection(pipeline.store,journal,'digimon-mock','group')
    inventory=reader.inventory()
    chosen=inventory.sites[0].subsidiary_id
    sites={s.site_id for s in inventory.sites if s.subsidiary_id==chosen}
    expected=sum(m.site_id in sites for m in inventory.machines)
    exported=export_inventory_snapshot(pipeline.store,journal,source='digimon-mock',scope='group',
        audience='inventory',subsidiary_ids=[chosen])
    table=pipeline.store.delta.read(DeltaReference(**exported['manifest']['tables']['inventory_counts']))
    assert table.schema == SCHEMA
    assert sum(table.column('machines').to_pylist()) == expected
    assert set(table.column('subsidiary_id').to_pylist()) == {chosen}
    assert not {'machine_id','user_id','email','host_id'} & set(table.column_names)


@pytest.mark.parametrize('selection',[[],['unknown']])
def test_inventory_export_requires_known_explicit_scope(context,selection):
    pipeline,journal=context
    collect(CollectionRunner(pipeline,journal))
    with pytest.raises(ValueError):
        export_inventory_snapshot(pipeline.store,journal,source='digimon-mock',scope='group',
            audience='inventory',subsidiary_ids=selection)
    assert not (pipeline.store.root/'gold/bi').exists()


def test_inventory_candidate_publishes_through_same_catalog(context):
    from app.bi.catalog import prepare_inventory_snapshot,publish_snapshot,publication
    pipeline,journal=context
    collect(CollectionRunner(pipeline,journal))
    inventory=PublishedCollection(pipeline.store,journal,'digimon-mock','group').inventory()
    candidate=prepare_inventory_snapshot(pipeline.store,journal,source='digimon-mock',scope='group',
        audience='inventory',subsidiary_ids=[inventory.sites[0].subsidiary_id])
    publish_snapshot(pipeline.store,journal,candidate['snapshot_id'],expected_snapshot=None)
    assert publication(journal,namespace=pipeline.store.prefix,audience='inventory')['snapshot_id'] == candidate['snapshot_id']
