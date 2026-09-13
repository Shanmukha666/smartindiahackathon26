from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from app.ingest import CorpusChunk
from app.retrieve import SearchCandidate
from app.session_documents import (
    USER_UPLOAD_JURISDICTION,
    ingest_upload_for_session,
    retrieve_session_upload_chunks,
)


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[0.01] * 1024 for _ in texts]


@dataclass
class FakeSessionUploadRepository:
    uploads: dict[str, list[int]] = field(default_factory=dict)
    chunks_by_upload: dict[int, list[CorpusChunk]] = field(default_factory=dict)
    next_id: int = 1

    async def has_uploads(self, session_id: str) -> bool:
        return bool(self.uploads.get(session_id))

    async def create_upload(
        self,
        session_id: str,
        filename: str,
        content_type: str,
        char_count: int,
        uploaded_by: str | None,
        ttl_hours: int,
    ) -> int:
        upload_id = self.next_id
        self.next_id += 1
        self.uploads.setdefault(session_id, []).append(upload_id)
        return upload_id

    async def insert_chunks(
        self,
        upload_id: int,
        chunks: Sequence[CorpusChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        assert len(chunks) == len(embeddings)
        self.chunks_by_upload[upload_id] = list(chunks)

    async def vector_search(
        self,
        session_id: str,
        embedding: Sequence[float],
        limit: int,
    ) -> list[SearchCandidate]:
        if session_id not in self.uploads:
            return []
        results: list[SearchCandidate] = []
        for upload_id in self.uploads[session_id]:
            for index, chunk in enumerate(
                self.chunks_by_upload.get(upload_id, [])
            ):
                results.append(
                    SearchCandidate(
                        chunk_id=f"{upload_id}:{index}",
                        document_id=upload_id,
                        instrument="uploaded.pdf",
                        section="Uploaded document",
                        jurisdiction=USER_UPLOAD_JURISDICTION,
                        chunk_text=chunk.text,
                        fused_score=0.9,
                    )
                )
        return results[:limit]

    async def purge_expired(self) -> int:
        return 0


@pytest.mark.asyncio
async def test_ingest_upload_chunks_and_embeds_text() -> None:
    embedder = FakeEmbedder()
    repository = FakeSessionUploadRepository()
    result = await ingest_upload_for_session(
        session_id="session-1",
        filename="dossier.pdf",
        text="Section 1. The formulation contains neem extract and turmeric. " * 20,
        content_type="application/pdf",
        embedder=embedder,
        repository=repository,
    )
    assert result.chunk_count >= 1
    assert result.filename == "dossier.pdf"
    assert embedder.calls  # embedding was actually invoked


@pytest.mark.asyncio
async def test_ingest_upload_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="No extractable text"):
        await ingest_upload_for_session(
            session_id="session-1",
            filename="empty.txt",
            text="   ",
            content_type="text/plain",
            embedder=FakeEmbedder(),
            repository=FakeSessionUploadRepository(),
        )


@pytest.mark.asyncio
async def test_retrieve_returns_empty_when_session_has_no_uploads() -> None:
    embedder = FakeEmbedder()
    repository = FakeSessionUploadRepository()
    results = await retrieve_session_upload_chunks(
        "session-without-uploads", "what is in my document?", embedder, repository
    )
    assert results == []
    assert embedder.calls == []  # must not waste an embedding call


@pytest.mark.asyncio
async def test_retrieve_finds_chunks_after_ingest_and_tags_jurisdiction() -> None:
    embedder = FakeEmbedder()
    repository = FakeSessionUploadRepository()
    await ingest_upload_for_session(
        "session-2",
        "notes.txt",
        "Traditional formulation using ashwagandha root powder.",
        "text/plain",
        embedder,
        repository,
    )
    results = await retrieve_session_upload_chunks(
        "session-2", "what herbs are used?", embedder, repository
    )
    assert len(results) >= 1
    assert all(
        candidate.jurisdiction == USER_UPLOAD_JURISDICTION for candidate in results
    )
