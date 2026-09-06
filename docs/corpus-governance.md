# Corpus governance

## Authority and pull requests

The **Legal Corpus Reviewer** role (the GitHub team `@ip-sakti/legal-corpus-reviewers`) is the only role authorized to add, modify, approve, or merge a file below `/corpus`. Engineers may improve ingestion tooling but may not alter legal source content or its provenance.

Each corpus change is a dedicated PR: it may contain `/corpus` files and the required provenance metadata only. The PR must use the corpus-change template, receive approval from a different Legal Corpus Reviewer through CODEOWNERS, and be merged only after required checks pass. Repository administrators must configure GitHub branch protection to require CODEOWNERS review and prohibit bypasses for this path.

Every corpus frontmatter block records an authoritative `source_url` and the UTC `retrieved_at` date. This provenance is ingested with the document version; combined with the PR review record and `corpus_change_log`, it provides an auditable account of what changed, the source reviewed, and when it was retrieved.

## Quarterly source review

The Legal Corpus Reviewer on rotation reviews every active source URL at least once each calendar quarter, including sources with no re-ingestion request. Record the outcome (amended, repealed, corrected, inaccessible, or unchanged), retrieval date, reviewer, and supporting official publication in the quarterly review issue. Amendments require a dedicated corpus PR; an unchanged review still updates the review register, not the legal text. An inaccessible or unverifiable authoritative source is an operational incident and blocks relying on that source for a release.

The scheduled `corpus-source-review` workflow opens the quarterly review issue. It is a reminder and audit trigger, not proof that a legal review occurred; a Legal Corpus Reviewer must close the issue only after every source has a recorded outcome.

## Phase 2.3 stale-answer queue

Every `qa_review_queue` item must reach `reviewed` or `dismissed`; neither status may be set without the reviewer, timestamp, and an evidence-based resolution note. The Legal Corpus Reviewer owns legal correctness; the RAG/QA owner owns remediation and re-evaluation. Review the queue weekly and at every corpus release. Escalate items older than five business days to the legal lead; items older than ten business days block releases affecting that instrument. Preserve closed items for audit—never delete them to make the queue appear empty.
