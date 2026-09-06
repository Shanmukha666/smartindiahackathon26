# Launch-readiness review — release candidate

**Review date:** 2026-09-06  
**Decision:** **NOT PRODUCTION-READY**  
**Reason:** Launch blockers remain open. Production approval must not be granted until every blocker below is closed and re-verified.

## Evidence recorded

| Area | Evidence | Result | Scope/limitation |
| --- | --- | --- | --- |
| Functional API and regression behavior | `pytest` | 42 passed | Unit/API doubles; no deployed dependencies. |
| Security/red team | `tests/test_red_team.py` (included in 42) | 5 passed | Covers prompt extraction/injection, unsupported-topic abstention, and fabricated citations. |
| Retrieval, citation, abstention, classification evaluator | `python eval/run_eval.py --offline --compare-to eval/baseline.json` | 27/27 cases; citation correctness 1.000; abstention precision/recall 1.000; classification accuracy 1.000 | Offline evaluator returns fixture citations/abstentions; it does **not** exercise Voyage, Cohere, Claude, Postgres, or production corpus. |
| Backend quality | Ruff, mypy, pip-audit | Passed; no known Python dependency vulnerabilities | Static/local only. |
| Frontend quality | `npm ci`, lint, typecheck, `npm audit --audit-level=high` | Passed; 0 vulnerabilities | Frontend is built, but no production hosting resource is present in Terraform. |
| Migration plan | `alembic upgrade head --sql` | Generated successfully | No staging/production database migration was executed in this review. |
| Observability | Source/config review | Stage spans/metrics, dashboards, and alerts defined | Production collector endpoint and alert routing were not verified. |

## Requirement assessment

| Requirement | Assessment |
| --- | --- |
| Classification | Deterministic decision-tree evaluation is 18/18 correct. This does not measure a free-text classifier because classification is user-driven via decision-tree answers. |
| Retrieval quality | Not established for the release candidate: no live corpus/provider evaluation or relevance measurements were run. |
| Citation correctness | Validation logic and adversarial fabricated-citation test pass; live model/corpus correctness is unverified. |
| Abstention | Fixture/offline and adversarial unsupported-topic tests pass; live-model abstention is unverified. |
| Escalation | Unit workflow passes; authenticated production webhook delivery and persistence/ownership are unverified. |
| Multilingual | Unit paths pass; Bhashini translation/ASR/TTS was not exercised against the issued production account. |
| Paid-source consent | Consent gate/envelope-encryption code exists, but the only connector is a stub and production rejects it. No production paid-source capability is available. |
| Privacy | Encryption/logging design is sound in reviewed code; ownership persistence for QA and escalations is incomplete. |
| Security | Local controls pass; required live IAM, HTTPS, CORS, rate-limit gateway, penetration testing, and protected-environment approval remain unverified. |
| Reliability/performance | No load, soak, failover, restore, or SLO verification evidence. |

## Open findings

Every unresolved item has an owner, severity, and explicit disposition.

| ID | Finding | Owner | Severity | Disposition / closure evidence |
| --- | --- | --- | --- | --- |
| LR-01 | `qa_log` and `escalations` have `user_id` columns, but `/ask` and `/escalate` do not authenticate/bind callers or pass a user ID into their persistence methods. `/privacy/export` and deletion filter by `user_id`, so those records cannot be reliably exported/deleted by their owner. | Backend + Privacy | Critical | **Launch blocker.** Require authenticated ownership binding, migration/backfill policy, two-user isolation tests, and privacy export/deletion verification. |
| LR-02 | No live release-candidate evaluation against the deployed corpus, PostgreSQL, Voyage, Cohere, Claude, or Bhashini was run. Offline metrics are fixture-derived. | ML/RAG + QA | Critical | **Launch blocker.** Run/record live evaluation with pinned corpus/app tag; meet approved thresholds for retrieval relevance, citations, abstention, multilingual behavior, and latency. |
| LR-03 | Terraform deploys only the backend Cloud Run service. The frontend image is built/pushed but no frontend hosting/service/CDN deployment is defined. | Platform | High | **Launch blocker.** Provision secured frontend hosting/routing and run browser/API end-to-end smoke tests. |
| LR-04 | Paid-source production search is unavailable: only `StubPaidSourceConnector` exists and production rejects it. | Product + Integrations | High | **Launch blocker.** Either implement an allowlisted production connector with credential retrieval, consent/audit tests, and provider-response validation, or formally remove paid-source search from launch scope. |
| LR-05 | Production observability defaults still require replacing the placeholder OTLP endpoint and configuring managed collector, dashboards, alert routing, on-call receiver, and alert drill. | SRE | High | **Launch blocker.** Provide deployed dashboard/alert links and successful test alerts for retrieval/LLM/citation/latency/escalation signals. |
| LR-06 | Production security prerequisites cannot be verified from this workspace: Secret Manager secret versions/IAM, protected GitHub `production` reviewers, HTTPS/gateway CORS/host settings, distributed limiter, and non-public Cloud Run invocation path. | Security + Platform | High | **Launch blocker.** Complete release checklist with screenshots/commands and independent review. |
| LR-07 | Required human security tests remain pending: BOLA/BOPLA, sensitive-flow abuse, paid-provider/tool-result abuse, secret rotation/backup/log-redaction validation. | Security | High | **Launch blocker.** Complete signed penetration/security review; document fixes or approved exception. |
| LR-08 | No load, soak, provider-outage, Cloud SQL failover, backup restore/PITR, or rollback drill evidence. | SRE + QA | High | **Launch blocker.** Meet approved capacity/SLO targets and execute a restore plus application/database/corpus rollback drill. |
| LR-09 | Migration plan is compilable, but the release workflow does not execute and verify migrations against staging/production as a managed release step. | Platform + DBA | High | **Launch blocker.** Run a staging migration, `release_check.py`, and a reviewed production migration procedure with PITR checkpoint before cutover. |
| LR-10 | Production smoke test accepts `401` for `/escalate`, so it proves IAM reachability but not authenticated escalation persistence/webhook delivery. | Backend + QA | Medium | **Launch blocker.** Use a dedicated short-lived application test JWT/service identity and verify an end-to-end escalation with a non-sensitive test record. |
| LR-11 | Evaluation corpus is small (27 deterministic cases) and lacks live multilingual, paid-source, provider failure, and corpus-rollback behavior coverage. | ML/RAG + QA | Medium | **Accepted post-launch risk only after LR-02 is closed.** Expand to representative, independently reviewed release-gate data and track quality drift. |
| LR-12 | Test output contains third-party FastAPI/Starlette deprecation warnings and a local Windows pytest-cache permission warning. | Backend | Low | **Accepted post-launch risk.** Track framework upgrade and CI cache cleanup; neither changes test outcomes. |

## Required decision

No release manager may mark this candidate production-ready or approve the protected production environment while LR-01 through LR-10 remain open. After closure, append links to evidence, rerun the live evaluator and smoke tests against the immutable application/corpus release IDs, and issue a new dated review.
