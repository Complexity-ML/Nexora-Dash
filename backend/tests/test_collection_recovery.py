from copy import copy
import pytest
from test_collection_runner import context, collect
from app.collection.runner import CollectionRunner
from app.collection.recovery import recover_once


def interrupted(context):
    pipeline, journal = context
    def crash(event):
        if event == 'after_checkpoint_silver':
            raise RuntimeError('simulated worker failure')
    with pytest.raises(RuntimeError):
        collect(CollectionRunner(pipeline, journal, crash))
    return pipeline, journal


def test_recovery_uses_archived_source_and_same_run(context):
    pipeline, journal = interrupted(context)
    candidate = journal.recovery_candidates(pipeline.store.prefix, 'digimon-mock', 'group')[0]
    # No connector exists on this pipeline: recovery must use Bronze alone.
    results = recover_once(pipeline, journal, source='digimon-mock', scope='group')
    assert results == [{'run_id': candidate['id'], 'status': 'published'}]
    assert journal.head(pipeline.store.prefix, 'digimon-mock', 'group')['run_id'] == candidate['id']
    assert recover_once(pipeline, journal, source='digimon-mock', scope='group') == []


def test_recovery_rejects_silent_configuration_changes(context):
    pipeline, journal = interrupted(context)
    pipeline.analytics = copy(pipeline.analytics)
    pipeline.analytics.threshold = .5
    results = recover_once(pipeline, journal, source='digimon-mock', scope='group')
    assert results[0]['status'] == 'configuration_changed'
    assert journal.head(pipeline.store.prefix, 'digimon-mock', 'group') is None


def test_recovery_is_scoped_and_rejects_tampered_bronze(context):
    pipeline, journal = interrupted(context)
    assert recover_once(pipeline, journal, source='digimon-mock', scope='another') == []
    candidate = journal.recovery_candidates(pipeline.store.prefix, 'digimon-mock', 'group')[0]
    bronze = journal.checkpoints(candidate['id'])['bronze']
    import json
    payload = json.loads(pipeline.store.get_bytes(bronze['key']))
    payload['payload_json'] = '{}'
    pipeline.store.put_json(bronze['key'], payload)
    results = recover_once(pipeline, journal, source='digimon-mock', scope='group')
    assert results[0]['status'] == 'failed'
    assert journal.head(pipeline.store.prefix, 'digimon-mock', 'group') is None


