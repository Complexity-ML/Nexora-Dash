"""Operational presence of periodic recovery workers, separate from run leases."""
from alembic import op
revision = '0014_recovery_workers'
down_revision = '0013_recovery_rotation'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE recovery_workers (
        id TEXT PRIMARY KEY, namespace TEXT NOT NULL, source TEXT NOT NULL, scope TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('working','waiting','stopped','failed')),
        heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        pass_started_at TIMESTAMPTZ, pass_finished_at TIMESTAMPTZ,
        next_pass_at TIMESTAMPTZ, last_outcome TEXT,
        started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());
        CREATE INDEX recovery_workers_stream ON recovery_workers(namespace,source,scope,started_at);''')


def downgrade():
    op.execute('DROP TABLE recovery_workers')
