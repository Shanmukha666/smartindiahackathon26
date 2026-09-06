# IP-SAKTI Sahayak

Monorepo foundation for IP-SAKTI Sahayak:

- `backend`: FastAPI on Python 3.11, managed with `uv`.
- `frontend`: React, Vite, TypeScript, and Tailwind CSS.
- `infra`: Google Cloud Terraform for Cloud SQL PostgreSQL, pgvector, Artifact Registry, and Cloud Run.
- `docker-compose.yml`: local PostgreSQL with pgvector, backend hot reload, and frontend hot reload.
- Local observability: JSON backend logs, OpenTelemetry traces, and Jaeger.

No business workflows are included in this scaffold.

## Local development

Prerequisites: Docker Desktop, `uv`, Node.js 22+, and npm.

Start the complete local stack from the repository root:

```bash
copy .env.example .env
# Edit .env and set POSTGRES_PASSWORD to a local-only value.
docker compose up --build
```

When running outside Docker, start the backend on port 8000, then run `npm run dev` in `frontend`. To use another backend port, set `VITE_API_PROXY_TARGET`, for example `VITE_API_PROXY_TARGET=http://127.0.0.1:8010 npm run dev`.

Open the frontend at `http://localhost:5173`. The backend is available at `http://localhost:8000`; its liveness endpoint is `GET /health` and its database-backed readiness endpoint is `GET /ready`. View local traces at `http://localhost:16686`.

Retrieve corpus evidence with:

```bash
curl -X POST http://localhost:8000/retrieve \
	-H 'Content-Type: application/json' \
	-d '{"query":"traditional knowledge exclusion","jurisdiction":"IN"}'
```

`jurisdiction` accepts `IN`, `INTL`, or `BOTH`. Retrieval filters active documents by jurisdiction, combines pgvector cosine and PostgreSQL full-text ranks with reciprocal rank fusion, reranks the fused top 20 through Cohere, and returns at most five results. Results below `MIN_RELEVANCE` are omitted; the default is `0.35` and it can be changed through the environment or Terraform's `min_relevance` variable.

## Legal graph

The legal graph uses a relational adjacency model in PostgreSQL (`graph_entities` and
`graph_relationships`), rather than a separate graph database. This keeps graph updates
transactional with the existing corpus, uses the current PostgreSQL backup/access-control
investment, and supports future multi-hop traversal with recursive CTEs. Entity types are
`Instrument`, `Section`, `Treaty`, `FormulationCategory`, and `RegistryRecord`; supported
edge types are `CITES`, `SUPERSEDES`, `APPLIES_TO_CATEGORY`, and `CROSS_REFERENCES`.

The graph migration backfills the seeded corpus's Section 3(p) → `classical`
`APPLIES_TO_CATEGORY` edge and the Biological Diversity Act, 2002 → WIPO GRATK Treaty
`CROSS_REFERENCES` edge. The treaty is represented as a canonical graph entity because it
is not yet a corpus document.

When a corpus document changes, prior answers that cited its replaced chunks are added to
the PostgreSQL `qa_review_queue`. The invalidation also follows `SUPERSEDES` and
`CROSS_REFERENCES` graph edges to catch affected neighboring authorities. Administrators
can inspect pending items with `GET /admin/review-queue` (optionally `?limit=...`), rather
than silently serving those answers as current.

Ask a grounded question with the Claude-backed endpoint:

```bash
curl -X POST http://localhost:8000/ask \
	-H 'Content-Type: application/json' \
	-d '{"query":"What does Section 3(p) exclude?","jurisdiction":"IN","session_id":"demo-session"}'
```

`/ask` abstains before invoking Claude when retrieval is empty, validates every returned citation against the retrieved chunk IDs, downgrades unjustified high confidence when reranker scores are weak, and writes every attempt to `qa_log`. Every response includes the `Information only, not legal advice.` disclaimer.

Escalate a question with:

```bash
curl -X POST http://localhost:8000/escalate \
	-H 'Content-Type: application/json' \
	-d '{"session_id":"demo-session","question":"Which route applies?","reason":"abstained-answer","priority":"normal"}'
```

