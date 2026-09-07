import asyncio

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import main
from app.auth import current_user
from app.config import Settings


def test_dev_session_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.setattr(main.settings, "enable_dev_session_endpoint", False)
    assert TestClient(main.app).post("/auth/dev-session").status_code == 404


def test_dev_session_issues_a_usable_short_lived_token(monkeypatch) -> None:
    monkeypatch.setattr(main.settings, "enable_dev_session_endpoint", True)
    client = TestClient(main.app)
    response = client.post("/auth/dev-session")
    assert response.status_code == 200
    token = response.json()["access_token"]
    request = type("Request", (), {"headers": {"Authorization": f"Bearer {token}"}})()
    assert asyncio.run(current_user(request)).startswith("local-")


def test_production_rejects_dev_session_endpoint() -> None:
    with pytest.raises(ValidationError, match="ENABLE_DEV_SESSION_ENDPOINT"):
        Settings(
            app_name="test",
            database_url="postgresql://localhost/test",
            jwt_signing_key="x" * 32,
            credential_kek_secret_resource="projects/test/secrets/kek/versions/latest",
            voyage_api_url="https://example.test",
            voyage_model="test",
            otel_service_name="test",
            otel_exporter_otlp_endpoint="https://example.test",
            otel_traces_exporter="none",
            deployment_environment="production",
            allowed_origins=["https://app.example.test"],
            trusted_hosts=["api.example.test"],
            notification_provider="webhook",
            notification_webhook_url="https://example.test/notify",
            rate_limit_backend="gateway",
            enable_dev_session_endpoint=True,
        )
