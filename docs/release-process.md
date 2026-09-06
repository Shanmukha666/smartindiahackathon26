# Release process and rollback

## Release identities

An application release is an **annotated, signed** Git tag in the form `vMAJOR.MINOR.PATCH`. The tag is the immutable image tag for both frontend and backend. A corpus release is the set of committed corpus files and their frontmatter `version_tag` values; record its Git commit and source publication references in the release ticket. Database releases are identified by the Alembic head revision.

Never use `latest` as a release identity.

## Staging to production checklist

- [ ] Create and sign the annotated application tag; record its commit SHA.
- [ ] Record corpus commit, each changed instrument/version tag, source URL, retrieval date, Legal Corpus Reviewer, and dedicated corpus PR in the release ticket.
- [ ] Run lint, type checks, full tests, red-team tests, and dependency audits.
- [ ] Compile the Alembic migration plan (`alembic upgrade head --sql`) and review every destructive or locking operation.
- [ ] Take/verify a Cloud SQL point-in-time-recovery checkpoint and record the Alembic current revision.
- [ ] Deploy and ingest the exact tagged corpus in staging; run `python scripts/release_check.py` and smoke tests.
- [ ] Review retrieval/answer behavior and the corpus change/review queue in staging.
- [ ] Open the production workflow with the tag, select `production`, and type `APPROVE-PRODUCTION`.
- [ ] An authorized release manager must approve the protected GitHub `production` environment. Configure that environment with required reviewers; workflow YAML alone cannot grant or simulate approval.
- [ ] Run the reviewed migration plan, deploy the exact tagged images, ingest the approved corpus, then run post-deploy smoke and `release_check.py`.
- [ ] Monitor alerts and key request paths; close the release only after the observation window.

## Database migration procedure

Production schema changes are **expand/contract** releases. Apply backward-compatible additions first; deploy code; contract only in a later release. Before any migration, take a PITR checkpoint and run `alembic current` plus `alembic upgrade head --sql`. Run migrations once, under the production runtime/database identity, not from application request handlers. Verify with:

```bash
DATABASE_URL=... uv run alembic current
DATABASE_URL=... uv run python scripts/release_check.py
```

Do not run an Alembic downgrade that drops `qa_log`, `corpus_*`, or audit columns in production. If an incompatible migration has already run, restore to a separate Cloud SQL instance/PITR point, validate it, and perform a controlled cutover.

## Independent rollback

### Application

Redeploy the prior immutable backend/frontend image tags. Cloud Run revisions make this reversible without changing corpus data or the schema. Use this when the schema remains backward-compatible.

### Database

For a safe, explicitly reviewed reversible migration, run `alembic downgrade <known_revision>` only after confirming its downgrade has no destructive data loss. Otherwise use the restore-and-cutover process above. Application rollback comes first when it is compatible with the current schema.

### Corpus

Corpus rollback does not delete the bad revision. Activate the retained prior version atomically:

```bash
DATABASE_URL=... uv run python -m app.cli rollback-corpus \
  --instrument "Patents Act, 1970" --version-tag "India Code 2024"
DATABASE_URL=... uv run python scripts/release_check.py
```

The command flips `is_active`, retains every document/chunk, and adds a `corpus_change_log` event. Retrieval resumes from the restored active chunks. `qa_log.retrieved_chunk_ids`, answer payloads, request IDs, and timestamps are immutable records; corpus rollback never rewrites or deletes them. `release_check.py` verifies that every retained QA chunk ID still resolves and that no instrument has multiple active revisions.

## Incident record

For every rollback record the triggering alert, application tag, migration revision, corpus version tags, approval, executor, timestamps, verification results, and the follow-up corrective release.
