"""Persist availability attempts even before a source snapshot exists."""
from alembic import op
revision = '0015_daily_collection_polls'
down_revision = '0014_recovery_workers'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE daily_collection_polls (
        namespace TEXT NOT NULL, source TEXT NOT NULL, scope TEXT NOT NULL, day DATE NOT NULL,
        attempt BIGINT NOT NULL DEFAULT 1,
        status TEXT NOT NULL CHECK(status IN ('fetching','source_pending','published','quality_rejected','conflict','failed')),
        started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(), finished_at TIMESTAMPTZ,
        run_id TEXT REFERENCES collection_runs(id),
        PRIMARY KEY(namespace,source,scope,day))''')


def downgrade():
    op.execute('DROP TABLE daily_collection_polls')
