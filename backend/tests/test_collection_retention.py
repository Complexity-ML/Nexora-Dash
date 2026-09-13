import pytest
from test_collection_runner import context
from app.collection.retention import journal_protection
from psycopg.types.json import Jsonb


def test_retention_includes_unpublished_and_archived_checkpoints(context):
    lake, journal = context[0].store, context[1]
    run = journal.register(namespace=lake.prefix, source='test', scope='group', snapshot_id='1',
        source_revision='1', fingerprint='a'*64, mapping_version='1', schema_version='1')
    fence = journal.claim(run['id'], 'fixture')
    lake.put_json('bronze/source.json', {'payload_json': '{}'})
    lake.put_json('gold/archived.json', {'usage': {'format': 'delta', 'path': 'silver/old', 'version': 3}})
    journal.checkpoint(run['id'], fence, 'bronze', {'key': 'bronze/source.json'})
    journal.fail(run['id'], fence, 'AWAITING_ACTIVATION')
    with journal.store.connect() as db:
        db.execute('INSERT INTO collection_step_history(run_id,stage,artifact,fence,reason) VALUES (%s,%s,%s,%s,%s)',
                   (run['id'], 'gold', Jsonb({'manifest_key': 'gold/archived.json'}), fence, 'test'))
    report = journal_protection(lake, journal)
    assert report['objects'] == ['bronze/source.json', 'gold/archived.json']
    assert report['delta_versions'] == [{'path': 'silver/old', 'version': 3}]
    assert report['runs_by_state'] == {'retryable': 1}
    assert report['root_artifacts'] == 2 and report['deletion_authorized'] is False
    assert journal.head(lake.prefix, 'test', 'group') is None
    lake.prefix += '-another'
    assert journal_protection(lake, journal)['objects'] == []


def test_retention_fails_on_missing_referenced_manifest(context):
    lake, journal = context[0].store, context[1]
    run = journal.register(namespace=lake.prefix, source='test', scope='group', snapshot_id='1',
        source_revision='1', fingerprint='a'*64, mapping_version='1', schema_version='1')
    fence = journal.claim(run['id'], 'fixture')
    journal.checkpoint(run['id'], fence, 'bronze', {'key': 'bronze/missing.json'})
    with pytest.raises(FileNotFoundError):
        journal_protection(lake, journal)


@pytest.mark.parametrize('version', [True, False, 1.0, '1', None, -1])
def test_retention_rejects_ambiguous_delta_versions(version):
    from app.collection.dependencies import dependency_inventory
    with pytest.raises(ValueError, match='version'):
        dependency_inventory(None, [{'format':'delta', 'path':'silver/usage', 'version':version}])
