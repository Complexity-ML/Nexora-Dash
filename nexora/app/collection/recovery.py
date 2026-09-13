"""Resume archived collections without requiring the source to be online."""
import json
from app.collection.journal import Conflict, fingerprint
from app.collection.quality import CoveragePolicy
from app.collection.runner import CollectionRunner, DayRevisionConflict, encoded


def recover_once(pipeline, journal, *, source, scope, limit=10, stop_requested=lambda: False):
    outcomes = []
    for run in journal.recovery_candidates(pipeline.store.prefix, source, scope, limit, rotate=True):
        if stop_requested():
            break
        result = {'run_id': run['id']}
        try:
            bronze = journal.checkpoints(run['id']).get('bronze')
            if not bronze:
                outcomes.append({**result, 'status': 'source_required'})
                continue
            envelope = json.loads(pipeline.store.get_bytes(bronze['key']))
            replay = envelope.get('replay')
            if not replay:
                outcomes.append({**result, 'status': 'replay_metadata_required'})
                continue
            policy = CoveragePolicy.model_validate(getattr(pipeline, 'collection_quality_policy', {}))
            identity_settings = {'mapping': replay['mapping_version'],
                'threshold': pipeline.analytics.threshold, 'reserve': pipeline.analytics.buffer_rate,
                'coverage_policy': policy.identity()}
            if replay.get('expected_day') is not None:
                identity_settings['expected_day'] = replay['expected_day']
            transform = fingerprint(encoded(identity_settings))
            if transform != run['mapping_version'] or replay['schema_version'] != run['schema_version']:
                outcomes.append({**result, 'status': 'configuration_changed'})
                continue
            payload = envelope['payload_json']
            if fingerprint(payload.encode()) != run['fingerprint'] or bronze['fingerprint'] != run['fingerprint']:
                raise ValueError('Archived source fingerprint mismatch')
            manifest = CollectionRunner(pipeline, journal).run(json.loads(payload), source=source,
                scope=scope, snapshot_id=run['snapshot_id'], source_revision=run['source_revision'], **replay)
            if manifest['run_id'] != run['id']:
                raise RuntimeError('Recovery produced an unexpected run')
            result['status'] = 'published'
        except DayRevisionConflict:
            result['status'] = 'day_revision_conflict'
        except Conflict:
            result['status'] = 'busy_or_superseded'
        except Exception:
            # Do not export payloads, credentials or raw transport exception text.
            result['status'] = 'failed'
        outcomes.append(result)
    return outcomes
