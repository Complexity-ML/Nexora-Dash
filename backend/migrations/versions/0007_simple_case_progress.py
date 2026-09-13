"""Add an in-progress state without rewriting historical administrative records."""
from alembic import op
revision = '0007_simple_case_progress'
down_revision = '0006_demo_generations'
branch_labels = None
depends_on = None

def upgrade():
    op.execute("ALTER TABLE cases DROP CONSTRAINT cases_status_check")
    op.execute("ALTER TABLE cases ADD CONSTRAINT cases_status_check CHECK(status IN ('preparing','in_progress','sent','response_received','completed'))")

def downgrade():
    raise RuntimeError('Use a forward migration to preserve case history.')
