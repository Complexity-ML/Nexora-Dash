"""Keep superseded recovery checkpoints for audit and retention."""
from alembic import op
revision='0011_collection_rebases'
down_revision='0010_collection_journal'
branch_labels=None
depends_on=None


def upgrade():
    op.execute('''CREATE TABLE collection_step_history (
      id BIGSERIAL PRIMARY KEY, run_id TEXT NOT NULL REFERENCES collection_runs(id),
      stage TEXT NOT NULL, artifact JSONB NOT NULL, fence BIGINT NOT NULL,
      reason TEXT NOT NULL, archived_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());
      CREATE INDEX collection_history_run ON collection_step_history(run_id);''')


def downgrade():
    raise RuntimeError('Recovery lineage must not be discarded by rollback')