The response contains a database-backed `tracking_id`. `abstained-answer` escalations are raised to `high` priority unless the caller explicitly sends `urgent`. Escalations require an authenticated caller. Production requires `NOTIFICATION_PROVIDER=webhook`; logging notification and the stub paid connector are development/test-only and production startup rejects either configuration.

Classify a product through the YAML-driven decision tree:

```bash
curl -X POST http://localhost:8000/classify/next \
	-H 'Content-Type: application/json' \
	-d '{"session_id":"demo-classification","trail":[],"answer_index":null}'
```

Use each response's `options` to choose the next `answer_index` and send back the returned `trail`. A terminal response contains `regulatory_path`, `ip_posture`, and `abs_note` and is persisted to `classification_results`. Domain experts can edit `backend/classification_tree.yaml`; set `CLASSIFICATION_TREE_PATH` to load an alternate tree without changing Python code.

Every backend response includes an `X-Request-ID` header. Clients can provide that header to correlate their own request; otherwise the backend generates a UUID. Backend events are emitted as one-line JSON records containing the request ID and, when available, OpenTelemetry trace and span IDs. Logs deliberately exclude questions, answers, session/user IDs, credentials, authorization headers, and provider payloads; use the request ID plus trace ID to investigate a request.

## Observability

The full request path emits OpenTelemetry spans and latency/error metrics for classification, retrieval/search, embedding, reranking, LLM generation, citation validation, escalation, translation, and paid-source connectors. W3C trace context and `X-Request-ID` are propagated to outbound provider calls without forwarding inbound credentials. Local `docker compose up` exposes Jaeger at `:16686`, Prometheus at `:9090`, and Grafana at `:3000`; Grafana provisions the **IP-SAKTI Request Pipeline** dashboard and Prometheus loads alerts for retrieval/LLM failure rates, p95 latency, citation-validation failures, and escalation spikes.

For production, point `OTEL_EXPORTER_OTLP_ENDPOINT` at the managed collector and configure its OTLP receiver, metrics backend, trace backend, and alert notification receiver. Keep metric labels bounded: stage, provider, jurisdiction, input type, priority, and reason only. Do not add query text, user identifiers, session IDs, chunk content, credentials, or raw provider responses as trace attributes, metric labels, or log fields.

The backend reads configuration from process environment variables only; it does not load `.env` files itself. The root `.env` is used only by Docker Compose and is ignored by Git.

For a local demo without PostgreSQL or provider keys, set `DEMO_MODE=true` with `DEPLOYMENT_ENVIRONMENT=development`. It performs a lexical search over the bundled corpus and returns a clearly labeled, cited extract; it is not an LLM and production startup rejects this setting.

The production frontend image proxies `/api/*` to `BACKEND_ORIGIN`; set that variable to the HTTPS URL of the deployed backend service. Its Docker default (`http://backend:8000`) is only for the local Compose network.

Indic-language queries use Bhashini before retrieval, so the English corpus remains the sole evidence source and its chunk IDs remain unchanged. Set `BHASHINI_API_KEY` and (when issued for the account) `BHASHINI_USER_ID`. The backend also provides `POST /speech/transcribe` and `POST /speech/synthesize` for Bhashini ASR/TTS. QA audit rows retain `original_query`, `translated_query`, and `query_language`.

Ingest the seeded public-source corpus after applying the database migration and setting `VOYAGE_API_KEY` in the ignored root `.env`:

```bash
docker compose exec backend ingest --corpus-dir /corpus
```

Corpus content is governed by the Legal Corpus Reviewer role, not engineers. See [corpus governance](docs/corpus-governance.md) for mandatory dedicated PRs, provenance, quarterly source review, and stale-answer queue closure.

The command prints JSON counters for inserted, changed, unchanged documents and generated chunks. It hashes each document body, skips unchanged versions, and records changed versions in `corpus_change_log` before inserting their new chunks and Voyage embeddings.

