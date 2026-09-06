from collections.abc import Sequence
from dataclasses import dataclass

import pytest

from app.retrieve import SearchCandidate, retrieve


@dataclass
class FakeEmbedder:
    async def embed_query(self, query: str) -> list[float]:
        return [1.0] * 1024


class FakeRepository:
    def __init__(self) -> None:
        self.vector = {
            "meaning": [candidate("meaning", "Traditional knowledge exclusion", "IN")],
            "both": [candidate("both", "Section 3(p) traditional knowledge", "IN")],
            "off-topic": [],
            "3(p)": [],
        }
        self.text = {
            "meaning": [],
            "both": [candidate("both", "Section 3(p) traditional knowledge", "IN")],
            "off-topic": [],
            "3(p)": [candidate("section", "Patents Act Section 3(p)", "IN")],
        }

    async def vector_search(
        self,
        embedding: Sequence[float],
        jurisdictions: Sequence[str],
        limit: int,
    ) -> list[SearchCandidate]:
        return [result for result in self.vector[self.query] if result.jurisdiction in jurisdictions]

    async def text_search(
        self,
        query: str,
        jurisdictions: Sequence[str],
        limit: int,
    ) -> list[SearchCandidate]:
        self.query = query
        return [result for result in self.text[query] if result.jurisdiction in jurisdictions]


class FakeReranker:
    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        if query == "off-topic":
            return [0.1 for _ in documents]
        return [0.95 - index * 0.05 for index, _ in enumerate(documents)]


def candidate(chunk_id: str, text: str, jurisdiction: str) -> SearchCandidate:
    return SearchCandidate(
        chunk_id=chunk_id,
        document_id=1,
        instrument="Patents Act, 1970",
        section="Section 3(p)",
        jurisdiction=jurisdiction,
        chunk_text=text,
    )


@pytest.mark.asyncio
async def test_meaning_only_query_uses_vector_signal() -> None:
    repository = FakeRepository()
    repository.query = "meaning"
    results = await retrieve("meaning", "IN", repository, FakeEmbedder(), FakeReranker(), 0.35)
    assert [result.candidate.chunk_id for result in results] == ["meaning"]


@pytest.mark.asyncio
async def test_exact_section_query_uses_full_text_signal() -> None:
    repository = FakeRepository()
    repository.query = "3(p)"
    results = await retrieve("3(p)", "IN", repository, FakeEmbedder(), FakeReranker(), 0.35)
    assert [result.candidate.chunk_id for result in results] == ["section"]


@pytest.mark.asyncio
async def test_query_matching_both_signals_is_fused() -> None:
    repository = FakeRepository()
    repository.query = "both"
    results = await retrieve("both", "IN", repository, FakeEmbedder(), FakeReranker(), 0.35)
    assert [result.candidate.chunk_id for result in results] == ["both"]
    assert results[0].candidate.vector_rank is not None
    assert results[0].candidate.text_rank is not None


@pytest.mark.asyncio
async def test_off_topic_query_abstains_below_reranked_threshold() -> None:
    repository = FakeRepository()
    repository.query = "off-topic"
    results = await retrieve("off-topic", "IN", repository, FakeEmbedder(), FakeReranker(), 0.35)
    assert results == []
