"""Internal BI publication metadata; this does not grant reader access."""
import json
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.bi.snapshot import export_pool_snapshot
from app.collection.journal import Conflict, fingerprint
from app.collection.runner import encoded


def prepare_pool_snapshot(lake, journal, **selection):
    exported = export_pool_snapshot(lake, journal, **selection)
    return register_snapshot(lake, journal, exported)


def prepare_inventory_snapshot(lake, journal, **selection):
    from app.bi.inventory_snapshot import export_inventory_snapshot
    return register_snapshot(lake, journal, export_inventory_snapshot(lake, journal, **selection))


def register_snapshot(lake, journal, exported):
    manifest = exported['manifest']
    sid = str(uuid4())
    artifact = {key:exported[key] for key in ('manifest_key','fingerprint')}
    with journal.store.connect() as db:
        db.execute('''INSERT INTO bi_snapshots(id,namespace,audience,source,scope,source_run_id,source_manifest_key,artifact)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)''',
            (sid,lake.prefix,manifest['audience'],manifest['source'],manifest['scope'],
             manifest['source_run_id'],exported['source_manifest_key'],Jsonb(artifact)))
    return {'snapshot_id':sid, **artifact}


def publish_snapshot(lake, journal, snapshot_id, *, expected_snapshot):
    with journal.store.connect() as db:
        snapshot = db.execute('SELECT * FROM bi_snapshots WHERE id=%s AND namespace=%s',
                              (snapshot_id,lake.prefix)).fetchone()
        if snapshot is None:
            raise ValueError('Unknown BI snapshot')
        artifact = snapshot['artifact']
        manifest = json.loads(lake.get_bytes(artifact['manifest_key']))
        if fingerprint(encoded(manifest)) != artifact['fingerprint']:
            raise ValueError('BI manifest integrity check failed')
        source = db.execute('''SELECT run_id,manifest_key FROM collection_heads
            WHERE namespace=%s AND source=%s AND scope=%s FOR UPDATE''',
            (lake.prefix,snapshot['source'],snapshot['scope'])).fetchone()
        if not source or source['run_id'] != snapshot['source_run_id'] or source['manifest_key'] != snapshot['source_manifest_key']:
            raise Conflict('Source publication changed; prepare a new BI snapshot')
        audience = (lake.prefix,snapshot['audience'])
        db.execute('INSERT INTO bi_publications(namespace,audience) VALUES (%s,%s) ON CONFLICT DO NOTHING', audience)
        head = db.execute('SELECT snapshot_id FROM bi_publications WHERE namespace=%s AND audience=%s FOR UPDATE', audience).fetchone()
        if head['snapshot_id'] == snapshot_id:
            return snapshot_id
        if head['snapshot_id'] != expected_snapshot:
            raise Conflict('BI publication changed')
        db.execute('UPDATE bi_publications SET snapshot_id=%s WHERE namespace=%s AND audience=%s', (snapshot_id,*audience))
    return snapshot_id


def publication(journal, *, namespace, audience):
    """Read one consistent pointer and artifact; caller enforces audience access."""
    with journal.store.connect() as db:
        return db.execute("""SELECT s.id AS snapshot_id,s.artifact FROM bi_publications p
            JOIN bi_snapshots s ON s.id=p.snapshot_id
            WHERE p.namespace=%s AND p.audience=%s""", (namespace,audience)).fetchone()


def prepare_license_snapshot(lake,journal,**selection):
    from app.bi.license_snapshot import export_license_snapshot
    return register_snapshot(lake,journal,export_license_snapshot(lake,journal,**selection))
