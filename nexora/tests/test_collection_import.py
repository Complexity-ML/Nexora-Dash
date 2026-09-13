"""Import keeps existing versions and refuses a changed legacy generation."""
import json
from datetime import date, datetime, timezone
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from test_collection_runner import context
from enterprise_fixture import snapshot
from app.connectors.digimon import map_digimon_payload
from app.models.inventory import map_inventory_payload
from app.business.inventory_index import publish_index
from app.collection.import_existing import prepare_existing, activate_existing
from app.collection.reader import PublishedCollection
from app.storage import pool_tables


def seed(pipeline, journal):
    lake = pipeline.store
    raw = snapshot(datetime(2026, 1, 1, tzinfo=timezone.utc))
    mapped = map_digimon_payload(raw)
    lake.delta.replace_day(pool_tables.PATH, date(2026, 1, 1), pa.Table.from_pylist(
        [v.model_dump(mode='json') for v in mapped.usage]))
    key = 'bronze/digimon/date=2026-01-01/source.parquet'
    path = lake.root / key
    path.parent.mkdir(parents=True)
    pq.write_table(pa.table({'payload_json': [json.dumps(raw)]}), path)
    lake.list_keys = lambda prefix: [str(p.relative_to(lake.root)) for p in lake.root.rglob('*.parquet')
                                     if str(p.relative_to(lake.root)).startswith(prefix)]
    lake.put_json('gold/enterprise/original.json', {'dimensions': {}})
    index = publish_index(journal.store, lake.prefix, map_inventory_payload(raw), 'gold/enterprise/original.json')
    return raw, index


def test_import_reuses_versions_and_does_not_activate_during_preparation(context):
    pipeline, journal = context
    raw, index = seed(pipeline, journal)
    artifact = prepare_existing(pipeline, journal, source='digimon-mock', scope='group')
    assert journal.head(pipeline.store.prefix, 'digimon-mock', 'group') is None
    assert prepare_existing(pipeline, journal, source='digimon-mock', scope='group') == artifact
    manifest = activate_existing(pipeline, journal, artifact)
    assert manifest['index_run'] == index
    assert manifest['daily']['2026-01-01']['usage']['path'] == pool_tables.PATH
    reader = PublishedCollection(pipeline.store, journal, 'digimon-mock', 'group')
    assert reader.usage().num_rows == 12
    assert reader.latest_snapshot().usage == map_digimon_payload(raw).usage
    assert reader.latest_snapshot().stock == map_digimon_payload(raw).stock
    assert activate_existing(pipeline, journal, artifact) == manifest


@pytest.mark.parametrize('changed', ['pool', 'manifest'])
def test_import_rejects_changes_after_preparation(context, changed):
    pipeline, journal = context
    seed(pipeline, journal)
    artifact = prepare_existing(pipeline, journal, source='digimon-mock', scope='group')
    if changed == 'pool':
        ref = pool_tables.reference(pipeline.store)
        pipeline.store.delta.replace(pool_tables.PATH, pipeline.store.delta.read(ref))
    else:
        pipeline.store.put_json('gold/enterprise/original.json', {'dimensions': {}, 'changed': True})
    with pytest.raises(ValueError, match='changed'):
        activate_existing(pipeline, journal, artifact)
    assert journal.head(pipeline.store.prefix, 'digimon-mock', 'group') is None


@pytest.mark.parametrize('defect', ['missing_partition', 'duplicate_day', 'wrong_partition'])
def test_import_checks_retained_enterprise_history(context, defect):
    pipeline, journal = context
    seed(pipeline, journal)
    lake = pipeline.store
    ref = lake.delta.replace_day('silver/enterprise/observations', date(2026, 1, 1),
                                 pa.table({'machine_id': ['m1']})).to_dict()
    item = {**ref, 'date': '2026-01-01', 'observation_date': '2026-01-01', 'rows': 1}
    if defect == 'missing_partition':
        item.update(date='2026-01-02', observation_date='2026-01-02')
    elif defect == 'wrong_partition':
        item['observation_date'] = None
    manifest = {'dimensions': {}, 'daily': [item, item] if defect == 'duplicate_day' else [item]}
    lake.put_json('gold/enterprise/original.json', manifest)
    with pytest.raises(ValueError, match='count mismatch|Duplicate|partition'):
        prepare_existing(pipeline, journal, source='digimon-mock', scope='group')
    assert journal.head(lake.prefix, 'digimon-mock', 'group') is None


def test_old_day_correction_keeps_imported_current_inventory(context):
    from app.collection.runner import CollectionRunner
    pipeline, journal = context
    raw, index = seed(pipeline, journal)
    artifact = prepare_existing(pipeline, journal, source='digimon-mock', scope='group')
    imported = activate_existing(pipeline, journal, artifact)
    older = snapshot(datetime(2025, 12, 31, tzinfo=timezone.utc))
    corrected = CollectionRunner(pipeline, journal).run(older, source='digimon-mock',
        scope='group', snapshot_id='older', source_revision='1')
    assert corrected['index_run'] == index
    assert corrected['index_namespace'] == pipeline.store.prefix
    assert corrected['index_manifest_key'] == imported['index_manifest_key']
    assert corrected['enterprise_manifest'] == imported['enterprise_manifest']
    reader = PublishedCollection(pipeline.store, journal, 'digimon-mock', 'group')
    assert reader.usage().num_rows == 24
    assert reader.latest_snapshot().stock == map_digimon_payload(raw).stock


def test_verification_does_not_activate_and_rejects_changed_settings(context):
    from app.collection.import_existing import verify_existing
    pipeline,journal=context
    seed(pipeline,journal)
    artifact=prepare_existing(pipeline,journal,source='digimon-mock',scope='group')
    before=journal.checkpoints(json.loads(pipeline.store.get_bytes(artifact['manifest_key']))['run_id'])
    manifest=verify_existing(pipeline,journal,artifact)
    assert journal.checkpoints(manifest['run_id']) == before
    assert journal.head(pipeline.store.prefix,'digimon-mock','group') is None
    pipeline.analytics.threshold = .17
    with pytest.raises(ValueError,match='Analysis settings changed'):
        verify_existing(pipeline,journal,artifact)
    with pytest.raises(ValueError,match='Analysis settings changed'):
        activate_existing(pipeline,journal,artifact)
    assert journal.head(pipeline.store.prefix,'digimon-mock','group') is None
