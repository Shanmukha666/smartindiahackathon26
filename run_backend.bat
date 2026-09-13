@echo off
set APP_NAME=IP-SAKTI Sahayak
set DATABASE_URL=postgresql://postgres:local-demo-postgres-password@localhost:5432/ipsakti
set DEPLOYMENT_ENVIRONMENT=local
set DEMO_MODE=true
set ENABLE_DEV_SESSION_ENDPOINT=true
set ALLOW_STUB_CONNECTORS=true
set JWT_SIGNING_KEY=local-demo-signing-key-with-at-least-32-characters
set CREDENTIAL_KEK_SECRET_RESOURCE=projects/local/secrets/credential-kek/versions/latest
set VOYAGE_API_URL=https://api.voyageai.com/v1/embeddings
set VOYAGE_MODEL=voyage-3-large
set COHERE_API_URL=https://api.cohere.com/v2/rerank
set COHERE_MODEL=rerank-v3.5
set MIN_RELEVANCE=0.35
set WEAK_RERANKER_SCORE=0.35
set OTEL_SERVICE_NAME=ip-sakti-sahayak-backend
set OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
set OTEL_TRACES_EXPORTER=none
set OTEL_METRICS_EXPORTER=none

echo Starting IP-SAKTI Sahayak backend on http://127.0.0.1:8000 ...
cd /d "%~dp0backend"
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
