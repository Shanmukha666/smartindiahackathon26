from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, Self

import httpx
import yaml
from pydantic import BaseModel, ConfigDict, Field

from .observability import outbound_headers, stage

if TYPE_CHECKING:
    from .config import Settings

MAX_CHUNK_TOKENS = 400
CHUNK_OVERLAP_TOKENS = 40
TOKEN_PATTERN = re.compile(r"\S+")
SECTION_BOUNDARY_PATTERN = re.compile(
    r"(?m)^(?=(?:#{1,6}\s+|(?:SECTION|Section|CHAPTER|Chapter)\s+\w+\b))"
)


class CorpusFrontmatter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument: str = Field(min_length=1)
    section: str = Field(min_length=1)
    jurisdiction: Literal["IN", "INTL"]
    tags: list[str] = Field(default_factory=list)
    version_tag: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    retrieved_at: date


@dataclass(frozen=True)
class SourceDocument:
    metadata: CorpusFrontmatter
    body: str
    source_hash: str
    path: Path


@dataclass(frozen=True)
class CorpusChunk:
    text: str
    tags: list[str]


@dataclass(frozen=True)
class ExistingDocument:
    id: int
    source_hash: str
    version_tag: str


@dataclass(frozen=True)
class IngestOutcome:
    status: Literal["inserted", "changed", "unchanged"]
    chunk_count: int


@dataclass
class IngestStats:
    inserted: int = 0
    changed: int = 0
    unchanged: int = 0
    chunks: int = 0


