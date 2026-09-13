"""Google Drive API client for metadata extraction and document retrieval."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any, Self

import httpx
from google.auth import crypt, jwt

from .observability import outbound_headers, stage

if TYPE_CHECKING:
    from .config import Settings

GOOGLE_DOCS_MIME_TYPES: set[str] = {
    "application/vnd.google-apps.document",
    "application/vnd.google-apps.spreadsheet",
    "application/vnd.google-apps.presentation",
}


class GoogleDriveClient:
    """Google Drive REST API v3 client using httpx and service account JWT authentication."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        credentials_json = getattr(settings, "google_drive_credentials_json", None)
        if credentials_json is None:
            raise RuntimeError("GOOGLE_DRIVE_CREDENTIALS_JSON must be configured")
        if hasattr(credentials_json, "get_secret_value"):
            raw_credentials = credentials_json.get_secret_value()
        elif isinstance(credentials_json, str):
            raw_credentials = credentials_json
        elif isinstance(credentials_json, dict):
            raw_credentials = None
            self._service_account_info: dict[str, Any] = credentials_json
        else:
            raw_credentials = str(credentials_json)

        if raw_credentials is not None:
            self._service_account_info = json.loads(raw_credentials)

        self._client = client
        self._owns_client = client is None
        self._access_token: str | None = None
        self._token_expiry: float = 0.0
        self._signer: crypt.RSASigner | None = None

    async def __aenter__(self) -> Self:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60, follow_redirects=True)
        return self

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    @property
    def _http_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("GoogleDriveClient must be used as an async context manager")
        return self._client

    async def _get_access_token(self) -> str:
        """Create a signed JWT and exchange it for an OAuth2 access token, caching for its lifetime."""
        now = time.time()
        if self._access_token is not None and now < (self._token_expiry - 60):
            return self._access_token

        if self._signer is None:
            self._signer = crypt.RSASigner.from_service_account_info(self._service_account_info)  # type: ignore[no-untyped-call]

        iat = int(now)
        payload: dict[str, Any] = {
            "iss": self._service_account_info["client_email"],
            "scope": "https://www.googleapis.com/auth/drive.readonly",
            "aud": "https://oauth2.googleapis.com/token",
            "iat": iat,
            "exp": iat + 3600,
        }
        signed_jwt = jwt.encode(self._signer, payload)  # type: ignore[no-untyped-call]
        assertion = signed_jwt.decode("utf-8") if isinstance(signed_jwt, bytes) else str(signed_jwt)

        response = await self._http_client.post(
            "https://oauth2.googleapis.com/token",
            headers=outbound_headers({"Content-Type": "application/x-www-form-urlencoded"}),
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )
        response.raise_for_status()
        token_data: dict[str, Any] = response.json()
        access_token = str(token_data["access_token"])
        expires_in = float(token_data.get("expires_in", 3600))
        self._access_token = access_token
        self._token_expiry = now + expires_in
        return access_token

    async def get_file_metadata(self, file_id: str) -> dict[str, str]:
        """Fetch metadata for a Drive file."""
        token = await self._get_access_token()
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}"
        response = await self._http_client.get(
            url,
            params={"fields": "id,name,mimeType,modifiedTime"},
            headers=outbound_headers({"Authorization": f"Bearer {token}"}),
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return {str(k): str(v) for k, v in data.items()}

    async def download_file(self, file_id: str) -> tuple[bytes, str, str]:
        """Download file content, exporting Google Workspace documents to plain text."""
        with stage("gdrive.download", provider="gdrive"):
            metadata = await self.get_file_metadata(file_id)
            filename = metadata.get("name", file_id)
            mime_type = metadata.get("mimeType", "application/octet-stream")
            token = await self._get_access_token()
            headers = outbound_headers({"Authorization": f"Bearer {token}"})

            if mime_type in GOOGLE_DOCS_MIME_TYPES:
                export_url = f"https://www.googleapis.com/drive/v3/files/{file_id}/export"
                response = await self._http_client.get(
                    export_url,
                    params={"mimeType": "text/plain"},
                    headers=headers,
                    follow_redirects=True,
                )
                response.raise_for_status()
                return response.content, filename, "text/plain"

            download_url = f"https://www.googleapis.com/drive/v3/files/{file_id}"
            response = await self._http_client.get(
                download_url,
                params={"alt": "media"},
                headers=headers,
                follow_redirects=True,
            )
            response.raise_for_status()
            return response.content, filename, mime_type
