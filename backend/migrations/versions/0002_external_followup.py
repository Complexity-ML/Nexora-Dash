"""Track administrative decisions received outside SAM; never infer an approval."""
from alembic import op
revision = '0002_external_followup'
down_revision = '0001_business'
branch_labels = None
depends_on = None

def upgrade():
    op.execute('''
        ALTER TABLE cases DROP CONSTRAINT cases_status_check;
        ALTER TABLE cases ADD COLUMN legacy_status TEXT;
        ALTER TABLE cases ADD COLUMN document_reference TEXT;
        ALTER TABLE cases ADD COLUMN external_decision TEXT CHECK(external_decision IN ('accepted','refused','revision_requested'));
        ALTER TABLE cases ADD COLUMN sent_on DATE;
        ALTER TABLE cases ADD COLUMN responded_on DATE;
        ALTER TABLE cases ADD COLUMN completed_on DATE;
        ALTER TABLE cases ADD COLUMN actual_quantity INTEGER CHECK(actual_quantity>=0);
        UPDATE cases SET legacy_status=status, status='preparing', version=version+1;
        ALTER TABLE cases ADD CONSTRAINT cases_status_check CHECK(status IN ('preparing','sent','response_received','completed'));
    ''')

def downgrade():
    # A rollback must not silently discard external references or reported actions.
    raise RuntimeError('Forward migration required: administrative follow-up records must be preserved.')