def test_recovery_reclaims_expired_worker_but_not_active_worker(context):
    pipeline, journal = interrupted(context)
    run = journal.recovery_candidates(pipeline.store.prefix, 'digimon-mock', 'group')[0]
    fence = journal.claim(run['id'], 'abandoned-worker')
    assert recover_once(pipeline, journal, source='digimon-mock', scope='group') == []
    with journal.store.connect() as db:
        db.execute("UPDATE collection_runs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (run['id'],))
    assert recover_once(pipeline, journal, source='digimon-mock', scope='group') == [
        {'run_id': run['id'], 'status': 'published'}]
    from app.collection.journal import LeaseLost
    with pytest.raises(LeaseLost):
        journal.checkpoint(run['id'], fence, 'gold', {'stale': True})


def test_recovery_leaves_explicit_import_activation_to_operator(context):
    pipeline, journal = interrupted(context)
    run = journal.recovery_candidates(pipeline.store.prefix, 'digimon-mock', 'group')[0]
    fence = journal.claim(run['id'], 'prepare-only')
    journal.fail(run['id'], fence, 'AWAITING_ACTIVATION')
    assert recover_once(pipeline, journal, source='digimon-mock', scope='group') == []
    assert journal.head(pipeline.store.prefix, 'digimon-mock', 'group') is None


def test_recovery_preserves_expected_batch_day(context):
    from datetime import datetime, timezone
    from app.connectors.demo import snapshot
    pipeline, journal = context
    def crash(event):
        if event == 'after_checkpoint_bronze':
            raise RuntimeError('interrupted batch')
    with pytest.raises(RuntimeError):
        CollectionRunner(pipeline, journal, crash).run(snapshot(datetime(2026,1,1,tzinfo=timezone.utc)),
            source='digimon-mock', scope='group', snapshot_id='batch', source_revision='1', expected_day='2026-01-01')
    assert recover_once(pipeline, journal, source='digimon-mock', scope='group')[0]['status'] == 'published'


def test_blocked_old_run_does_not_starve_later_recovery(context):
    import json
    from app.collection.journal import CollectionJournal
    pipeline, journal = interrupted(context)
    old = journal.recovery_candidates(pipeline.store.prefix, 'digimon-mock', 'group')[0]
    bronze = journal.checkpoints(old['id'])['bronze']
    envelope = json.loads(pipeline.store.get_bytes(bronze['key']))
    envelope.pop('replay')  # Older archive requires an operator-provided mapping.
    pipeline.store.put_json(bronze['key'], envelope)
    def crash(event):
        if event == 'after_checkpoint_bronze':
            raise RuntimeError('interrupted next day')
    with pytest.raises(RuntimeError):
        collect(CollectionRunner(pipeline, journal, crash), day=2)
    assert recover_once(pipeline, journal, source='digimon-mock', scope='group', limit=1) == [
        {'run_id': old['id'], 'status': 'replay_metadata_required'}]
    # A new process must retain the rotation, even though the blocked run was not claimed.
    restarted = CollectionJournal(journal.store)
    second = recover_once(pipeline, restarted, source='digimon-mock', scope='group', limit=1)
    assert second[0]['status'] == 'published' and second[0]['run_id'] != old['id']
    assert restarted.head(pipeline.store.prefix, 'digimon-mock', 'group')['run_id'] == second[0]['run_id']
    # Blocking does not delete/reject the old run: it remains inspectable and retryable.
    assert recover_once(pipeline, restarted, source='digimon-mock', scope='group', limit=1) == [
        {'run_id': old['id'], 'status': 'replay_metadata_required'}]
    assert restarted.checkpoints(old['id'])['bronze'] == bronze


def test_inspecting_candidates_does_not_change_recovery_order(context):
    pipeline, journal = interrupted(context)
    candidates = journal.recovery_candidates(pipeline.store.prefix, 'digimon-mock', 'group')
    assert candidates[0]['recovery_checked_at'] is None
    assert journal.recovery_candidates(pipeline.store.prefix, 'digimon-mock', 'group') == candidates


def test_stop_request_leaves_candidate_for_a_later_pass(context):
    pipeline, journal = interrupted(context)
    run = journal.recovery_candidates(pipeline.store.prefix, 'digimon-mock', 'group')[0]
    assert recover_once(pipeline, journal, source='digimon-mock', scope='group',
                        stop_requested=lambda: True) == []
    assert journal.head(pipeline.store.prefix, 'digimon-mock', 'group') is None
    assert recover_once(pipeline, journal, source='digimon-mock', scope='group') == [
        {'run_id': run['id'], 'status': 'published'}]


def test_old_interrupted_payload_cannot_replace_later_published_day(context):
    from app.collection.reader import PublishedCollection
    from app.storage.table_reader import read_table
    from datetime import datetime, timezone
    from app.connectors.demo import snapshot
    pipeline, journal = interrupted(context)
    old = journal.recovery_candidates(pipeline.store.prefix, 'digimon-mock', 'group')[0]
    raw = snapshot(datetime(2026,1,1,tzinfo=timezone.utc))
    raw['pools'][0]['consumed'] = 7
    latest = CollectionRunner(pipeline, journal).run(raw, source='digimon-mock', scope='group',
        snapshot_id='1', source_revision='opaque-correction')
    assert recover_once(pipeline, journal, source='digimon-mock', scope='group') == [
        {'run_id': old['id'], 'status': 'day_revision_conflict'}]
    reader = PublishedCollection(pipeline.store, journal, 'digimon-mock', 'group')
    assert reader.manifest['run_id'] == latest['run_id']
    rows = read_table(pipeline.store, reader.manifest['daily']['2026-01-01']['usage']).to_pylist()
    assert rows[0]['used'] == 7
    with journal.store.connect() as db:
        record = db.execute('SELECT state,error_code FROM collection_runs WHERE id=%s', (old['id'],)).fetchone()
    assert record == {'state': 'rejected', 'error_code': 'DAY_REVISION_CONFLICT'}
    assert recover_once(pipeline, journal, source='digimon-mock', scope='group') == []
