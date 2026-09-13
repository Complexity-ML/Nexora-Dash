"""Remove obsolete SQL projections, never lake history or recovery metadata."""
import json
from app.collection.dependencies import dependency_inventory
from app.collection.retention import journal_roots
from app.collection.maintenance_lock import protect_deletion


def referenced_runs(values, candidates):
    """Conservative: protect any known inventory ID appearing in metadata."""
    found=set()
    def walk(value):
        if isinstance(value,str) and value in candidates: found.add(value)
        elif isinstance(value,dict):
            for item in value.values(): walk(item)
        elif isinstance(value,list):
            for item in value: walk(item)
    walk(values)
    return found


def prune_index_cache(store,lake,*,apply=False):
    with store.connect() as db:
        db.execute("SET LOCAL lock_timeout='5s'")
        protect_deletion(db)
        # Block publication/checkpoint changes while determining retention roots.
        db.execute('LOCK TABLE inventory_runs,inventory_heads,collection_runs,collection_heads,collection_steps,collection_step_history,bi_snapshots IN SHARE ROW EXCLUSIVE MODE')
        if db.execute("SELECT 1 FROM collection_runs WHERE namespace=%s AND state='running' LIMIT 1",(lake.prefix,)).fetchone():
            raise RuntimeError('Collection is running; retry index maintenance later')
        runs=[dict(r) for r in db.execute('SELECT id,manifest_key FROM inventory_runs WHERE namespace=%s',(lake.prefix,))]
        ids={str(r['id']) for r in runs}
        protected={str(r['run_id']) for r in db.execute('SELECT run_id FROM inventory_heads WHERE namespace=%s',(lake.prefix,))}
        roots=journal_roots(db,lake.prefix)['artifacts']
        dependencies=dependency_inventory(lake,roots)
        documents=roots+[json.loads(lake.get_bytes(key)) for key in dependencies['objects'] if key.endswith('.json')]
        protected |= referenced_runs(documents,ids)
        protected |= {str(r['id']) for r in runs if r['manifest_key'] in dependencies['objects']}
        obsolete=sorted(ids-protected)
        count=db.execute('SELECT count(*) AS n FROM inventory_entities WHERE run_id=ANY(%s::text[])',(obsolete,)).fetchone()['n']
        if apply and obsolete:
            db.execute('DELETE FROM inventory_entities WHERE run_id=ANY(%s::text[])',(obsolete,))
            db.execute('DELETE FROM inventory_software_summaries WHERE run_id=ANY(%s::text[])',(obsolete,))
        return {'namespace':lake.prefix,'protected_runs':sorted(protected),'obsolete_runs':obsolete,
                'projection_rows':count,'applied':apply,
                'lake_objects_deleted':0,'run_metadata_deleted':0}
