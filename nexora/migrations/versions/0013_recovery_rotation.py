"""Rotate recovery inspection so blocked runs cannot starve later collections."""
from alembic import op
revision = '0013_recovery_rotation'
down_revision = '0012_inventory_software_summary'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('ALTER TABLE collection_runs ADD COLUMN recovery_checked_at TIMESTAMPTZ')


def downgrade():
    # Only scheduling order is lost; source, checkpoints and lineage remain intact.
    op.execute('ALTER TABLE collection_runs DROP COLUMN recovery_checked_at')
