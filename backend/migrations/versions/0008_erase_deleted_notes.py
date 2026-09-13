"""Erase content of previously deleted notes, preserving case history metadata."""
from alembic import op
revision = '0008_erase_deleted_notes'
down_revision = '0007_simple_case_progress'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""UPDATE events AS note
        SET payload=(note.payload::jsonb - 'text')::text
        WHERE note.action IN ('case.comment','comment.edited')
        AND EXISTS (SELECT 1 FROM events AS deletion
            WHERE deletion.action='comment.deleted'
            AND deletion.workspace_id=note.workspace_id
            AND deletion.case_id=note.case_id
            AND deletion.payload::jsonb->>'comment_id' = CASE
                WHEN note.action='case.comment' THEN note.id::text
                ELSE note.payload::jsonb->>'comment_id' END)""")


def downgrade():
    raise RuntimeError('Note erasure is irreversible. Use a forward migration; rollback to 0007 is unsafe.')
