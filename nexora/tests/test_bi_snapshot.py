import pytest
from test_collection_runner import context, collect
from app.collection.runner import CollectionRunner
from app.bi.snapshot import export_pool_snapshot
from app.collection.dependencies import dependency_inventory


def test_snapshot_contains_only_selected_pools_and_gold_dependencies(context):
    pipeline, journal = context
    collect(CollectionRunner(pipeline, journal), day=1)
    collect(CollectionRunner(pipeline, journal), day=2)
    result = export_pool_snapshot(pipeline.store, journal, source='digimon-mock', scope='group',
                                  audience='sam-cad', pool_ids=['flex-cad'])
    manifest = result['manifest']
    assert manifest['rows'] == 2
    from app.storage.delta_tables import DeltaReference
    table = pipeline.store.delta.read(DeltaReference(**manifest['tables']['pool_usage']))
    assert table.column('license_pool_id').to_pylist() == ['flex-cad', 'flex-cad']
    assert 'user_id' not in table.column_names and 'machine_id' not in table.column_names
    dependencies = dependency_inventory(pipeline.store, [result])
    assert all(key.startswith('gold/bi/sam-cad/') for key in dependencies['objects'])
    assert all(ref['path'].startswith('gold/bi/sam-cad/') for ref in dependencies['delta_versions'])
    assert len(manifest['source_manifest_fingerprint']) == 64


@pytest.mark.parametrize('pools', [[], ['unknown']])
def test_no_implicit_all_catalog_export(context, pools):
    pipeline, journal = context
    collect(CollectionRunner(pipeline, journal))
    with pytest.raises(ValueError):
        export_pool_snapshot(pipeline.store, journal, source='digimon-mock', scope='group', audience='cad', pool_ids=pools)
    assert not (pipeline.store.root/'gold/bi').exists()
