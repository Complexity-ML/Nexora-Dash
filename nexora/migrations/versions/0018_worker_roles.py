"""Distinguish daily collection presence from recovery presence."""
from alembic import op
revision = '0018_worker_roles'
down_revision = '0017_bi_readers'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE recovery_workers ADD COLUMN kind TEXT NOT NULL DEFAULT 'recovery' CHECK(kind IN ('recovery','daily'))")


def downgrade():
    raise RuntimeError('Worker roles must not be discarded by rollback')
