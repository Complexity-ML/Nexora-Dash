"""Shared workspace cost assumptions, stored as integer euro cents."""
from alembic import op
revision = '0004_workspace_costs'
down_revision = '0003_analysis_settings'
branch_labels = None
depends_on = None

def upgrade():
    op.execute('''CREATE TABLE workspace_costs (
        workspace_id TEXT NOT NULL REFERENCES workspaces(id),
        pool_id TEXT NOT NULL,
        annual_unit_cents BIGINT CHECK(annual_unit_cents>=0 AND annual_unit_cents<=1000000000),
        version INTEGER NOT NULL CHECK(version>0),
        updated_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY(workspace_id,pool_id));''')

def downgrade():
    raise RuntimeError('Preserve shared assumptions through a forward migration.')