## Evaluation

The seeded evaluator is in `backend/eval`. It contains 27 YAML cases covering all six classification categories, four grounded questions, and five abstention cases including an adversarial off-topic prompt. Run the deterministic CI check with:

```bash
cd backend
uv run python eval/run_eval.py --offline --compare-to eval/baseline.json
```

For a live backend evaluation, omit `--offline` and set `EVAL_BASE_URL`. The report includes citation correctness, abstention precision/recall, and classification accuracy. Pull requests compare citation correctness and abstention precision against the baseline stored on `main`; regression tolerance is controlled by the `EVAL_MAX_REGRESSION` GitHub repository variable and defaults to `0.05`.

For backend work outside Compose:

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

Run the database migrations with `DATABASE_URL` in the process environment:

```bash
cd backend
uv run alembic upgrade head
```

To roll back the latest migration, use `uv run alembic downgrade -1`. The migration creates the pgvector extension and the corpus, audit, QA, escalation, and grant tables. The embedding index is HNSW with cosine distance; `text_search` is a generated `tsvector` indexed with GIN.

For frontend work outside Compose:

```bash
cd frontend
npm install
npm run dev
```

## Terraform environments

Terraform state is separated with workspaces. The `staging` workspace is intended for lower-cost, scale-to-zero Cloud Run and zonal Cloud SQL. The `production` workspace uses regional Cloud SQL, point-in-time recovery, deletion protection, and a nonzero Cloud Run minimum instance count.

Initialize Terraform and create the workspaces:

```bash
cd infra
terraform init
terraform workspace new staging
terraform workspace new production
```

Select one workspace, copy its variable example, set the GCP project and image, then plan/apply:

```bash
terraform workspace select staging
terraform plan -var-file=staging.tfvars
terraform apply -var-file=staging.tfvars
```

Use `production.tfvars` with the `production` workspace for production. The first apply requires the Google Cloud CLI because Terraform runs `gcloud sql databases execute-sql` to enable the `vector` extension after Cloud SQL is provisioned. The executing identity needs permission to administer Cloud SQL and the project APIs must be enabled.

## Secrets

## Paid-source credentials and key rotation

Paid-source routes require a bearer JWT and explicit per-call consent. Credentials are envelope-encrypted: a random data key encrypts the credential with AES-256-GCM; only the encrypted data key, nonces, ciphertext, and Secret Manager KEK version are stored in PostgreSQL. Plaintext credentials are never logged or persisted. The KEK is loaded at runtime from the configured Google Secret Manager version.

To rotate: create a new 32-byte base64 KEK version in Secret Manager; deploy with `CREDENTIAL_KEK_SECRET_RESOURCE` pointing to it; re-submit/re-encrypt each credential (which records the new `kek_version`); validate provider access; then disable the previous Secret Manager version. Do not destroy the prior key until every old credential has been re-encrypted.

Secrets must never be committed to source, `.env.example`, Terraform variable files, or GitHub workflow YAML.

## Production security gates

Production startup fails closed unless explicit trusted hosts and CORS origins are supplied, a 32+ character non-test JWT signing key is present, edge/gateway rate limiting is declared, a webhook notification secret is configured, and stub connectors are disabled. Cloud Run is no longer publicly invokable; place it behind the approved authenticated gateway/load balancer, which must enforce the declared distributed rate limit. The deployment workflow runs endpoint smoke checks after deployment.

## Releases and rollback

See [the release process](docs/release-process.md) for signed application tags, corpus/version records, staging-to-production approval, migration checks, and independently scoped application, database, and corpus rollback procedures.

