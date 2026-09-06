"""Store original and translated query forms for Indic-language auditability.

Revision ID: 20260906_0007
Revises: 20260906_0006
"""

from alembic import op

revision = "20260906_0007"
down_revision = "20260906_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE qa_log ADD COLUMN original_query TEXT")
    op.execute("ALTER TABLE qa_log ADD COLUMN translated_query TEXT")
    op.execute("ALTER TABLE qa_log ADD COLUMN query_language TEXT NOT NULL DEFAULT 'en'")
    op.execute("UPDATE qa_log SET original_query = question, translated_query = question WHERE original_query IS NULL")
    op.execute("ALTER TABLE qa_log ALTER COLUMN original_query SET NOT NULL")
    op.execute("ALTER TABLE qa_log ALTER COLUMN translated_query SET NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE qa_log DROP COLUMN IF EXISTS query_language")
    op.execute("ALTER TABLE qa_log DROP COLUMN IF EXISTS translated_query")
    op.execute("ALTER TABLE qa_log DROP COLUMN IF EXISTS original_query")
