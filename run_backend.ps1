# Script to run IP-SAKTI Sahayak backend on host (Windows PowerShell)

$env:APP_NAME = "IP-SAKTI Sahayak"
$env:DATABASE_URL = "postgresql://postgres:local-demo-postgres-password@localhost:5432/ipsakti"
$env:DEPLOYMENT_ENVIRONMENT = "local"
$env:DEMO_MODE = "true"
$env:ENABLE_DEV_SESSION_ENDPOINT = "true"
$env:ALLOW_STUB_CONNECTORS = "true"
$env:JWT_SIGNING_KEY = "local-demo-signing-key-with-at-least-32-characters"
$env:CREDENTIAL_KEK_SECRET_RESOURCE = "projects/local/secrets/credential-kek/versions/latest"
$env:VOYAGE_API_URL = "https://api.voyageai.com/v1/embeddings"
$env:VOYAGE_MODEL = "voyage-3-large"
$env:COHERE_API_URL = "https://api.cohere.com/v2/rerank"
$env:COHERE_MODEL = "rerank-v3.5"
$env:MIN_RELEVANCE = "0.35"
$env:WEAK_RERANKER_SCORE = "0.35"
$env:OTEL_SERVICE_NAME = "ip-sakti-sahayak-backend"
$env:OTEL_EXPORTER_OTLP_ENDPOINT = "http://localhost:4317"
$env:OTEL_TRACES_EXPORTER = "none"
$env:OTEL_METRICS_EXPORTER = "none"

Write-Host "Starting IP-SAKTI Sahayak backend on http://127.0.0.1:8000 ..." -ForegroundColor Cyan
Set-Location -Path "$PSScriptRoot\backend"
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
