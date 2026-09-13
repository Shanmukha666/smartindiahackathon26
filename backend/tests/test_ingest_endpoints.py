from __future__ import annotations

from collections.abc import Generator
from typing import Self

import pytest
from starlette.testclient import TestClient

from app import main
from app.auth import issue_test_token
from app.main import app, get_repository


class FakeRepository:
    @classmethod
    async def create(cls, database_url: str) -> FakeRepository:
        return cls()

    async def close(self) -> None:
        pass

    async def get_active_document(self, instrument: str) -> None:
        return None

    async def upsert_document(self, source: object, chunks: list[object], embeddings: object) -> object:
        from app.ingest import IngestOutcome
        return IngestOutcome("inserted", len(chunks))


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    app.dependency_overrides[get_repository] = lambda: FakeRepository()
    yield TestClient(app)
    app.dependency_overrides.pop(get_repository, None)


def test_ingest_endpoints_require_auth(client: TestClient) -> None:
    for route in ["/ingest/gdrive", "/ingest/url", "/ingest/upload"]:
        res = client.post(route, json={})
        assert res.status_code == 401


def test_ingest_endpoints_require_legal_reviewer_role(client: TestClient) -> None:
    token = issue_test_token("test-user", roles=["regular_user"])
    headers = {"Authorization": f"Bearer {token}"}
    for route in ["/ingest/gdrive", "/ingest/url", "/ingest/upload"]:
        res = client.post(route, json={}, headers=headers)
        assert res.status_code == 403


def test_ingest_endpoints_rejected_in_demo_mode(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    token = issue_test_token("test-reviewer", roles=["legal_reviewer"])
    headers = {"Authorization": f"Bearer {token}"}
    
    monkeypatch.setattr(main.settings, "demo_mode", True)
    res = client.post("/ingest/url", json={"url": "https://example.com"}, headers=headers)
    assert res.status_code == 400
    assert "disabled in DEMO_MODE" in res.json()["detail"]


def test_ingest_upload_endpoint_success(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import SecretStr
    token = issue_test_token("test-reviewer", roles=["legal_reviewer"])
    headers = {"Authorization": f"Bearer {token}"}

    monkeypatch.setattr(main.settings, "demo_mode", False)
    monkeypatch.setattr(main.settings, "voyage_api_key", SecretStr("fake-voyage-key"))
    
    class FakeVoyageEmbedder:
        def __init__(self, settings: object, client: object = None) -> None:
            pass
        async def __aenter__(self) -> Self:
            return self
        async def __aexit__(self, *args: object) -> None:
            pass
        async def embed(self, texts: list[str]) -> list[list[float]]:
            return [[0.01] * 1024 for _ in texts]

    monkeypatch.setattr(main, "VoyageEmbedder", FakeVoyageEmbedder)
    
    payload = {
        "filename": "custom_act.txt",
        "content": "Section 1. Short title.\nThis Act may be called the Custom Act.",
        "jurisdiction": "IN"
    }
    res = client.post("/ingest/upload", json=payload, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "inserted"
    assert data["chunk_count"] >= 1
    assert data["pinecone_synced"] is False
