"""Workspace portfolio selections over the shared source catalog."""
from alembic import op
revision = '0005_workspace_portfolios'
down_revision = '0004_workspace_costs'
branch_labels = None
depends_on = None

def upgrade():
    op.execute('''CREATE TABLE workspace_portfolios (
      workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id),
      all_catalog BOOLEAN NOT NULL,
      pool_ids JSONB NOT NULL,
      version INTEGER NOT NULL CHECK(version>0));''')

def downgrade():
    raise RuntimeError('Preserve portfolio selections with a forward migration.')
