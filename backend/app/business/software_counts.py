"""Rebuildable software counts pinned to an immutable inventory run."""
from psycopg.types.json import Jsonb


def compute_counts(db, run_id, pools=None):
    scope = ' AND pool_ids && %s::text[]' if pools is not None else ''
    params = [run_id] + ([pools] if pools is not None else [])
    indexed = db.execute("""WITH machines AS (
        SELECT id,data FROM inventory_entities WHERE run_id=%s AND entity='machines'""" + scope + """
    ), installed AS (
        SELECT id,jsonb_array_elements(data->'installed_products') AS product
        FROM machines WHERE data ? 'installed_products'
        UNION ALL
        SELECT id,jsonb_build_object('name',jsonb_array_elements_text(
            jsonb_build_array(data->>'operating_system') || COALESCE(data->'services','[]'::jsonb) || COALESCE(data->'applications','[]'::jsonb)
        )) AS product FROM machines WHERE NOT data ? 'installed_products'
    ) SELECT product,count(DISTINCT id) AS machines FROM installed
    WHERE product->>'name' IS NOT NULL AND product->>'name'<>'' AND product->>'name'<>'Inventory agent'
    GROUP BY product ORDER BY machines DESC,product->>'name'""", params).fetchall()
    return [{**row['product'], 'machines':row['machines']} for row in indexed]


def rebuild_summary(db, run_id):
    if not db.execute('SELECT id FROM inventory_runs WHERE id=%s FOR SHARE', (run_id,)).fetchone():
        raise ValueError('Unknown inventory run')
    rows = compute_counts(db, run_id)
    db.execute('INSERT INTO inventory_software_summaries VALUES (%s,%s) ON CONFLICT(run_id) DO UPDATE SET products=EXCLUDED.products',
               (run_id, Jsonb(rows)))
    return rows


def read_counts(db, run_id, pools=None):
    cached = db.execute('SELECT products FROM inventory_software_summaries WHERE run_id=%s', (run_id,)).fetchone()
    rows = cached['products'] if cached else None
    # Legacy names alone cannot safely filter an aggregate by a selected pool.
    if rows is None or (pools is not None and any(not r.get('software_id') for r in rows)):
        rows = compute_counts(db, run_id, pools)
    if pools is not None:
        selected = set(pools)
        rows = [r for r in rows if not r.get('software_id') or (r.get('license_pool_id') or r['software_id']) in selected]
    return rows
