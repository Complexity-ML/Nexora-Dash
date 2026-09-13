"""Persist shared analytical thresholds and their audit trail."""
from alembic import op
revision = '0003_analysis_settings'
down_revision = '0002_external_followup'
branch_labels = None
depends_on = None

def upgrade():
    op.execute("""
        CREATE TABLE analysis_settings (
            id INTEGER PRIMARY KEY CHECK(id=1),
            threshold DOUBLE PRECISION NOT NULL CHECK(threshold>0 AND threshold<=1),
            buffer DOUBLE PRECISION NOT NULL CHECK(buffer>=0 AND buffer<=1),
            version INTEGER NOT NULL CHECK(version>0));
        CREATE TABLE analysis_settings_events (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            actor_id TEXT NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL,
            payload TEXT NOT NULL);
    """)

def downgrade():
    raise RuntimeError('Preserve settings audit via a forward migration.')
