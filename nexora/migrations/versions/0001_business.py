"""Accounts, memberships, dossiers and immutable application audit trail."""
from alembic import op

revision = '0001_business'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''
        CREATE TABLE users (
            id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE CHECK(email=lower(email)),
            name TEXT NOT NULL, password TEXT NOT NULL);
        CREATE TABLE sessions (
            digest TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
            expires DOUBLE PRECISION NOT NULL);
        CREATE TABLE workspaces (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL);
        CREATE TABLE members (
            workspace_id TEXT REFERENCES workspaces(id), user_id TEXT REFERENCES users(id),
            role TEXT NOT NULL CHECK(role IN ('admin','analyst','reader')),
            PRIMARY KEY(workspace_id,user_id));
        CREATE TABLE cases (
            id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
            pool_id TEXT NOT NULL, title TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('open','in_review','approved','rejected')),
            assignee_id TEXT REFERENCES users(id), quantity INTEGER NOT NULL CHECK(quantity>=0),
            annual_unit_cents BIGINT NOT NULL CHECK(annual_unit_cents>=0), evidence TEXT NOT NULL,
            version INTEGER NOT NULL CHECK(version>0), created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL);
        CREATE TABLE events (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            workspace_id TEXT NOT NULL REFERENCES workspaces(id),
            case_id TEXT REFERENCES cases(id), actor_id TEXT NOT NULL REFERENCES users(id),
            action TEXT NOT NULL, payload TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL);
        CREATE INDEX cases_workspace ON cases(workspace_id);
        CREATE INDEX events_case ON events(case_id,id);
        CREATE INDEX sessions_expiry ON sessions(expires);
    ''')


def downgrade():
    for table in ('events','cases','members','workspaces','sessions','users'):
        op.execute(f'DROP TABLE {table}')
