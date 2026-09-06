"""Record source retrieval provenance and review-queue closure evidence."""

from alembic import op

revision = "20260906_0008"
down_revision = "20260906_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE corpus_documents ADD COLUMN source_retrieved_at DATE NOT NULL DEFAULT CURRENT_DATE")
    op.execute("ALTER TABLE corpus_documents ALTER COLUMN source_retrieved_at DROP DEFAULT")
    op.execute("ALTER TABLE qa_review_queue ADD COLUMN resolved_by TEXT")
    op.execute("ALTER TABLE qa_review_queue ADD COLUMN resolution_note TEXT")
    op.execute("""ALTER TABLE qa_review_queue ADD CONSTRAINT review_queue_closure_evidence
                  CHECK ((status = 'pending' AND reviewed_at IS NULL AND resolved_by IS NULL AND resolution_note IS NULL)
                     OR (status IN ('reviewed', 'dismissed') AND reviewed_at IS NOT NULL
                         AND resolved_by IS NOT NULL AND resolution_note IS NOT NULL))""")


def downgrade() -> None:
    op.execute("ALTER TABLE qa_review_queue DROP CONSTRAINT IF EXISTS review_queue_closure_evidence")
    op.execute("ALTER TABLE qa_review_queue DROP COLUMN IF EXISTS resolution_note")
    op.execute("ALTER TABLE qa_review_queue DROP COLUMN IF EXISTS resolved_by")
    op.execute("ALTER TABLE corpus_documents DROP COLUMN IF EXISTS source_retrieved_at")
