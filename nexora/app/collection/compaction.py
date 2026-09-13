"""Validated, atomic compaction adoption for one published usage day."""
from copy import deepcopy
from uuid import uuid4
from app.collection.reader import PublishedCollection
from app.collection.journal import Conflict, fingerprint
from app.collection.runner import encoded
from app.collection.maintenance_lock import protect_backup
from app.storage.delta_tables import DeltaReference


def compact_usage_day(lake, journal, *, source, scope, day, target_size=134217728, hook=None):
    hook = hook or (lambda stage: None)
    # Compaction removes files from the active set, but never deletes them.
    # Keep cooperative deletion excluded while validating old and new versions.
    with journal.store.connect() as protection:
        protect_backup(protection)
        reader = PublishedCollection(lake, journal, source, scope)
        if not reader.manifest or day not in reader.manifest['daily']:
            raise ValueError('No published usage for this day')
        original = DeltaReference(**reader.manifest['daily'][day]['usage'])
        current = lake.delta.latest(original.path)
        if current.version != original.version:
            commit = lake.delta.open(current).history(limit=1)[0]
            if (commit.get('nexora_maintenance') != 'compaction'
                    or commit.get('nexora_base_version') != str(original.version)):
                raise Conflict('Table changed outside this compaction; review the current publication')
            candidate = DeltaReference(original.path, current.version, observation_date=original.observation_date)
        else:
            candidate, _ = lake.delta.compact(original, target_size=target_size)
        hook('after_compaction')
        if candidate == original:
            return {'status':'unchanged', 'manifest_key':reader.manifest_key}
        before, after = lake.delta.read(original), lake.delta.read(candidate)
        order = [(name, 'ascending') for name in before.column_names]
        if (not before.schema.equals(after.schema) or before.num_rows != after.num_rows
                or not before.sort_by(order).equals(after.sort_by(order))):
            raise ValueError('Compaction changed published usage data')
        manifest = deepcopy(reader.manifest)
        manifest['daily'][day]['usage'] = candidate.to_dict()
        manifest['previous_manifest'] = reader.manifest_key
        manifest['maintenance'] = {'operation':'compaction', 'day':day,
                                   'before':original.to_dict(), 'after':candidate.to_dict()}
        key = f"gold/maintenance/{uuid4()}/manifest.json"
        lake.put_json(key, manifest)
        artifact = {'manifest_key':key, 'fingerprint':fingerprint(encoded(manifest))}
        if fingerprint(lake.get_bytes(key)) != artifact['fingerprint']:
            # Storage JSON formatting may differ; compare canonical content.
            import json
            if fingerprint(encoded(json.loads(lake.get_bytes(key)))) != artifact['fingerprint']:
                raise ValueError('Maintenance manifest verification failed')
        hook('before_publish')
        journal.replace_published_manifest(manifest['run_id'], expected_manifest=reader.manifest_key, artifact=artifact)
        return {'status':'published', 'manifest_key':key, 'version':candidate.version}
