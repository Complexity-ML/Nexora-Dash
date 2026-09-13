"""Versioned software counts to avoid expanding every machine on each request."""
from alembic import op
revision = '0012_inventory_software_summary'
down_revision = '0011_collection_rebases'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE inventory_software_summaries (
        run_id TEXT PRIMARY KEY REFERENCES inventory_runs(id) ON DELETE CASCADE,
        products JSONB NOT NULL CHECK(jsonb_typeof(products)='array'))''')


def downgrade():
    op.execute('DROP TABLE inventory_software_summaries')
