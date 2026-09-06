from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, Self

import httpx

from .ingest import AsyncpgCorpusRepository, vector_literal
from .observability import outbound_headers, stage

if TYPE_CHECKING:
    from .config import Settings

JurisdictionMode = Literal["IN", "INTL", "BOTH"]
RRF_K = 60
VECTOR_CANDIDATE_LIMIT = 50
TEXT_CANDIDATE_LIMIT = 50
FUSION_LIMIT = 20
RESULT_LIMIT = 5


@dataclass(frozen=True)
class SearchCandidate:
    chunk_id: str
    document_id: int
    instrument: str
    section: str
    jurisdiction: str
    chunk_text: str
    vector_rank: int | None = None
    text_rank: int | None = None
    fused_score: float = 0.0


@dataclass(frozen=True)
class RerankedCandidate:
    candidate: SearchCandidate
    relevance_score: float


class QueryEmbedder(Protocol):
    async def embed_query(self, query: str) -> list[float]: ...


class CandidateRepository(Protocol):
    async def vector_search(
        self,
        embedding: Sequence[float],
        jurisdictions: Sequence[str],
        limit: int,
    ) -> list[SearchCandidate]: ...

    async def text_search(
        self,
        query: str,
        jurisdictions: Sequence[str],
        limit: int,
    ) -> list[SearchCandidate]: ...


class Reranker(Protocol):
    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]: ...


class CohereReranker:
    def __init__(self, settings: Settings) -> None:
        if settings.cohere_api_key is None:
            raise RuntimeError("COHERE_API_KEY must be set to retrieve corpus results")
        self._api_key = settings.cohere_api_key.get_secret_value()
        self._api_url = settings.cohere_api_url
        self._model = settings.cohere_model
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> Self:
        self._client = httpx.AsyncClient(timeout=30)
        return self

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        if self._client is None:
            raise RuntimeError("CohereReranker must be used as an async context manager")
        with stage("reranking", provider="cohere", document_count=len(documents)):
            response = await self._client.post(
                self._api_url, headers=outbound_headers({"Authorization": f"Bearer {self._api_key}"}),
                json={"model": self._model, "query": query, "documents": list(documents),
                      "top_n": len(documents), "return_documents": False},
            )
            response.raise_for_status()
        results = response.json()["results"]
        scores = [0.0] * len(documents)
        for result in results:
            scores[result["index"]] = float(result["relevance_score"])
        return scores


class AsyncpgCorpusRepositoryAdapter:
    """Retrieval-facing adapter over the existing asyncpg repository pool."""

    def __init__(self, repository: AsyncpgCorpusRepository) -> None:
        self._repository = repository

    async def vector_search(
        self,
        embedding: Sequence[float],
        jurisdictions: Sequence[str],
        limit: int,
    ) -> list[SearchCandidate]:
        return await self._search(
            """
            SELECT cc.id::text AS chunk_id, cd.id AS document_id,
                   cd.instrument, cd.section, cd.jurisdiction, cc.chunk_text
            FROM corpus_chunks AS cc
            JOIN corpus_documents AS cd ON cd.id = cc.document_id
            WHERE cd.is_active = TRUE
              AND cd.jurisdiction = ANY($2::text[])
              AND cc.embedding IS NOT NULL
            ORDER BY cc.embedding <=> $1::vector
            LIMIT $3
            """,
            vector_literal(embedding),
            list(jurisdictions),
            limit,
            "vector_rank",
        )

    async def text_search(
        self,
        query: str,
        jurisdictions: Sequence[str],
        limit: int,
    ) -> list[SearchCandidate]:
        return await self._search(
            """
            SELECT cc.id::text AS chunk_id, cd.id AS document_id,
                   cd.instrument, cd.section, cd.jurisdiction, cc.chunk_text
            FROM corpus_chunks AS cc
            JOIN corpus_documents AS cd ON cd.id = cc.document_id
            WHERE cd.is_active = TRUE
              AND cd.jurisdiction = ANY($2::text[])
              AND cc.text_search @@ websearch_to_tsquery('simple', $1)
            ORDER BY ts_rank_cd(cc.text_search, websearch_to_tsquery('simple', $1)) DESC
            LIMIT $3
            """,
            query,
            list(jurisdictions),
            limit,
            "text_rank",
        )

    async def _search(
        self,
        query: str,
        first_param: Any,
        jurisdictions: list[str],
        limit: int,
        rank_field: Literal["vector_rank", "text_rank"],
    ) -> list[SearchCandidate]:
        async with self._repository._pool.acquire() as connection:
            rows = await connection.fetch(query, first_param, jurisdictions, limit)
        return [
            SearchCandidate(
                chunk_id=str(row["chunk_id"]),
                document_id=row["document_id"],
                instrument=row["instrument"],
                section=row["section"],
                jurisdiction=row["jurisdiction"],
                chunk_text=row["chunk_text"],
                **{rank_field: index},
            )
            for index, row in enumerate(rows, start=1)
        ]


