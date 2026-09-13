"""Inventory all retained journal references; never authorize deletion."""
from app.collection.dependencies import dependency_inventory


def journal_roots(db, namespace):
    """Read roots in the caller transaction, including an exported backup snapshot."""
    rows = db.execute('''SELECT s.artifact FROM collection_steps s
        JOIN collection_runs r ON r.id=s.run_id WHERE r.namespace=%s
        UNION ALL
        SELECT s.artifact FROM collection_step_history s
        JOIN collection_runs r ON r.id=s.run_id WHERE r.namespace=%s''',
        (namespace, namespace)).fetchall()
    heads = db.execute('SELECT manifest_key FROM collection_heads WHERE namespace=%s AND manifest_key IS NOT NULL',
                       (namespace,)).fetchall()
    counts = db.execute('SELECT state,count(*) AS count FROM collection_runs WHERE namespace=%s GROUP BY state',
                        (namespace,)).fetchall()
    bi = db.execute('SELECT artifact FROM bi_snapshots WHERE namespace=%s', (namespace,)).fetchall()
    return {"artifacts": [row["artifact"] for row in rows + bi] + [dict(row) for row in heads],
            "runs_by_state": {r["state"]: r["count"] for r in counts}}


def journal_protection(lake, journal):
    with journal.store.connect() as db:
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        roots = journal_roots(db, lake.prefix)
    artifacts = roots["artifacts"]
    inventory = dependency_inventory(lake, artifacts)
    return {'namespace': lake.prefix, 'runs_by_state': roots['runs_by_state'],
            'root_artifacts': len(artifacts), **inventory,
            'deletion_authorized': False}
