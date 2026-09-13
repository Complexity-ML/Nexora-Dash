from copy import deepcopy
import pytest
from deltalake import write_deltalake
from test_collection_runner import context, collect
from app.collection.runner import CollectionRunner, encoded
from app.collection.reader import PublishedCollection
from app.collection.journal import fingerprint, Conflict
from app.collection.compaction import compact_usage_day


def fragmented(context):
    pipeline, journal = context
    lake = pipeline.store
    collect(CollectionRunner(pipeline, journal))
    reader = PublishedCollection(lake, journal, 'digimon-mock', 'group')
    table = reader.usage()
    path = 'silver/fragmented'
    lake.delta.replace(path, table.slice(0, 3))
    for offset in (3, 6, 9):
        write_deltalake(lake.delta.uri(path), table.slice(offset, 3), mode='append')
    manifest = deepcopy(reader.manifest)
    manifest['daily']['2026-01-01']['usage'] = lake.delta.latest(path).to_dict()
    key = 'gold/fragmented/manifest.json'
    lake.put_json(key, manifest)
    journal.replace_published_manifest(manifest['run_id'], expected_manifest=reader.manifest_key,
        artifact={'manifest_key':key, 'fingerprint':fingerprint(encoded(manifest))})
    return lake, journal, table, key


def test_interrupted_compaction_reuses_candidate_and_preserves_reader(context):
    lake, journal, table, key = fragmented(context)
    def crash(stage):
        if stage == 'before_publish':
            raise RuntimeError('interrupted')
    with pytest.raises(RuntimeError, match='interrupted'):
        compact_usage_day(lake, journal, source='digimon-mock', scope='group', day='2026-01-01', hook=crash)
    assert PublishedCollection(lake, journal, 'digimon-mock', 'group').manifest_key == key
    result = compact_usage_day(lake, journal, source='digimon-mock', scope='group', day='2026-01-01')
    reader = PublishedCollection(lake, journal, 'digimon-mock', 'group')
    assert result['status'] == 'published' and reader.manifest_key != key
    assert reader.usage().sort_by([(name, 'ascending') for name in table.column_names]).equals(table.sort_by([(name, 'ascending') for name in table.column_names]))
    assert compact_usage_day(lake, journal, source='digimon-mock', scope='group', day='2026-01-01')['status'] == 'unchanged'


def test_new_collection_wins_over_stale_compaction(context):
    lake, journal, _, _ = fragmented(context)
    def publish_other(stage):
        if stage == 'before_publish':
            collect(CollectionRunner(context[0], journal), day=2)
    with pytest.raises(Conflict):
        compact_usage_day(lake, journal, source='digimon-mock', scope='group', day='2026-01-01', hook=publish_other)
    assert PublishedCollection(lake, journal, 'digimon-mock', 'group').usage().num_rows == 24


def test_changed_values_in_candidate_are_never_published(context, monkeypatch):
    import pyarrow as pa
    lake, journal, table, key = fragmented(context)
    def corrupt(reference, **kwargs):
        rows = table.to_pylist()
        rows[0]['used'] += 1
        return lake.delta.replace(reference.path, pa.Table.from_pylist(rows, schema=table.schema)), {}
    monkeypatch.setattr(lake.delta, 'compact', corrupt)
    with pytest.raises(ValueError, match='changed published usage'):
        compact_usage_day(lake, journal, source='digimon-mock', scope='group', day='2026-01-01')
    assert PublishedCollection(lake, journal, 'digimon-mock', 'group').manifest_key == key


def test_backup_after_compaction_restores_both_published_and_previous_versions(context, tmp_path_factory):
    import json
    import shutil
    from app.collection.retention import journal_protection
    from app.collection.backup import delta_backup_files
    from app.storage.delta_tables import DeltaReference, DeltaTables
    from types import SimpleNamespace
    lake, journal, table, previous_key = fragmented(context)
    previous = json.loads(lake.get_bytes(previous_key))
    previous_ref = DeltaReference(**previous['daily']['2026-01-01']['usage'])
    result = compact_usage_day(lake, journal, source='digimon-mock', scope='group', day='2026-01-01')
    report = journal_protection(lake, journal)
    assert previous_key in report['objects'] and result['manifest_key'] in report['objects']
    versions = {r['version'] for r in report['delta_versions'] if r['path'] == previous_ref.path}
    assert previous_ref.version in versions and result['version'] in versions
    lake.list_keys = lambda prefix: [str(p.relative_to(lake.root)) for p in (lake.root/prefix).rglob('*') if p.is_file()]
    keys = set(report['objects']) | set(delta_backup_files(lake, report['delta_versions']))
    destination = tmp_path_factory.mktemp('restored-compaction')
    for key in keys:
        path = destination/key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(lake.get_bytes(key))
    shutil.rmtree(lake.root)
    restored = SimpleNamespace(prefix=lake.prefix, delta=DeltaTables(str(destination)),
                               get_bytes=lambda key: (destination/key).read_bytes())
    reader = PublishedCollection(restored, journal, 'digimon-mock', 'group')
    assert reader.manifest_key == result['manifest_key']
    order = [(name, 'ascending') for name in table.column_names]
    assert reader.usage().sort_by(order).equals(table.sort_by(order))
    assert restored.delta.read(previous_ref).sort_by(order).equals(table.sort_by(order))
