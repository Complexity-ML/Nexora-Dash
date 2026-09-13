"""Durable collection runs, checkpoints and fenced publication pointers."""
from alembic import op
revision = '0010_collection_journal'
down_revision = '0009_inventory_index'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''
    CREATE TABLE collection_runs (
      id TEXT PRIMARY KEY, namespace TEXT NOT NULL, source TEXT NOT NULL,
      scope TEXT NOT NULL, snapshot_id TEXT NOT NULL, source_revision TEXT NOT NULL,
      fingerprint TEXT NOT NULL CHECK(fingerprint ~ '^[0-9a-f]{64}$'),
      mapping_version TEXT NOT NULL, schema_version TEXT NOT NULL,
      state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','running','retryable','rejected','published')),
      fence BIGINT NOT NULL DEFAULT 0, owner TEXT, lease_until TIMESTAMPTZ,
      error_code TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
      UNIQUE(namespace,source,scope,snapshot_id,source_revision,mapping_version,schema_version));
    CREATE TABLE collection_steps (
      run_id TEXT NOT NULL REFERENCES collection_runs(id),
      stage TEXT NOT NULL CHECK(stage IN ('bronze','validated','silver','gold')),
      artifact JSONB NOT NULL CHECK(jsonb_typeof(artifact)='object'),
      finished_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
      PRIMARY KEY(run_id,stage));
    CREATE TABLE collection_heads (
      namespace TEXT NOT NULL, source TEXT NOT NULL, scope TEXT NOT NULL,
      run_id TEXT REFERENCES collection_runs(id), manifest_key TEXT,
      PRIMARY KEY(namespace,source,scope));
    CREATE INDEX collection_pending ON collection_runs(state,lease_until);
    ''')


def downgrade():
    # Losing recovery state could cause replay of already published collections.
    raise RuntimeError('Collection recovery metadata must not be discarded by rollback')
