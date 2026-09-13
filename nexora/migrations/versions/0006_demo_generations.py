"""Atomically select a validated fictional dataset without deleting prior data."""
from alembic import op
revision='0006_demo_generations'
down_revision='0005_workspace_portfolios'
branch_labels=None
depends_on=None

def upgrade():
    op.execute('''CREATE TABLE demo_generation (
      id INTEGER PRIMARY KEY CHECK(id=1), prefix TEXT NOT NULL,
      version INTEGER NOT NULL CHECK(version>=0));
      INSERT INTO demo_generation VALUES(1,'',0);
      CREATE TABLE demo_generation_events (
      id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      actor_id TEXT NOT NULL REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL,
      payload JSONB NOT NULL);''')

def downgrade():
    raise RuntimeError('Keep dataset activation history using a forward migration.')
