import asyncio

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import main
from app.auth import audit_record_user, current_user
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


def test_demo_repository_supports_ephemeral_visible_demo_actions() -> None:
    from app.demo import DemoRepository

    repository = DemoRepository()
    first_id = asyncio.run(repository.create_escalation("session", "question", "reason", "normal"))
    asyncio.run(repository.log_paid_source_consent("local-user", "stub", {}))
    assert first_id >= 1


def test_demo_repository_never_persists_privacy_or_paid_source_data() -> None:
    from app.demo import DemoRepository

    repository = DemoRepository()
    asyncio.run(repository.store_paid_source_credential())
    exported = asyncio.run(repository.export_user_data("demo-user"))
    assert exported["demo_mode"] is True
    assert exported["qa_log"] == []
    assert asyncio.run(repository.list_review_queue(100)) == []
    assert asyncio.run(repository.resolve_review_queue_item(1, "reviewed", "reviewer", "checked")) is False
    assert asyncio.run(repository.delete_user_data("demo-user")) == {
        "qa_log": 0,
        "escalations": 0,
        "paid_source_credentials": 0,
    }


def test_staging_and_production_require_an_identity_for_persisted_audit_records(monkeypatch) -> None:
    request = type("Request", (), {"headers": {}})()
    monkeypatch.setattr(main.settings, "deployment_environment", "production")
    with pytest.raises(Exception, match="Bearer token required"):
        asyncio.run(audit_record_user(request))
