"""Paid-source connectors, consent enforcement, and envelope encryption."""
from __future__ import annotations

import base64
import hashlib
import os
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class PaidSourceConnector(ABC):
    provider: str

    @abstractmethod
    async def search(self, query: str) -> list[dict[str, str]]: ...


class StubPaidSourceConnector(PaidSourceConnector):
    provider = "stub"

    async def search(self, query: str) -> list[dict[str, str]]:
        return [{"title": "Stub paid-source result", "query": query, "provider": self.provider}]


class KekProvider(Protocol):
    async def get_kek(self) -> tuple[str, bytes]: ...


class SecretManagerKekProvider:
    """Loads a base64 256-bit KEK from Google Secret Manager at runtime."""
    def __init__(self, secret_resource: str) -> None:
        self._resource = secret_resource

    async def get_kek(self) -> tuple[str, bytes]:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        response = client.access_secret_version(request={"name": self._resource})
        return self._resource.rsplit("/", 1)[-1], base64.b64decode(response.payload.data, validate=True)


def envelope_encrypt(plaintext: str, kek: bytes) -> dict[str, bytes]:
    if len(kek) != 32:
        raise ValueError("Credential KEK must be a 256-bit key")
    data_key, data_nonce, kek_nonce = os.urandom(32), os.urandom(12), os.urandom(12)
    return {"ciphertext": AESGCM(data_key).encrypt(data_nonce, plaintext.encode(), None), "data_nonce": data_nonce,
            "encrypted_data_key": AESGCM(kek).encrypt(kek_nonce, data_key, None), "kek_nonce": kek_nonce}


async def consent_event(user_id: str, provider: str, query: str) -> dict[str, str]:
    return {
        "user_id": user_id,
        "provider": provider,
        "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "timestamp": datetime.now(UTC).isoformat(),
    }
