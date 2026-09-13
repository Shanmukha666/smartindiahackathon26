from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.gdrive import GoogleDriveClient


def make_test_settings(**kwargs: object) -> Settings:
    fake_creds = {
        "client_email": "test@project.iam.gserviceaccount.com",
        "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC7...\n-----END PRIVATE KEY-----\n",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    defaults: dict[str, object] = {
        "app_name": "test-app",
        "database_url": SecretStr("postgresql://localhost/test"),
        "jwt_signing_key": SecretStr("test-signing-key-not-for-production"),
        "credential_kek_secret_resource": "projects/test/secrets/credential-kek/versions/latest",
        "voyage_api_url": "https://api.voyageai.com/v1/embeddings",
        "voyage_model": "voyage-3-large",
        "otel_service_name": "test-service",
        "otel_exporter_otlp_endpoint": "http://localhost:4317",
        "otel_traces_exporter": "none",
        "google_drive_credentials_json": SecretStr(json.dumps(fake_creds)),
    }
    defaults.update(kwargs)
    return Settings(**defaults)  # type: ignore[arg-type]


def test_gdrive_missing_credentials() -> None:
    settings = make_test_settings(google_drive_credentials_json=None)
    with pytest.raises(RuntimeError, match="GOOGLE_DRIVE_CREDENTIALS_JSON must be configured"):
        GoogleDriveClient(settings)


@pytest.mark.asyncio
async def test_gdrive_metadata_and_download() -> None:
    settings = make_test_settings()

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "oauth2.googleapis.com/token" in url_str:
            return httpx.Response(200, json={"access_token": "fake-access-token", "expires_in": 3600})
        if "files/test-file-id?fields=" in url_str:
            return httpx.Response(200, json={
                "id": "test-file-id",
                "name": "patents_act.txt",
                "mimeType": "text/plain",
                "modifiedTime": "2026-01-01T00:00:00Z"
            })
        if "files/test-file-id?alt=media" in url_str:
            return httpx.Response(200, content=b"Section 3(p) full text content", headers={"Content-Type": "text/plain"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        gdrive = GoogleDriveClient(settings, client=client)
        # Mock _get_access_token directly to avoid RSA signer with dummy key
        async def fake_get_token() -> str:
            return "fake-access-token"
        gdrive._get_access_token = fake_get_token  # type: ignore[method-assign]
        meta = await gdrive.get_file_metadata("test-file-id")
        assert meta["name"] == "patents_act.txt"

        content, filename, mime_type = await gdrive.download_file("test-file-id")
        assert content == b"Section 3(p) full text content"
        assert filename == "patents_act.txt"
        assert mime_type == "text/plain"
