"""PostgreSQL journal. Workers write artifacts before checkpointing them.

A lease fences metadata/publication, not external object writes. The coordinator
must use isolated immutable outputs and verify them before calling checkpoint.
"""
from hashlib import sha256
import json
import re
from uuid import uuid4
from psycopg.types.json import Jsonb

STAGES = ('bronze', 'validated', 'silver', 'gold')


class Conflict(RuntimeError):
    pass


class LeaseLost(Conflict):
    pass


def fingerprint(raw: bytes) -> str:
    return sha256(raw).hexdigest()


class CollectionJournal:
    def __init__(self, store):
        self.store = store

    def register(self, *, namespace, source, scope, snapshot_id, source_revision,
                 fingerprint, mapping_version, schema_version):
        identity = (namespace, source, scope, snapshot_id, source_revision, mapping_version, schema_version)
        if any(not isinstance(v, str) or not v.strip() for v in identity):
            raise ValueError('Collection identity fields must be explicit')
        if not re.fullmatch('[0-9a-f]{64}', fingerprint):
            raise ValueError('Expected a SHA-256 fingerprint')
        with self.store.connect() as db:
            db.execute('''INSERT INTO collection_runs
                (id,namespace,source,scope,snapshot_id,source_revision,mapping_version,schema_version,fingerprint)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
                (str(uuid4()), *identity, fingerprint))
            row = db.execute('''SELECT * FROM collection_runs WHERE
                namespace=%s AND source=%s AND scope=%s AND snapshot_id=%s AND source_revision=%s
                AND mapping_version=%s AND schema_version=%s''', identity).fetchone()
            if row['fingerprint'] != fingerprint:
                raise Conflict('Source revision reused with different content')
            return row

    def claim(self, run_id, owner, seconds=120):
        if not owner or not 1 <= seconds <= 3600:
            raise ValueError('Explicit owner and bounded lease required')
        with self.store.connect() as db:
            stream = db.execute('SELECT namespace,source,scope FROM collection_runs WHERE id=%s', (run_id,)).fetchone()
            if stream is None:
                raise Conflict('Unknown collection')
            # Transaction lock serializes lease acquisition for the stream.
            key = json.dumps([stream['namespace'],stream['source'],stream['scope']])
            db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (key,))
            occupied = db.execute('''SELECT id FROM collection_runs WHERE namespace=%s AND source=%s AND scope=%s
                AND state='running' AND lease_until > clock_timestamp() LIMIT 1''',
                (stream['namespace'],stream['source'],stream['scope'])).fetchone()
            if occupied:
                raise Conflict('Another worker owns this collection stream')
            row = db.execute('''UPDATE collection_runs SET state='running', owner=%s,
                fence=fence+1, lease_until=clock_timestamp()+(%s * interval '1 second'),error_code=NULL
                WHERE id=%s AND (state IN ('pending','retryable') OR
                (state='running' AND lease_until <= clock_timestamp())) RETURNING *''',
                (owner, seconds, run_id)).fetchone()
            if row is None:
                raise Conflict('Run unavailable or already completed')
            return row['fence']

    def _owned(self, db, run_id, fence):
        row = db.execute('''SELECT * FROM collection_runs WHERE id=%s AND fence=%s
            AND state='running' AND lease_until > clock_timestamp() FOR UPDATE''',
            (run_id, fence)).fetchone()
        if row is None:
            raise LeaseLost('Worker lease expired or superseded')
        return row

    def renew(self, run_id, fence, seconds=120):
        if not 1 <= seconds <= 3600:
            raise ValueError('Invalid lease duration')
        with self.store.connect() as db:
            self._owned(db, run_id, fence)
            db.execute("UPDATE collection_runs SET lease_until=clock_timestamp()+(%s * interval '1 second') WHERE id=%s", (seconds,run_id))

    def reconcile(self, run_id, fence):
        """Invalidate derived checkpoints if the baseline changed; retain lineage."""
        with self.store.connect() as db:
            run = self._owned(db,run_id,fence)
            valid = db.execute("SELECT artifact FROM collection_steps WHERE run_id=%s AND stage='validated'",(run_id,)).fetchone()
            if valid is None:
                return False
            head = db.execute('SELECT run_id,manifest_key FROM collection_heads WHERE namespace=%s AND source=%s AND scope=%s',
                              (run['namespace'],run['source'],run['scope'])).fetchone()
            if (valid['artifact'].get('expected_run') == (head['run_id'] if head else None)
                    and valid['artifact'].get('base_manifest') == (head['manifest_key'] if head else None)):
                return False
            db.execute("""INSERT INTO collection_step_history(run_id,stage,artifact,fence,reason)
                SELECT run_id,stage,artifact,%s,'BASELINE_CHANGED' FROM collection_steps
                WHERE run_id=%s AND stage<>'bronze'""",(fence,run_id))
            db.execute("DELETE FROM collection_steps WHERE run_id=%s AND stage<>'bronze'",(run_id,))
            return True

    def checkpoints(self, run_id):
        with self.store.connect() as db:
            rows = db.execute('SELECT stage,artifact FROM collection_steps WHERE run_id=%s', (run_id,)).fetchall()
        return {row['stage']:row['artifact'] for row in rows}

    def checkpoint(self, run_id, fence, stage, artifact):
        if stage not in STAGES or not isinstance(artifact, dict) or not artifact:
            raise ValueError('Expected a known stage and artifact metadata')
        # JSON roundtrip prevents non-persistent values and NaN in recovery metadata.
        artifact = json.loads(json.dumps(artifact, allow_nan=False))
        with self.store.connect() as db:
            self._owned(db, run_id, fence)
            existing = {r['stage']:r['artifact'] for r in db.execute(
                'SELECT stage,artifact FROM collection_steps WHERE run_id=%s', (run_id,)).fetchall()}
            if stage in existing:
                if existing[stage] != artifact:
                    raise Conflict('A completed checkpoint is immutable')
                return
            if not all(s in existing for s in STAGES[:STAGES.index(stage)]):
                raise Conflict('Previous stage is not complete')
            db.execute('INSERT INTO collection_steps(run_id,stage,artifact) VALUES (%s,%s,%s)',
                       (run_id,stage,Jsonb(artifact)))

    def fail(self, run_id, fence, code, retryable=True):
        if not re.fullmatch('[A-Z][A-Z0-9_]{0,63}', code):
            raise ValueError('Use a sanitized error code, not an exception payload')
        with self.store.connect() as db:
            self._owned(db,run_id,fence)
            db.execute('UPDATE collection_runs SET state=%s,error_code=%s,owner=NULL,lease_until=NULL WHERE id=%s',
                       ('retryable' if retryable else 'rejected',code,run_id))

    def recovery_candidates(self, namespace, source, scope, limit=10, *, rotate=False):
        if not 1 <= limit <= 100:
            raise ValueError('Recovery batch must contain 1 to 100 runs')
        with self.store.connect() as db:
            if rotate:
                # Selection is durable, but is not a worker lease. claim() still fences execution.
                return db.execute("""WITH candidates AS (
                    SELECT id FROM collection_runs
                    WHERE namespace=%s AND source=%s AND scope=%s
                    AND (state='retryable' OR (state='running' AND lease_until <= clock_timestamp()))
                    AND error_code IS DISTINCT FROM 'AWAITING_ACTIVATION'
                    ORDER BY recovery_checked_at NULLS FIRST,created_at,id
                    LIMIT %s FOR UPDATE SKIP LOCKED
                ), checked AS (
                    UPDATE collection_runs r SET recovery_checked_at=clock_timestamp()
                    FROM candidates c WHERE r.id=c.id RETURNING r.*
                ) SELECT * FROM checked ORDER BY created_at,id""",
                    (namespace,source,scope,limit)).fetchall()
            return db.execute("""SELECT * FROM collection_runs
                WHERE namespace=%s AND source=%s AND scope=%s
                AND (state='retryable' OR (state='running' AND lease_until <= clock_timestamp()))
                AND error_code IS DISTINCT FROM 'AWAITING_ACTIVATION'
                ORDER BY created_at,id LIMIT %s""", (namespace,source,scope,limit)).fetchall()

    def head(self, namespace, source, scope):
        with self.store.connect() as db:
            return db.execute('SELECT run_id,manifest_key FROM collection_heads WHERE namespace=%s AND source=%s AND scope=%s',
                              (namespace,source,scope)).fetchone()

    def publish(self, run_id, fence, *, expected_run, expected_manifest):
        with self.store.connect() as db:
            run = self._owned(db,run_id,fence)
            gold = db.execute("SELECT artifact FROM collection_steps WHERE run_id=%s AND stage='gold'", (run_id,)).fetchone()
            if gold is None or not isinstance(gold['artifact'].get('manifest_key'), str) or not gold['artifact']['manifest_key']:
                raise Conflict('A verified Gold manifest is required')
            stream = (run['namespace'],run['source'],run['scope'])
            db.execute('INSERT INTO collection_heads(namespace,source,scope) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING', stream)
            head = db.execute('SELECT run_id,manifest_key FROM collection_heads WHERE namespace=%s AND source=%s AND scope=%s FOR UPDATE',stream).fetchone()
            if head['run_id'] != expected_run or head['manifest_key'] != expected_manifest:
                raise Conflict('Published head changed during processing')
            # Recheck time after waiting for the publication lock.
            self._owned(db,run_id,fence)
            db.execute('UPDATE collection_heads SET run_id=%s,manifest_key=%s WHERE namespace=%s AND source=%s AND scope=%s',
                       (run_id,gold['artifact']['manifest_key'],*stream))
            db.execute("UPDATE collection_runs SET state='published',owner=NULL,lease_until=NULL WHERE id=%s",(run_id,))

    def published_artifact(self, namespace, source, scope):
        with self.store.connect() as db:
            return db.execute("""SELECT h.run_id,h.manifest_key,s.artifact
                FROM collection_heads h LEFT JOIN collection_steps s
                    ON s.run_id=h.run_id AND s.stage='gold'
                WHERE h.namespace=%s AND h.source=%s AND h.scope=%s""",
                (namespace, source, scope)).fetchone()

    def replace_published_manifest(self, run_id, *, expected_manifest, artifact):
        """Atomically adopt an already verified maintenance manifest.

        The caller must verify content and preserve the run identity before this
        metadata-only operation. Old references remain reachable in step history.
        """
        key = artifact.get('manifest_key')
        digest = artifact.get('fingerprint')
        if (not isinstance(key, str) or not key.startswith('gold/') or '..' in key.split('/')
                or not isinstance(digest, str) or re.fullmatch('[0-9a-f]{64}', digest) is None):
            raise ValueError('Expected a verified maintenance artifact')
        with self.store.connect() as db:
            # Same lock order as normal publication: run, then stream head.
            run = db.execute('SELECT * FROM collection_runs WHERE id=%s FOR UPDATE', (run_id,)).fetchone()
            if run is None or run['state'] != 'published':
                raise Conflict('Maintenance requires a published run')
            stream = (run['namespace'], run['source'], run['scope'])
            head = db.execute('SELECT run_id,manifest_key FROM collection_heads WHERE namespace=%s AND source=%s AND scope=%s FOR UPDATE', stream).fetchone()
            old = db.execute("SELECT artifact FROM collection_steps WHERE run_id=%s AND stage='gold'", (run_id,)).fetchone()
            if (head is None or head['run_id'] != run_id or head['manifest_key'] != expected_manifest
                    or old is None or old['artifact']['manifest_key'] != expected_manifest):
                raise Conflict('Published manifest changed during maintenance')
            if key == expected_manifest:
                if artifact != old['artifact']:
                    raise Conflict('Published artifacts must be immutable')
                return False
            db.execute("""INSERT INTO collection_step_history(run_id,stage,artifact,fence,reason)
                VALUES (%s,'gold',%s,%s,'MAINTENANCE_PUBLICATION')""",
                (run_id, Jsonb(old['artifact']), run['fence']))
            db.execute("UPDATE collection_steps SET artifact=%s,finished_at=clock_timestamp() WHERE run_id=%s AND stage='gold'",
                       (Jsonb(artifact), run_id))
            db.execute('UPDATE collection_heads SET manifest_key=%s WHERE namespace=%s AND source=%s AND scope=%s',
                       (key, *stream))
            return True
