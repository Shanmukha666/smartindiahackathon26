"""Add DPDP ownership, legal holds, and retention support.

Revision ID: 20260906_0006
Revises: 20260906_0005
"""
from alembic import op

revision = "20260906_0006"
down_revision = "20260906_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE qa_log ADD COLUMN user_id TEXT")
    op.execute("ALTER TABLE qa_log ADD COLUMN legal_hold BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE escalations ADD COLUMN user_id TEXT")
    op.execute("CREATE INDEX ix_qa_log_user_id_created_at ON qa_log (user_id, created_at)")
    op.execute("CREATE INDEX ix_escalations_user_id ON escalations (user_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_escalations_user_id")
    op.execute("DROP INDEX IF EXISTS ix_qa_log_user_id_created_at")
    op.execute("ALTER TABLE escalations DROP COLUMN IF EXISTS user_id")
    op.execute("ALTER TABLE qa_log DROP COLUMN IF EXISTS legal_hold")
    op.execute("ALTER TABLE qa_log DROP COLUMN IF EXISTS user_id")
