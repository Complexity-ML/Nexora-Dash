import csv
from io import StringIO
import pytest
import pyarrow as pa
from test_collection_runner import context, collect
from app.collection.runner import CollectionRunner, encoded
from app.collection.journal import fingerprint
from app.bi.snapshot import export_pool_snapshot
from app.bi.download import pool_csv
from app.storage.delta_tables import DeltaReference


def exported(context):
    pipeline, journal = context
    collect(CollectionRunner(pipeline, journal))
    result = export_pool_snapshot(pipeline.store, journal, source='digimon-mock', scope='group',
                                  audience='cad', pool_ids=['flex-cad'])
    return pipeline.store, result


def test_csv_keeps_published_version_after_new_delta_commit(context):
    lake, result = exported(context)
    ref = DeltaReference(**result['manifest']['tables']['pool_usage'])
    original = lake.delta.read(ref)
    changed = original.to_pylist()
    changed[0]['used'] = 999999
    newer = lake.delta.replace(ref.path, pa.Table.from_pylist(changed, schema=original.schema))
    assert newer.version > ref.version
    rows = list(csv.DictReader(StringIO(pool_csv(lake, result, 'cad'))))
    assert int(rows[0]['used']) == original.to_pylist()[0]['used']


@pytest.mark.parametrize('change', ['audience', 'path', 'version', 'rows'])
def test_csv_rejects_invalid_even_fingerprinted_metadata(context, change):
    lake, result = exported(context)
    manifest = result['manifest']
    if change == 'audience':
        manifest['audience'] = 'other'
    elif change == 'path':
        manifest['tables']['pool_usage']['path'] = 'silver/private'
    elif change == 'version':
        manifest['tables']['pool_usage']['version'] = True
    else:
        manifest['rows'] += 1
    lake.put_json(result['manifest_key'], manifest)
    result['fingerprint'] = fingerprint(encoded(manifest))
    with pytest.raises(ValueError):
        pool_csv(lake, result, 'cad')
