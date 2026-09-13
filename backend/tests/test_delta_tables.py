from datetime import date

import pyarrow as pa
import pytest

from app.storage.delta_tables import DeltaTables
from deltalake.exceptions import SchemaMismatchError


def test_daily_replay_keeps_other_days_and_pinned_versions(tmp_path):
    store = DeltaTables(str(tmp_path))
    first = store.replace_day('silver/usage', date(2026, 1, 1), pa.table({'used': [2]}))
    store.replace_day('silver/usage', date(2026, 1, 2), pa.table({'used': [3]}))
    current = store.replace_day('silver/usage', date(2026, 1, 1), pa.table({'used': [4]}))
    assert sorted(store.read(current)['used'].to_pylist()) == [3, 4]
    assert store.read(first)['used'].to_pylist() == [2]
    assert (tmp_path / 'silver/usage/_delta_log/00000000000000000000.json').exists()


def test_invalid_partition_does_not_change_active_version(tmp_path):
    store = DeltaTables(str(tmp_path))
    first = store.replace_day('silver/usage', date(2026, 1, 1), pa.table({'used': [2]}))
    with pytest.raises(ValueError, match='observation date'):
        store.replace_day('silver/usage', date(2026, 1, 1), pa.table({
            'used': [4], 'observation_date': pa.array([date(2026, 1, 2)], type=pa.date32())}))
    assert store.latest('silver/usage') == first


def test_schema_failure_preserves_table(tmp_path):
    store = DeltaTables(str(tmp_path))
    first = store.replace('gold/products', pa.table({'product_id': ['a'], 'count': [1]}))
    with pytest.raises(SchemaMismatchError):
        store.replace('gold/products', pa.table({'unrelated_column': [5]}))
    assert store.latest('gold/products') == first
    assert store.read(first).to_pylist() == [{'product_id': 'a', 'count': 1}]


def test_reference_identifies_own_commit_when_another_writer_follows(tmp_path, monkeypatch):
    import app.storage.delta_tables as module
    write = module.write_deltalake
    def interleaved(uri, rows, **options):
        write(uri, rows, **options)
        write(uri, pa.table({'value': [99]}), mode='overwrite')
    monkeypatch.setattr(module, 'write_deltalake', interleaved)
    store = DeltaTables(str(tmp_path))
    result = store.replace('gold/summary', pa.table({'value': [1]}))
    assert result.version == 0
    assert store.read(result)['value'].to_pylist() == [1]
    assert store.read(store.latest('gold/summary'))['value'].to_pylist() == [99]


def test_manifest_day_filter_is_preserved_with_predicates(tmp_path):
    from app.storage.table_reader import read_table
    from types import SimpleNamespace
    store = DeltaTables(str(tmp_path))
    store.replace_day('silver/usage', date(2026, 1, 1), pa.table({'used': [2]}))
    current = store.replace_day('silver/usage', date(2026, 1, 2), pa.table({'used': [3]}))
    reference = {**current.to_dict(), 'observation_date': '2026-01-01'}
    lake = SimpleNamespace(delta=store)
    assert read_table(lake, reference, columns=['used']).to_pylist() == [{'used': 2}]
    assert read_table(lake, reference, filters=[[('used', '=', 3)], [('used', '=', 2)]]).num_rows == 1
    with pytest.raises(ValueError, match='Unsupported table format'):
        read_table(lake, {'format': 'unknown', 'key': 'unused'})


def test_inventory_nullable_schema_and_migration(tmp_path):
    import json
    from io import BytesIO
    from types import SimpleNamespace
    import pyarrow.parquet as pq
    from scripts.migrate_enterprise_delta import migrate
    objects = {}
    def parquet(key, rows):
        sink = BytesIO()
        pq.write_table(pa.Table.from_pylist(rows), sink)
        objects[key] = sink.getvalue()
        return {'key': key, 'rows': len(rows)}
    product = parquet('products.parquet', [{'software_id': 'rhel', 'name': 'RHEL',
                      'category': 'operating_system', 'license_pool_id': None}])
    days = []
    for day, used in [('2026-01-01', False), ('2026-01-02', True)]:
        item = parquet(day+'.parquet', [{'machine_id': 'm1', 'user_id': None,
                      'license_pool_id': 'pool', 'used': used, 'software_version': None,
                      'execution_minutes': None, 'execution_count': None}])
        days.append({**item, 'date': day})
    lake = SimpleNamespace(delta=DeltaTables(str(tmp_path)), get_bytes=objects.__getitem__,
                           put_json=lambda key, value: objects.update({key: json.dumps(value).encode()}))
    migrated = migrate(lake, {'dimensions': {'products': product}, 'daily': days}, 'test')
    from app.storage.table_reader import read_table
    assert read_table(lake, migrated['dimensions']['products']).to_pylist() == [
        {'software_id': 'rhel', 'name': 'RHEL', 'category': 'operating_system', 'license_pool_id': None}]
    assert [read_table(lake, day)['used'].to_pylist() for day in migrated['daily']] == [[False], [True]]
    assert len({day['version'] for day in migrated['daily']}) == 1
    assert len(objects) == 3  # Source archives are untouched.


@pytest.mark.parametrize('version', [True, False, 1.0, '1', None, -1])
def test_invalid_pinned_version_never_opens_storage(tmp_path, monkeypatch, version):
    from app.storage import delta_tables
    from app.storage.delta_tables import DeltaReference
    monkeypatch.setattr(delta_tables, 'DeltaTable', lambda *a, **k:pytest.fail('Storage must not be opened'))
    with pytest.raises(ValueError, match='reference'):
        DeltaTables(str(tmp_path)).open(DeltaReference('silver/usage', version))
