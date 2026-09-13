"""Retain BI snapshot lineage and audience publication pointers."""
from alembic import op
revision = '0016_bi_publications'
down_revision = '0015_daily_collection_polls'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE bi_snapshots (
        id TEXT PRIMARY KEY, namespace TEXT NOT NULL, audience TEXT NOT NULL,
        source TEXT NOT NULL, scope TEXT NOT NULL,
        source_run_id TEXT NOT NULL REFERENCES collection_runs(id),
        source_manifest_key TEXT NOT NULL, artifact JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());
        CREATE INDEX bi_snapshots_audience ON bi_snapshots(namespace,audience);
        CREATE TABLE bi_publications (
        namespace TEXT NOT NULL, audience TEXT NOT NULL,
        snapshot_id TEXT REFERENCES bi_snapshots(id),
        PRIMARY KEY(namespace,audience));''')


def downgrade():
    raise RuntimeError('BI publication lineage must not be discarded by rollback')
