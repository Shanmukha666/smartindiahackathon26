from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.pinecone_store import (
    OPENAI_EMBEDDING_DIMENSION,
    OpenAIEmbedder,
    PineconeStore,
)


def make_test_settings(**kwargs: object) -> Settings:
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
        "openai_api_key": SecretStr("test-openai-key"),
        "openai_embedding_model": "text-embedding-3-small",
        "pinecone_api_key": SecretStr("test-pinecone-key"),
        "pinecone_index": "airag-1536",
    }
    defaults.update(kwargs)
    return Settings(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_openai_embedder_missing_api_key() -> None:
    settings = make_test_settings(openai_api_key=None)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY must be set"):
        OpenAIEmbedder(settings)


@pytest.mark.asyncio
async def test_openai_embedder_success() -> None:
    settings = make_test_settings()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.openai.com/v1/embeddings"
        assert request.headers["authorization"] == "Bearer test-openai-key"
        body = httpx.Response(200, content=request.content).json()
        assert body["model"] == "text-embedding-3-small"
        assert body["input"] == ["hello world", "test 2"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [0.1] * OPENAI_EMBEDDING_DIMENSION},
                    {"index": 1, "embedding": [0.2] * OPENAI_EMBEDDING_DIMENSION},
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        embedder = OpenAIEmbedder(settings, client=client)
        embeddings = await embedder.embed(["hello world", "test 2"])
        assert len(embeddings) == 2
        assert len(embeddings[0]) == OPENAI_EMBEDDING_DIMENSION
        assert embeddings[0][0] == 0.1
        assert embeddings[1][0] == 0.2


@pytest.mark.asyncio
async def test_openai_embedder_embed_query() -> None:
    settings = make_test_settings()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.5] * OPENAI_EMBEDDING_DIMENSION}]},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        embedder = OpenAIEmbedder(settings, client=client)
        result = await embedder.embed_query("query test")
        assert len(result) == OPENAI_EMBEDDING_DIMENSION
        assert result[0] == 0.5


@pytest.mark.asyncio
async def test_openai_embedder_http_error() -> None:
    settings = make_test_settings()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Unauthorized API key")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        embedder = OpenAIEmbedder(settings, client=client)
        with pytest.raises(RuntimeError, match="OpenAI embeddings request failed \\(401\\)"):
            await embedder.embed(["fail"])


@pytest.mark.asyncio
async def test_pinecone_store_missing_api_key() -> None:
    settings = make_test_settings(pinecone_api_key=None)
    with pytest.raises(RuntimeError, match="PINECONE_API_KEY must be set"):
        PineconeStore(settings)


@pytest.mark.asyncio
async def test_pinecone_store_host_resolution_and_caching() -> None:
    settings = make_test_settings()
    resolution_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal resolution_calls
        if request.url == "https://api.pinecone.io/indexes/airag-1536":
            resolution_calls += 1
            assert request.headers["api-key"] == "test-pinecone-key"
            return httpx.Response(200, json={"host": "index-123.pinecone.io"})
        if request.url == "https://index-123.pinecone.io/query":
            return httpx.Response(200, json={"matches": [{"id": "vec1", "score": 0.95}]})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        store = PineconeStore(settings, client=client)
        res1 = await store.query([0.1] * 1536, top_k=1)
        assert len(res1) == 1
        assert res1[0]["id"] == "vec1"
        assert resolution_calls == 1

        # Second query should reuse cached host and not call control plane again
        res2 = await store.query([0.2] * 1536, top_k=1)
        assert len(res2) == 1
        assert resolution_calls == 1


@pytest.mark.asyncio
async def test_pinecone_store_upsert_batching() -> None:
    settings = make_test_settings()
    batch_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal batch_count
        if request.url == "https://index-abc.pinecone.io/vectors/upsert":
            batch_count += 1
            assert request.headers["api-key"] == "test-pinecone-key"
            data = httpx.Response(200, content=request.content).json()
            vectors = data["vectors"]
            assert len(vectors) <= 100
            return httpx.Response(200, json={"upsertedCount": len(vectors)})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        # Pass index_host directly
        store = PineconeStore(settings, client=client, index_host="index-abc.pinecone.io")
        ids = [f"id_{i}" for i in range(250)]
        embeddings = [[0.1] * 1536 for _ in range(250)]
        metadatas = [{"text": f"text {i}"} for i in range(250)]

        upserted = await store.upsert(ids, embeddings, metadatas)
        assert upserted == 250
        assert batch_count == 3  # 100 + 100 + 50


@pytest.mark.asyncio
async def test_pinecone_store_query_with_filter() -> None:
    settings = make_test_settings()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://index-xyz.pinecone.io/query"
        data = httpx.Response(200, content=request.content).json()
        assert data["topK"] == 3
        assert data["includeMetadata"] is True
        assert data["filter"] == {"genre": "patent"}
        return httpx.Response(
            200,
            json={"matches": [{"id": "vec1", "score": 0.88, "metadata": {"genre": "patent"}}]},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        store = PineconeStore(settings, client=client, index_host="index-xyz.pinecone.io")
        results = await store.query([0.5] * 1536, top_k=3, filter={"genre": "patent"})
        assert len(results) == 1
        assert results[0]["id"] == "vec1"
        assert results[0]["score"] == 0.88