| Secret | Local development | Staging and production |
| --- | --- | --- |
| `POSTGRES_PASSWORD` | Root ignored `.env`, used only by Compose | Generated and stored as the `${environment}-database-url` Google Secret Manager version by Terraform |
| `DATABASE_URL` | Supplied to the backend container by Compose; set manually in the process environment for non-Compose runs | Injected into Cloud Run from Google Secret Manager, never as a Terraform plain-text environment value |
| `ANTHROPIC_API_KEY` | Optional ignored environment variable | `${environment}-anthropic-api-key` in Google Secret Manager; add a secret version before deploying Cloud Run |
| `VOYAGE_API_KEY` | Optional ignored environment variable | `${environment}-voyage-api-key` in Google Secret Manager; add a secret version before deploying Cloud Run |
| `COHERE_API_KEY` | Required for `/retrieve`, stored in the ignored root `.env` | `${environment}-cohere-api-key` in Google Secret Manager; add a secret version before deploying Cloud Run |
| `ANTHROPIC_API_KEY` | Required for `/ask`, stored in the ignored root `.env` | `${environment}-anthropic-api-key` in Google Secret Manager; add a secret version before deploying Cloud Run |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Not used locally | GitHub Actions variable containing the full Workload Identity Federation provider resource name |
| `GCP_SERVICE_ACCOUNT` | Not used locally | GitHub Actions variable containing the deployer service-account email |

Create the AI-key versions outside the repository, for example with `gcloud secrets versions add`. Grant access only to the deployment/runtime identities that need it. `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_SERVICE_NAME` are configuration, not secrets; the OTLP endpoint is configured through Terraform and should be replaced before production.

Before applying either Cloud Run workspace, add the required API-key versions from your local secret environment:

```bash
printf '%s' "$ANTHROPIC_API_KEY" | gcloud secrets versions add ip-sakti-staging-anthropic-api-key --data-file=-
printf '%s' "$VOYAGE_API_KEY" | gcloud secrets versions add ip-sakti-staging-voyage-api-key --data-file=-
printf '%s' "$COHERE_API_KEY" | gcloud secrets versions add ip-sakti-staging-cohere-api-key --data-file=-
```

Use the `ip-sakti-production-*` names for the production workspace. Do not put these values in Terraform variables, tfvars files, or workflow YAML.

## Production observability

The backend uses a generic OTLP gRPC exporter by default. Set the Terraform variables `otel_service_name`, `otel_exporter_otlp_endpoint`, and `otel_traces_exporter` in the environment tfvars file to point at the production observability backend. The placeholder endpoint is `https://otel-collector.example.com:4317` and must be replaced before production deployment. Set `otel_traces_exporter = "none"` to disable trace exporting where required.

## Clean local teardown

Stop containers and remove the local database volume when you want a clean reset:

```bash
docker compose down --volumes --remove-orphans
```

To remove only running containers while preserving database data, use `docker compose down`. Terraform teardown is separate and destructive; select the intended workspace and run `terraform destroy -var-file=<environment>.tfvars` only when the corresponding cloud environment should be removed.

## GitHub Actions

Pull requests run backend linting, mypy, tests, frontend ESLint and TypeScript checks, and both Docker image builds without pushing.

Merges to `main` repeat those checks, provision the staging Artifact Registry if needed, push tagged backend and frontend images, and apply the `staging` Terraform workspace. The deployment job uses GitHub's OIDC token and Google Cloud Workload Identity Federation (WIF), not a service-account key. Configure these GitHub Actions variables (repository variables, or environment variables when staging and production use separate Google Cloud projects):

| Variable | Value |
| --- | --- |
| `GCP_PROJECT_ID` | The Google Cloud project ID. |
| `GCP_REGION` | Optional target Cloud Run/Artifact Registry region. It defaults to `asia-south1`, matching Terraform. |
| `GCP_TERRAFORM_STATE_BUCKET` | Name of the pre-created, private GCS bucket used only for Terraform state. |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Full provider resource name, for example `projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/POOL_ID/providers/PROVIDER_ID`. |
| `GCP_SERVICE_ACCOUNT` | Email of the WIF-bound deployment service account, for example `DEPLOYER_NAME@PROJECT_ID.iam.gserviceaccount.com`. |

