"""Indexed current inventory projection; historical observations stay in MinIO."""
from alembic import op
revision = '0009_inventory_index'
down_revision = '0008_erase_deleted_notes'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''
      CREATE TABLE inventory_runs (
        id TEXT PRIMARY KEY, namespace TEXT NOT NULL, captured_at TIMESTAMPTZ NOT NULL,
        source TEXT NOT NULL, manifest_key TEXT NOT NULL);
      CREATE TABLE inventory_heads (
        namespace TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES inventory_runs(id));
      CREATE TABLE inventory_entities (
        run_id TEXT NOT NULL REFERENCES inventory_runs(id), entity TEXT NOT NULL,
        id TEXT NOT NULL, name TEXT NOT NULL, subsidiary TEXT, country TEXT,
        region TEXT, site TEXT, kind TEXT, os TEXT, environment TEXT,
        pool_ids TEXT[] NOT NULL, search TEXT NOT NULL, data JSONB NOT NULL,
        PRIMARY KEY(run_id,entity,id));
      CREATE INDEX inventory_location_idx ON inventory_entities(run_id,entity,subsidiary,country,region,site);
      CREATE INDEX inventory_name_idx ON inventory_entities(run_id,entity,name,id);
      CREATE INDEX inventory_pools_idx ON inventory_entities USING GIN(pool_ids);
      CREATE INDEX inventory_kind_idx ON inventory_entities(run_id,entity,kind,environment);
    ''')


def downgrade():
    op.execute('DROP TABLE inventory_entities; DROP TABLE inventory_heads; DROP TABLE inventory_runs;')