class EmbeddingClient(Protocol):
    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class CorpusRepository(Protocol):
    async def get_active_document(self, instrument: str) -> ExistingDocument | None: ...

    async def upsert_document(
        self,
        source: SourceDocument,
        chunks: Sequence[CorpusChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> IngestOutcome: ...

    async def enqueue_stale_answers_for_change(
        self, changed_document_id: int, previous_document_id: int, instrument: str
    ) -> None: ...


class VoyageEmbedder:
    def __init__(self, settings: Settings) -> None:
        if settings.voyage_api_key is None:
            raise RuntimeError("VOYAGE_API_KEY must be set to ingest corpus documents")
        self._api_key = settings.voyage_api_key.get_secret_value()
        self._api_url = settings.voyage_api_url
        self._model = settings.voyage_model
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> Self:
        self._client = httpx.AsyncClient(timeout=90)
        return self

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def embed(
        self,
        texts: Sequence[str],
        input_type: Literal["document", "query"] = "document",
    ) -> list[list[float]]:
        if self._client is None:
            raise RuntimeError("VoyageEmbedder must be used as an async context manager")
        with stage("embedding.provider", provider="voyage", input_type=input_type, input_count=len(texts)):
            response = await self._client.post(
                self._api_url, headers=outbound_headers({"Authorization": f"Bearer {self._api_key}"}),
                json={"input": list(texts), "model": self._model, "input_type": input_type,
                      "output_dimension": 1024},
            )
            response.raise_for_status()
        payload = response.json()
        embeddings = [item["embedding"] for item in sorted(payload["data"], key=lambda item: item["index"])]
        if len(embeddings) != len(texts):
            raise RuntimeError("Voyage returned an unexpected number of embeddings")
        if any(len(embedding) != 1024 for embedding in embeddings):
            raise RuntimeError("Voyage returned an embedding with an unexpected dimension")
        return embeddings

    async def embed_query(self, query: str) -> list[float]:
        embeddings = await self.embed([query], input_type="query")
        return embeddings[0]


class AsyncpgCorpusRepository:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    @classmethod
    async def create(cls, database_url: str) -> AsyncpgCorpusRepository:
        import asyncpg

        pool = await asyncpg.create_pool(database_url, min_size=1, max_size=4)
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def rollback_corpus_version(self, instrument: str, version_tag: str) -> int:
        """Atomically activate one retained corpus revision without deleting audit history."""
        async with self._pool.acquire() as connection, connection.transaction():
            target = await connection.fetchrow(
                """SELECT id, version_tag FROM corpus_documents
                   WHERE instrument=$1 AND version_tag=$2 ORDER BY id DESC LIMIT 1""",
                instrument, version_tag,
            )
            if target is None:
                raise ValueError("Requested corpus version was not found")
            active = await connection.fetchrow(
                "SELECT id, version_tag FROM corpus_documents WHERE instrument=$1 AND is_active=TRUE FOR UPDATE",
                instrument,
            )
            if active is not None and active["id"] == target["id"]:
                return int(target["id"])
            await connection.execute("UPDATE corpus_documents SET is_active=FALSE WHERE instrument=$1", instrument)
            await connection.execute("UPDATE corpus_documents SET is_active=TRUE WHERE id=$1", target["id"])
            await connection.execute(
                """INSERT INTO corpus_change_log (document_id, previous_version_tag, new_version_tag)
                   VALUES ($1, $2, $3)""",
                target["id"], active["version_tag"] if active else None, target["version_tag"],
            )
            return int(target["id"])

    async def write_qa_log(
        self,
        session_id: str,
        question: str,
        jurisdiction: str,
        retrieved_chunk_ids: Sequence[str],
        reranker_scores: dict[str, float],
        answer_json: dict[str, Any],
        confidence: str | None,
        abstained: bool,
        request_id: str,
        tool_calls: Sequence[dict[str, Any]] = (),
    ) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO qa_log
                    (session_id, question, jurisdiction_mode, retrieved_chunk_ids,
                     reranker_scores, answer_json, confidence, abstained, request_id, tool_calls,
                     original_query, translated_query, query_language)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8, $9, $10::jsonb, $11, $12, $13)
                """,
                session_id,
                question,
                jurisdiction,
                list(retrieved_chunk_ids),
                json.dumps(reranker_scores),
                json.dumps(answer_json),
                {"high": 1.0, "medium": 0.5, "low": 0.0}.get(confidence) if confidence else None,
                abstained,
                request_id,
                json.dumps(list(tool_calls)),
                str(answer_json.get("_query_audit", {}).get("original_query", question)),
                str(answer_json.get("_query_audit", {}).get("translated_query", question)),
                str(answer_json.get("_query_audit", {}).get("language", "en")),
            )

    async def write_classification_result(
        self,
        session_id: str,
        answers: dict[str, Any],
        category: str,
    ) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO classification_results (session_id, answers_json, category)
                VALUES ($1, $2::jsonb, $3)
                """,
                session_id,
                json.dumps(answers),
                category,
            )

    async def create_escalation(
        self,
        session_id: str,
        question: str,
        reason: str,
        priority: str,
    ) -> int:
        async with self._pool.acquire() as connection:
            escalation_id = await connection.fetchval(
                """
                INSERT INTO escalations (session_id, question, reason, priority)
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                session_id,
                question,
                reason,
                priority,
            )
        return int(escalation_id)

    async def enqueue_stale_answers_for_change(
        self, changed_document_id: int, previous_document_id: int, instrument: str
    ) -> None:
        """Queue answers citing the replaced document or graph-related documents."""
        async with self._pool.acquire() as connection:
            await connection.execute(
                """
                WITH related_instruments AS (
                    SELECT $3::text AS instrument, ARRAY['DIRECT_CHANGE']::text[] AS relationship_types
                    UNION ALL
                    SELECT COALESCE(target.properties ->> 'instrument', target.name),
                           ARRAY[relationship.relationship_type]
                    FROM graph_relationships AS relationship
                    JOIN graph_entities AS source ON source.id = relationship.source_entity_id
                    JOIN graph_entities AS target ON target.id = relationship.target_entity_id
                    WHERE source.properties ->> 'instrument' = $3
                      AND relationship.relationship_type IN ('SUPERSEDES', 'CROSS_REFERENCES')
                    UNION ALL
                    SELECT COALESCE(source.properties ->> 'instrument', source.name),
                           ARRAY[relationship.relationship_type]
                    FROM graph_relationships AS relationship
                    JOIN graph_entities AS source ON source.id = relationship.source_entity_id
                    JOIN graph_entities AS target ON target.id = relationship.target_entity_id
                    WHERE target.properties ->> 'instrument' = $3
                      AND relationship.relationship_type IN ('SUPERSEDES', 'CROSS_REFERENCES')
                ), affected_documents AS (
                    SELECT $2::bigint AS id, ARRAY['DIRECT_CHANGE']::text[] AS relationship_types
                    UNION ALL
                    SELECT document.id, related.relationship_types
                    FROM corpus_documents AS document
                    JOIN related_instruments AS related ON document.instrument = related.instrument
                ), affected_chunks AS (
                    SELECT chunk.id::text AS id, affected.relationship_types
                    FROM corpus_chunks AS chunk
                    JOIN affected_documents AS affected ON affected.id = chunk.document_id
                ), affected_answers AS (
                    SELECT log.id, array_agg(DISTINCT relationship_type) AS relationship_types
                    FROM qa_log AS log
                    JOIN affected_chunks AS chunk ON log.retrieved_chunk_ids @> ARRAY[chunk.id]
                    CROSS JOIN LATERAL unnest(chunk.relationship_types) AS relationship_type
                    GROUP BY log.id
                )
                INSERT INTO qa_review_queue (qa_log_id, changed_document_id, relationship_types)
                SELECT id, $1, relationship_types FROM affected_answers
                ON CONFLICT (qa_log_id, changed_document_id) DO NOTHING
                """,
                changed_document_id,
                previous_document_id,
                instrument,
            )

    async def list_review_queue(self, limit: int = 100) -> list[dict[str, Any]]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """SELECT queue.id, queue.status, queue.relationship_types, queue.created_at,
                          queue.qa_log_id, log.question, log.answer_json, changed.instrument AS changed_instrument,
                          changed.section AS changed_section
                   FROM qa_review_queue AS queue
                   JOIN qa_log AS log ON log.id = queue.qa_log_id
                   JOIN corpus_documents AS changed ON changed.id = queue.changed_document_id
                   WHERE queue.status = 'pending'
                   ORDER BY queue.created_at ASC LIMIT $1""",
                limit,
            )
        return [dict(row) for row in rows]

    async def resolve_review_queue_item(self, queue_id: int, status: str, reviewer: str, resolution_note: str) -> bool:
        async with self._pool.acquire() as connection:
            result = await connection.execute(
                """UPDATE qa_review_queue
                   SET status=$2, reviewed_at=CURRENT_TIMESTAMP, resolved_by=$3, resolution_note=$4
                   WHERE id=$1 AND status='pending'""",
                queue_id, status, reviewer, resolution_note,
            )
        return str(result) == "UPDATE 1"

    async def store_paid_source_credential(self, user_id: str, provider: str, encrypted: dict[str, bytes], kek_version: str) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """INSERT INTO paid_source_credentials (user_id, provider, ciphertext, data_nonce, encrypted_data_key, kek_nonce, kek_version)
                   VALUES ($1,$2,$3,$4,$5,$6,$7)
                   ON CONFLICT (user_id, provider) DO UPDATE SET ciphertext=EXCLUDED.ciphertext, data_nonce=EXCLUDED.data_nonce,
                       encrypted_data_key=EXCLUDED.encrypted_data_key, kek_nonce=EXCLUDED.kek_nonce, kek_version=EXCLUDED.kek_version, rotated_at=CURRENT_TIMESTAMP""",
                user_id, provider, encrypted["ciphertext"], encrypted["data_nonce"], encrypted["encrypted_data_key"], encrypted["kek_nonce"], kek_version,
            )

    async def log_paid_source_consent(self, user_id: str, provider: str, event: dict[str, str]) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                """WITH existing AS (
                       SELECT id FROM paid_source_grants WHERE user_id=$1 AND provider=$2 AND revoked_at IS NULL ORDER BY id DESC LIMIT 1
                   ), updated AS (
                       UPDATE paid_source_grants SET consent_log_json = CASE WHEN jsonb_typeof(consent_log_json) = 'array'
                           THEN consent_log_json || jsonb_build_array($3::jsonb) ELSE jsonb_build_array($3::jsonb) END
                       WHERE id = (SELECT id FROM existing) RETURNING id
                   )
                   INSERT INTO paid_source_grants (user_id, provider, consent_log_json)
                   SELECT $1, $2, jsonb_build_array($3::jsonb) WHERE NOT EXISTS (SELECT 1 FROM updated)""",
                user_id, provider, json.dumps(event),
            )

    async def purge_expired_qa_logs(self, retention_days: int) -> int:
        async with self._pool.acquire() as connection:
            result = await connection.execute(
                """DELETE FROM qa_log AS log WHERE log.created_at < CURRENT_TIMESTAMP - ($1 * INTERVAL '1 day')
                   AND NOT log.legal_hold AND NOT EXISTS (
                     SELECT 1 FROM escalations AS escalation
                     WHERE escalation.session_id = log.session_id AND escalation.status = 'open'
                   )""",
                retention_days,
            )
        return int(result.split()[-1])

    async def export_user_data(self, user_id: str) -> dict[str, Any]:
        async with self._pool.acquire() as connection:
            qa_rows = await connection.fetch("SELECT session_id, question, answer_json, created_at FROM qa_log WHERE user_id=$1 ORDER BY created_at", user_id)
            escalation_rows = await connection.fetch("SELECT session_id, question, reason, priority, status, created_at FROM escalations WHERE user_id=$1 ORDER BY created_at", user_id)
            grant_rows = await connection.fetch("SELECT provider, granted_at, revoked_at, consent_log_json FROM paid_source_grants WHERE user_id=$1 ORDER BY granted_at", user_id)
        return {"qa_log": [dict(row) for row in qa_rows], "escalations": [dict(row) for row in escalation_rows], "paid_source_grants": [dict(row) for row in grant_rows]}

    async def delete_user_data(self, user_id: str) -> dict[str, int]:
        async with self._pool.acquire() as connection, connection.transaction():
            qa = await connection.execute("DELETE FROM qa_log WHERE user_id=$1 AND NOT legal_hold", user_id)
            escalations = await connection.execute("DELETE FROM escalations WHERE user_id=$1", user_id)
            grants = await connection.execute("DELETE FROM paid_source_grants WHERE user_id=$1", user_id)
            credentials = await connection.execute("DELETE FROM paid_source_credentials WHERE user_id=$1", user_id)
        return {"qa_log": int(qa.split()[-1]), "escalations": int(escalations.split()[-1]), "paid_source_grants": int(grants.split()[-1]), "paid_source_credentials": int(credentials.split()[-1])}

    async def get_active_document(self, instrument: str) -> ExistingDocument | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT id, source_hash, version_tag
                FROM corpus_documents
                WHERE instrument = $1 AND is_active = TRUE
                """,
                instrument,
            )
        if row is None:
            return None
        return ExistingDocument(row["id"], row["source_hash"], row["version_tag"])

    async def upsert_document(
        self,
        source: SourceDocument,
        chunks: Sequence[CorpusChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> IngestOutcome:
        if len(chunks) != len(embeddings):
            raise ValueError("Each corpus chunk must have exactly one embedding")

        async with self._pool.acquire() as connection, connection.transaction():
            existing = await connection.fetchrow(
                """
                    SELECT id, source_hash, version_tag
                    FROM corpus_documents
                    WHERE instrument = $1 AND is_active = TRUE
                    FOR UPDATE
                    """,
                source.metadata.instrument,
            )
            if existing is not None and existing["source_hash"] == source.source_hash:
                return IngestOutcome("unchanged", 0)

            if existing is not None:
                previous_document_id = int(existing["id"])
                await connection.execute(
                    "UPDATE corpus_documents SET is_active = FALSE WHERE id = $1",
                    existing["id"],
                )

            document_id = await connection.fetchval(
                """
                    INSERT INTO corpus_documents
                        (instrument, section, jurisdiction, source_url, source_hash,
                         source_retrieved_at, full_text, version_tag, is_active)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, TRUE)
                    RETURNING id
                    """,
                source.metadata.instrument,
                source.metadata.section,
                source.metadata.jurisdiction,
                source.metadata.source_url,
                source.source_hash,
                source.metadata.retrieved_at,
                source.body,
                source.metadata.version_tag,
            )

            if existing is not None:
                await connection.execute(
                    """
                        INSERT INTO corpus_change_log
                            (document_id, previous_version_tag, new_version_tag)
                        VALUES ($1, $2, $3)
                        """,
                    document_id,
                    existing["version_tag"],
                    source.metadata.version_tag,
                )

            await connection.executemany(
                """
                    INSERT INTO corpus_chunks (document_id, chunk_text, embedding, tags)
                    VALUES ($1, $2, $3::vector, $4)
                    """,
                [
                    (document_id, chunk.text, vector_literal(embedding), source.metadata.tags)
                    for chunk, embedding in zip(chunks, embeddings, strict=True)
                ],
            )

        if previous_document_id is not None:
            await self.enqueue_stale_answers_for_change(
                int(document_id), previous_document_id, source.metadata.instrument
            )
        return IngestOutcome("changed" if existing is not None else "inserted", len(chunks))


def vector_literal(embedding: Sequence[float]) -> str:
    if len(embedding) != 1024:
        raise ValueError(f"Expected 1024 embedding values, got {len(embedding)}")
    return "[" + ",".join(format(value, ".10g") for value in embedding) + "]"


def parse_source_file(path: Path) -> SourceDocument:
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{path}: expected YAML frontmatter delimited by ---")

    end_index = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if end_index is None:
        raise ValueError(f"{path}: missing closing YAML frontmatter delimiter")

    frontmatter = yaml.safe_load("".join(lines[1:end_index]))
    if frontmatter is None:
        frontmatter = {}
    if not isinstance(frontmatter, dict):
        raise ValueError(f"{path}: YAML frontmatter must be a mapping")  # noqa: TRY004
    if "version_tag" in frontmatter:
        frontmatter["version_tag"] = str(frontmatter["version_tag"])
    metadata = CorpusFrontmatter.model_validate(frontmatter)
    body = "".join(lines[end_index + 1 :]).strip()
    if not body:
        raise ValueError(f"{path}: document body must not be empty")
    source_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return SourceDocument(metadata=metadata, body=body, source_hash=source_hash, path=path)


def chunk_body(body: str, tags: list[str]) -> list[CorpusChunk]:
    sections = SECTION_BOUNDARY_PATTERN.split(body)
    chunks: list[CorpusChunk] = []
    for section in sections:
        words = TOKEN_PATTERN.findall(section.strip())
        if not words:
            continue
        start = 0
        while start < len(words):
            end = min(start + MAX_CHUNK_TOKENS, len(words))
            chunks.append(CorpusChunk(" ".join(words[start:end]), list(tags)))
            if end == len(words):
                break
            start = end - CHUNK_OVERLAP_TOKENS
    return chunks


async def ingest_directory(
    corpus_dir: Path,
    repository: CorpusRepository,
    embedder: EmbeddingClient,
) -> IngestStats:
    if not corpus_dir.is_dir():
        raise FileNotFoundError(f"Corpus directory does not exist: {corpus_dir}")

    stats = IngestStats()
    for path in sorted(item for item in corpus_dir.rglob("*") if item.is_file()):
        source = parse_source_file(path)
        existing = await repository.get_active_document(source.metadata.instrument)
        if existing is not None and existing.source_hash == source.source_hash:
            stats.unchanged += 1
            continue

        chunks = chunk_body(source.body, source.metadata.tags)
        embeddings = await embedder.embed([chunk.text for chunk in chunks])
        outcome = await repository.upsert_document(source, chunks, embeddings)
        stats.chunks += outcome.chunk_count
        if outcome.status == "inserted":
            stats.inserted += 1
        elif outcome.status == "changed":
            stats.changed += 1
        else:
            stats.unchanged += 1
    return stats
