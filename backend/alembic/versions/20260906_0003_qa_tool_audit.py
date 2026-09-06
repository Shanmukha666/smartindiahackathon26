"""Record bounded agent tool calls in QA audit logs.

Revision ID: 20260906_0003
Revises: 20260906_0002
Create Date: 2026-09-06
"""

from alembic import op

revision = "20260906_0003"
down_revision = "20260906_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE qa_log ADD COLUMN tool_calls JSONB NOT NULL DEFAULT '[]'::jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE qa_log DROP COLUMN IF EXISTS tool_calls")
