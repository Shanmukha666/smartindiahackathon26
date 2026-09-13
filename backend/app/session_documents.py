"""Session-scoped document upload and retrieval.

Uploaded documents are NOT part of the verified legal corpus. They live in
session-scoped tables, are tagged with jurisdiction="USER_UPLOAD", and are
auto-purged after a configurable TTL (default 24 hours). The prompt policy
must visibly distinguish these from authoritative statute text.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from .ingest import CorpusChunk, chunk_body
from .retrieve import SearchCandidate

USER_UPLOAD_JURISDICTION = "USER_UPLOAD"
DEFAULT_TTL_HOURS = 24


@dataclass(frozen=True)
class UploadResult:
    upload_id: int
    filename: str
    chunk_count: int
    char_count: int


class SessionUploadEmbedder(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class SessionUploadRepository(Protocol):
    async def has_uploads(self, session_id: str) -> bool: ...

    async def create_upload(
        self,
        session_id: str,
        filename: str,
        content_type: str,
        char_count: int,
        uploaded_by: str | None,
        ttl_hours: int,
    ) -> int: ...

    async def insert_chunks(
        self,
        upload_id: int,
        chunks: Sequence[CorpusChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None: ...

    async def vector_search(
        self,
        session_id: str,
        embedding: Sequence[float],
        limit: int,
    ) -> list[SearchCandidate]: ...

    async def purge_expired(self) -> int: ...


class AsyncpgSessionUploadRepository:
    """Backs SessionUploadRepository with the same asyncpg pool the app uses."""

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def has_uploads(self, session_id: str) -> bool:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT 1 FROM session_uploads WHERE session_id = $1 "
                "AND expires_at > CURRENT_TIMESTAMP LIMIT 1",
                session_id,
            )
        return row is not None

    async def create_upload(
        self,
        session_id: str,
        filename: str,
        content_type: str,
        char_count: int,
        uploaded_by: str | None,
        ttl_hours: int,
    ) -> int:
        async with self._pool.acquire() as connection:
            upload_id = await connection.fetchval(
                """
                INSERT INTO session_uploads
                    (session_id, filename, content_type, char_count, uploaded_by,
                     expires_at)
                VALUES ($1, $2, $3, $4, $5,
                        CURRENT_TIMESTAMP + ($6 * INTERVAL '1 hour'))
                RETURNING id
                """,
                session_id,
                filename[:512],
                content_type,
                char_count,
                uploaded_by,
                ttl_hours,
            )
        return int(upload_id)

    async def insert_chunks(
        self,
        upload_id: int,
        chunks: Sequence[CorpusChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        from .ingest import vector_literal

        async with self._pool.acquire() as connection:
            await connection.executemany(
                """
                INSERT INTO session_upload_chunks
                    (upload_id, chunk_text, embedding)
                VALUES ($1, $2, $3::vector)
                """,
                [
                    (upload_id, chunk.text, vector_literal(embedding))
                    for chunk, embedding in zip(chunks, embeddings, strict=True)
                ],
            )

    async def vector_search(
        self,
        session_id: str,
        embedding: Sequence[float],
        limit: int,
    ) -> list[SearchCandidate]:
        from .ingest import vector_literal

        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT chunk.id, upload.id AS upload_id, upload.filename,
                       chunk.chunk_text,
                       1 - (chunk.embedding <=> $2::vector) AS similarity
                FROM session_upload_chunks AS chunk
                JOIN session_uploads AS upload ON upload.id = chunk.upload_id
                WHERE upload.session_id = $1
                  AND upload.expires_at > CURRENT_TIMESTAMP
                ORDER BY chunk.embedding <=> $2::vector
                LIMIT $3
                """,
                session_id,
                vector_literal(list(embedding)),
                limit,
            )
        return [
            SearchCandidate(
                chunk_id=str(row["id"]),
                document_id=int(row["upload_id"]),
                instrument=str(row["filename"]),
                section="Uploaded document",
                jurisdiction=USER_UPLOAD_JURISDICTION,
                chunk_text=str(row["chunk_text"]),
                fused_score=float(row["similarity"]),
            )
            for row in rows
        ]

    async def purge_expired(self) -> int:
        async with self._pool.acquire() as connection:
            result = await connection.execute(
                "DELETE FROM session_uploads WHERE expires_at < CURRENT_TIMESTAMP"
            )
        return int(result.split()[-1])


async def ingest_upload_for_session(
    session_id: str,
    filename: str,
    text: str,
    content_type: str,
    embedder: SessionUploadEmbedder,
    repository: SessionUploadRepository,
    uploaded_by: str | None = None,
    ttl_hours: int = DEFAULT_TTL_HOURS,
) -> UploadResult:
    """Chunk, embed, and store a user-uploaded document for session-scoped retrieval."""
    clean = text.strip()
    if not clean:
        raise ValueError("No extractable text in uploaded document")

    chunks = chunk_body(clean, tags=["user-upload"])
    if not chunks:
        raise ValueError("No extractable text in uploaded document")

    embeddings = await embedder.embed([chunk.text for chunk in chunks])

    upload_id = await repository.create_upload(
        session_id=session_id,
        filename=filename,
        content_type=content_type,
        char_count=len(clean),
        uploaded_by=uploaded_by,
        ttl_hours=ttl_hours,
    )

    await repository.insert_chunks(upload_id, chunks, embeddings)

    return UploadResult(
        upload_id=upload_id,
        filename=filename,
        chunk_count=len(chunks),
        char_count=len(clean),
    )


async def retrieve_session_upload_chunks(
    session_id: str,
    query: str,
    embedder: SessionUploadEmbedder,
    repository: SessionUploadRepository,
    limit: int = 5,
) -> list[SearchCandidate]:
    """Retrieve relevant chunks from the user's uploaded documents."""
    if not await repository.has_uploads(session_id):
        return []

    embeddings = await embedder.embed([query])
    return await repository.vector_search(session_id, embeddings[0], limit)
