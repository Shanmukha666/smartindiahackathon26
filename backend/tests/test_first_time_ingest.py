from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.ingest import (
    AsyncpgCorpusRepository,
    CorpusChunk,
    CorpusFrontmatter,
    SourceDocument,
)


class AsyncContextManagerMock:
    def __init__(self, enter_val: Any = None) -> None:
        self.enter_val = enter_val

    async def __aenter__(self) -> Any:
        return self.enter_val

    async def __aexit__(self, exc_type: Any, exc_val: Any, tb: Any) -> None:
        return None


def make_mock_pool(conn: AsyncMock) -> MagicMock:
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=AsyncContextManagerMock(conn))
    conn.transaction = MagicMock(return_value=AsyncContextManagerMock(None))
    return pool


@pytest.mark.asyncio
async def test_upsert_document_first_time_ingest_succeeds_without_error() -> None:
    """Verifies that upsert_document on a brand-new instrument does not raise
    UnboundLocalError (or any other exception) when existing is None."""
    conn = AsyncMock()
    conn.fetchrow.return_value = None  # Brand-new document
    conn.fetchval.return_value = 101   # Returned document_id

    pool = make_mock_pool(conn)
    repo = AsyncpgCorpusRepository(pool)
    assert repo.pool is pool

    source = SourceDocument(
        body="Section 1. Short title and commencement.",
        source_hash="hash_brand_new_doc_123",
        metadata=CorpusFrontmatter(
            instrument="Brand New Act 2026",
            section="Section 1",
            jurisdiction="IN",
            source_url="https://example.gov.in/act2026",
            retrieved_at=date(2026, 1, 1),
            tags=["patent", "ayush"],
            version_tag="v1.0",
        ),
        path=Path("dummy.md"),
    )
    chunks = [CorpusChunk(text="Section 1 chunk", tags=["patent"])]
    embeddings = [[0.01] * 1024]

    outcome = await repo.upsert_document(source, chunks, embeddings)

    assert outcome.status == "inserted"
    assert outcome.chunk_count == 1
    # Ensure insert into corpus_documents was called
    assert conn.fetchval.called
    # Ensure chunk insert was called
    assert conn.executemany.called


@pytest.mark.asyncio
async def test_upsert_document_update_triggers_stale_answer_enqueue() -> None:
    """Verifies that upserting an updated document inactivates the previous one
    and enqueues stale answers with previous_document_id."""
    conn = AsyncMock()
    conn.fetchrow.return_value = {
        "id": 50,
        "source_hash": "old_hash_000",
        "version_tag": "v1.0",
    }
    conn.fetchval.return_value = 102

    pool = make_mock_pool(conn)
    repo = AsyncpgCorpusRepository(pool)

    # Mock enqueue_stale_answers_for_change to verify it receives correct args
    repo.enqueue_stale_answers_for_change = AsyncMock()  # type: ignore[method-assign]

    source = SourceDocument(
        body="Section 1. Updated title.",
        source_hash="new_hash_111",
        metadata=CorpusFrontmatter(
            instrument="Brand New Act 2026",
            section="Section 1",
            jurisdiction="IN",
            source_url="https://example.gov.in/act2026",
            retrieved_at=date(2026, 1, 1),
            tags=["patent", "ayush"],
            version_tag="v1.1",
        ),
        path=Path("dummy.md"),
    )
    chunks = [CorpusChunk(text="Updated chunk", tags=["patent"])]
    embeddings = [[0.02] * 1024]

    outcome = await repo.upsert_document(source, chunks, embeddings)

    assert outcome.status == "changed"
    assert outcome.chunk_count == 1
    repo.enqueue_stale_answers_for_change.assert_awaited_once_with(
        102, 50, "Brand New Act 2026"
    )
