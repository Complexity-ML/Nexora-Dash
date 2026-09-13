"""Expiring and revocable technical reader credentials for BI audiences."""
from alembic import op
revision = '0017_bi_readers'
down_revision = '0016_bi_publications'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE bi_readers (
        id TEXT PRIMARY KEY, namespace TEXT NOT NULL, audience TEXT NOT NULL,
        token_hash TEXT NOT NULL UNIQUE CHECK(token_hash ~ '^[0-9a-f]{64}$'),
        created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        expires_at TIMESTAMPTZ NOT NULL, revoked_at TIMESTAMPTZ,
        CHECK(expires_at > created_at));''')


def downgrade():
    raise RuntimeError('BI reader revocations must not be discarded by rollback')