def jurisdictions_for(mode: JurisdictionMode) -> tuple[str, ...]:
    return ("IN",) if mode == "IN" else ("INTL",) if mode == "INTL" else ("IN", "INTL")


def reciprocal_rank_fusion(
    vector_results: Sequence[SearchCandidate],
    text_results: Sequence[SearchCandidate],
    limit: int = FUSION_LIMIT,
    k: int = RRF_K,
) -> list[SearchCandidate]:
    merged: dict[str, SearchCandidate] = {}
    scores: dict[str, float] = {}
    for rank, result in enumerate(vector_results, start=1):
        merged[result.chunk_id] = SearchCandidate(
            chunk_id=result.chunk_id,
            document_id=result.document_id,
            instrument=result.instrument,
            section=result.section,
            jurisdiction=result.jurisdiction,
            chunk_text=result.chunk_text,
            vector_rank=rank,
            text_rank=result.text_rank,
        )
        scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + 1 / (k + rank)
    for rank, result in enumerate(text_results, start=1):
        current = merged.get(result.chunk_id, result)
        merged[result.chunk_id] = SearchCandidate(
            chunk_id=current.chunk_id,
            document_id=current.document_id,
            instrument=current.instrument,
            section=current.section,
            jurisdiction=current.jurisdiction,
            chunk_text=current.chunk_text,
            vector_rank=current.vector_rank,
            text_rank=rank,
        )
        scores[result.chunk_id] = scores.get(result.chunk_id, 0.0) + 1 / (k + rank)

    fused = [
        SearchCandidate(
            chunk_id=result.chunk_id,
            document_id=result.document_id,
            instrument=result.instrument,
            section=result.section,
            jurisdiction=result.jurisdiction,
            chunk_text=result.chunk_text,
            vector_rank=result.vector_rank,
            text_rank=result.text_rank,
            fused_score=scores[result.chunk_id],
        )
        for result in merged.values()
    ]
    return sorted(fused, key=lambda result: result.fused_score, reverse=True)[:limit]


async def retrieve(
    query: str,
    jurisdiction: JurisdictionMode,
    repository: CandidateRepository,
    embedder: QueryEmbedder,
    reranker: Reranker,
    min_relevance: float,
) -> list[RerankedCandidate]:
    if not query.strip():
        return []
    allowed_jurisdictions = jurisdictions_for(jurisdiction)
    with stage("retrieval", jurisdiction=jurisdiction) as retrieval_span:
        with stage("embedding", provider="voyage"):
            query_embedding = await embedder.embed_query(query)
        with stage("retrieval.search", jurisdiction=jurisdiction):
            vector_results, text_results = await asyncio.gather(
                repository.vector_search(query_embedding, allowed_jurisdictions, VECTOR_CANDIDATE_LIMIT),
                repository.text_search(query, allowed_jurisdictions, TEXT_CANDIDATE_LIMIT),
            )
        fused = reciprocal_rank_fusion(vector_results, text_results)
        retrieval_span.set_attribute("app.candidate_count", len(fused))
        if not fused:
            return []
        relevance_scores = await reranker.rerank(query, [result.chunk_text for result in fused])
        if len(relevance_scores) != len(fused):
            raise RuntimeError("Reranker returned an unexpected number of scores")
        reranked = [
            RerankedCandidate(candidate, score)
            for candidate, score in zip(fused, relevance_scores, strict=True)
            if score >= min_relevance
        ]
        results = sorted(reranked, key=lambda result: result.relevance_score, reverse=True)[:RESULT_LIMIT]
        retrieval_span.set_attribute("app.result_count", len(results))
        return results
