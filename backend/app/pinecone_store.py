from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Protocol, Self

import httpx

from .observability import outbound_headers, stage

if TYPE_CHECKING:
    from .config import Settings

OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
OPENAI_EMBEDDING_DIMENSION = 1536
PINECONE_CONTROL_PLANE_URL = "https://api.pinecone.io"
PINECONE_BATCH_SIZE = 100


class Embedder(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...
    async def embed_query(self, query: str) -> list[float]: ...


class VectorStore(Protocol):
    async def upsert(
        self,
        ids: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        metadatas: Sequence[dict[str, str]],
    ) -> int: ...

    async def query(
        self,
        embedding: Sequence[float],
        top_k: int = 5,
        filter: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]: ...


class OpenAIEmbedder:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        if settings.openai_api_key is None:
            raise RuntimeError("OPENAI_API_KEY must be set to generate embeddings")
        self._api_key = settings.openai_api_key.get_secret_value()
        self._model = settings.openai_embedding_model
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> Self:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if self._client is None:
            raise RuntimeError("OpenAIEmbedder must be used as an async context manager")
        if not texts:
            return []

        with stage("embedding.provider", provider="openai", input_count=len(texts)):
            response = await self._client.post(
                OPENAI_EMBEDDINGS_URL,
                headers=outbound_headers({
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                }),
                json={"input": list(texts), "model": self._model},
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(
                    f"OpenAI embeddings request failed ({response.status_code}): {response.text}"
                ) from exc

        payload = response.json()
        data = payload.get("data", [])
        embeddings = [item["embedding"] for item in sorted(data, key=lambda item: item.get("index", 0))]
        if len(embeddings) != len(texts):
            raise RuntimeError(
                f"OpenAI returned {len(embeddings)} embeddings, expected {len(texts)}"
            )
        if any(len(embedding) != OPENAI_EMBEDDING_DIMENSION for embedding in embeddings):
            raise RuntimeError(
                f"OpenAI returned an embedding with unexpected dimension (expected {OPENAI_EMBEDDING_DIMENSION})"
            )
        return embeddings

    async def embed_query(self, query: str) -> list[float]:
        embeddings = await self.embed([query])
        if not embeddings:
            raise RuntimeError("OpenAI failed to generate embedding for query")
        return embeddings[0]


class PineconeStore:
    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
        *,
        index_host: str | None = None,
    ) -> None:
        if settings.pinecone_api_key is None:
            raise RuntimeError("PINECONE_API_KEY must be set to access Pinecone")
        self._api_key = settings.pinecone_api_key.get_secret_value()
        self._index_name = (
            getattr(settings, "pinecone_index", None)
            or getattr(settings, "pinecone_index_name", "airag-1536")
        )
        self._client = client
        self._owns_client = client is None
        self._index_host: str | None = (
            index_host.removeprefix("https://").removeprefix("http://").rstrip("/")
            if index_host
            else None
        )

    async def __aenter__(self) -> Self:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _resolve_index_host(self) -> str:
        if self._index_host is not None:
            return self._index_host
        if self._client is None:
            raise RuntimeError("PineconeStore must be used as an async context manager")

        response = await self._client.get(
            f"{PINECONE_CONTROL_PLANE_URL}/indexes/{self._index_name}",
            headers=outbound_headers({"Api-Key": self._api_key}),
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Failed to describe Pinecone index '{self._index_name}' "
                f"({response.status_code}): {response.text}"
            ) from exc

        payload = response.json()
        host = payload.get("host")
        if not host or not isinstance(host, str):
            raise RuntimeError(
                f"Pinecone index '{self._index_name}' description response did not contain a valid host: {payload}"
            )
        self._index_host = host.removeprefix("https://").removeprefix("http://").rstrip("/")
        return self._index_host

    async def upsert(
        self,
        ids: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        metadatas: Sequence[dict[str, str]],
    ) -> int:
        if not (len(ids) == len(embeddings) == len(metadatas)):
            raise ValueError(
                f"Mismatched input lengths: ids ({len(ids)}), embeddings ({len(embeddings)}), "
                f"metadatas ({len(metadatas)})"
            )
        if self._client is None:
            raise RuntimeError("PineconeStore must be used as an async context manager")
        if not ids:
            return 0

        host = await self._resolve_index_host()
        total_upserted = 0
        with stage("pinecone.upsert", provider="pinecone", input_count=len(ids)):
            for start in range(0, len(ids), PINECONE_BATCH_SIZE):
                batch_ids = ids[start : start + PINECONE_BATCH_SIZE]
                batch_embeddings = embeddings[start : start + PINECONE_BATCH_SIZE]
                batch_metadatas = metadatas[start : start + PINECONE_BATCH_SIZE]
                vectors = [
                    {
                        "id": vid,
                        "values": list(vec),
                        "metadata": meta,
                    }
                    for vid, vec, meta in zip(batch_ids, batch_embeddings, batch_metadatas)
                ]
                response = await self._client.post(
                    f"https://{host}/vectors/upsert",
                    headers=outbound_headers({
                        "Api-Key": self._api_key,
                        "Content-Type": "application/json",
                    }),
                    json={"vectors": vectors},
                )
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise RuntimeError(
                        f"Pinecone upsert batch failed ({response.status_code}): {response.text}"
                    ) from exc
                data = response.json()
                total_upserted += int(data.get("upsertedCount", len(vectors)))

        return total_upserted

    async def query(
        self,
        embedding: Sequence[float],
        top_k: int = 5,
        filter: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        if self._client is None:
            raise RuntimeError("PineconeStore must be used as an async context manager")

        host = await self._resolve_index_host()
        with stage("pinecone.query", provider="pinecone"):
            query_body: dict[str, Any] = {
                "vector": list(embedding),
                "topK": top_k,
                "includeMetadata": True,
            }
            if filter:
                query_body["filter"] = filter

            response = await self._client.post(
                f"https://{host}/query",
                headers=outbound_headers({
                    "Api-Key": self._api_key,
                    "Content-Type": "application/json",
                }),
                json=query_body,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(
                    f"Pinecone query failed ({response.status_code}): {response.text}"
                ) from exc

            payload = response.json()
            matches: list[dict[str, Any]] = payload.get("matches", [])
            return matches
