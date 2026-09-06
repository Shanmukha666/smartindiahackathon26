import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import app


def test_production_rejects_unsafe_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEPLOYMENT_ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SIGNING_KEY", "x" * 32)
    with pytest.raises(ValidationError):
        Settings(
            app_name="test", database_url="postgresql://localhost/test", voyage_api_url="https://example.test",
            voyage_model="test", otel_service_name="test", otel_exporter_otlp_endpoint="http://localhost:4317",
            otel_traces_exporter="none",
        )


def test_test_credentials_cannot_be_used_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEPLOYMENT_ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SIGNING_KEY", "test-signing-key-not-for-production")
    monkeypatch.setenv("ALLOWED_ORIGINS", '["https://app.example.test"]')
    monkeypatch.setenv("TRUSTED_HOSTS", '["app.example.test"]')
    monkeypatch.setenv("NOTIFICATION_PROVIDER", "webhook")
    monkeypatch.setenv("NOTIFICATION_WEBHOOK_URL", "https://hooks.example.test/notify")
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "gateway")
    with pytest.raises(ValidationError):
        Settings(app_name="test", database_url="postgresql://localhost/test", voyage_api_url="https://example.test",
                 voyage_model="test", otel_service_name="test", otel_exporter_otlp_endpoint="http://localhost:4317",
                 otel_traces_exporter="none")


def test_sensitive_routes_require_authentication_and_responses_have_security_headers() -> None:
    client = TestClient(app)
    admin = client.get("/admin/review-queue")
    escalation = client.post("/escalate", json={"session_id": "s", "question": "q", "reason": "r"})
    health = client.get("/health")
    assert admin.status_code == 401
    assert escalation.status_code == 401
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["x-frame-options"] == "DENY"


def test_request_body_limit_is_enforced_before_validation() -> None:
    response = TestClient(app).post("/retrieve", content="x" * 64, headers={"Content-Length": "9000001"})
    assert response.status_code == 413