The variables are intentionally not defaulted in source (except the documented region default). The workflow validates them before authentication, so a missing value fails with an actionable message instead of passing an empty input to `google-github-actions/auth`. Create the state bucket before the first workflow run, enable bucket versioning and uniform bucket-level access, and grant the deployment service account only the storage permissions required for that bucket. The workflow uses the prefix `ip-sakti-sahayak/staging` or `ip-sakti-sahayak/production` to isolate state.

The following values are project-specific and cannot be derived from this repository. They are GitHub Actions **Variables**, not Secrets:

| Variable | Repository source | Obtain it from |
| --- | --- | --- |
| `GCP_PROJECT_ID` | `infra/variables.tf` declares it as required; both example tfvars files deliberately use a placeholder. | The target project’s ID in Google Cloud Console or `gcloud projects list`. |
| `GCP_TERRAFORM_STATE_BUCKET` | No `google_storage_bucket` resource or Terraform backend is defined. | The name of the private/versioned GCS bucket a project administrator creates for Terraform state. |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | No WIF pool or provider Terraform resource is defined. | The full provider resource name after a project administrator creates the GitHub OIDC WIF provider. |
| `GCP_SERVICE_ACCOUNT` | Terraform creates `backend_runtime` only; it does not create a deployment account. | The email of the separately created WIF-bound deployment service account. |

The WIF provider must map `assertion.repository` to `attribute.repository` and restrict the accepted repository to `Shanmukha666/smartindiahackathon26`. Its service-account binding must grant `roles/iam.workloadIdentityUser` to that repository principal set.

For production, also configure these non-secret GitHub Actions variables. They are passed to Terraform as `TF_VAR_*` environment variables because the repository contains only placeholder tfvars examples:

| Variable | Value |
| --- | --- |
| `TF_VAR_ALLOWED_ORIGINS` | A JSON array of the real allowed frontend origins, for example `["https://app.your-domain.example"]`. |
| `TF_VAR_TRUSTED_HOSTS` | A JSON array of the real backend hosts, for example `["api.your-domain.example"]`. |

The workflow selects `notification_provider=webhook` and `rate_limit_backend=gateway` for production, as Terraform requires. `TF_VAR_ALLOWED_ORIGINS` and `TF_VAR_TRUSTED_HOSTS` must not use placeholder or wildcard values. They are deployment configuration, not credentials.

### Google Cloud WIF bootstrap

This Terraform configuration currently provisions the application runtime service account only; it does **not** create a WIF pool, WIF provider, or GitHub deployment service account. A Google Cloud project administrator must bootstrap those resources outside this deployment workflow, because the workflow cannot authenticate through a provider that does not yet exist. Do not create or commit a service-account JSON key.

The WIF provider must map `assertion.repository` to `attribute.repository` and restrict it to `Shanmukha666/smartindiahackathon26`. Bind the deployment service account with `roles/iam.workloadIdentityUser` for this member:

```
principalSet://iam.googleapis.com/projects/PROJECT_NUMBER/locations/global/workloadIdentityPools/POOL_ID/attribute.repository/Shanmukha666/smartindiahackathon26
```

Grant that deployment account only the additional project/resource roles needed to run the Terraform plan and push/deploy the images; have a platform administrator review those grants. After bootstrap, copy the provider's full resource name and deployment service-account email into the GitHub Actions variables above. No private credential is needed or should be stored in GitHub.

The workflow has no GitHub Actions Secrets. Provider API keys, JWT signing material, the credential KEK, and the notification webhook are separate Google Secret Manager secret versions; create their values in the target Google Cloud project before Cloud Run is deployed. They must not be copied into GitHub variables, Terraform files, or workflow YAML.

Production is never deployed by a merge. Use the **Deploy** workflow's `workflow_dispatch`, choose `production`, and protect the corresponding GitHub environment with required reviewers. Choosing `staging` manually is also supported.

## Pre-commit secret scanning

Install pre-commit, install the hook, and scan existing files once:

```bash
pipx install pre-commit
pre-commit install
pre-commit run --all-files
```

The tracked [.pre-commit-config.yaml](.pre-commit-config.yaml) runs gitleaks on staged changes and blocks commits containing likely API keys or other credentials.
