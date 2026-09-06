import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.ingest import (
    CorpusChunk,
    ExistingDocument,
    IngestOutcome,
    SourceDocument,
    ingest_directory,
)


class FakeEmbedder:
    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.001] * 1024 for _ in texts]


@dataclass
class StoredDocument:
    id: int
    source: SourceDocument
    active: bool = True


@dataclass
class FakeRepository:
    documents: list[StoredDocument] = field(default_factory=list)
    change_log: list[dict[str, object]] = field(default_factory=list)
    next_id: int = 1
    review_requests: list[dict[str, object]] = field(default_factory=list)

    async def enqueue_stale_answers_for_change(
        self, changed_document_id: int, previous_document_id: int, instrument: str
    ) -> None:
        self.review_requests.append(
            {"changed_document_id": changed_document_id, "previous_document_id": previous_document_id, "instrument": instrument}
        )

    async def get_active_document(self, instrument: str) -> ExistingDocument | None:
        for document in self.documents:
            if document.active and document.source.metadata.instrument == instrument:
                return ExistingDocument(
                    document.id,
                    document.source.source_hash,
                    document.source.metadata.version_tag,
                )
        return None

    async def upsert_document(
        self,
        source: SourceDocument,
        chunks: Sequence[CorpusChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> IngestOutcome:
        existing = await self.get_active_document(source.metadata.instrument)
        if existing is not None and existing.source_hash == source.source_hash:
            return IngestOutcome("unchanged", 0)
        if existing is not None:
            old = next(document for document in self.documents if document.id == existing.id)
            old.active = False
            self.change_log.append(
                {
                    "document_id": self.next_id,
                    "previous_version_tag": existing.version_tag,
                    "new_version_tag": source.metadata.version_tag,
                }
            )
        document_id = self.next_id
        self.documents.append(StoredDocument(document_id, source))
        self.next_id += 1
        if existing is not None:
            await self.enqueue_stale_answers_for_change(document_id, existing.id, source.metadata.instrument)
        return IngestOutcome("changed" if existing is not None else "inserted", len(chunks))


@pytest.mark.asyncio
async def test_modified_document_creates_corpus_change_log(tmp_path: Path) -> None:
    seed_dir = Path(__file__).parents[2] / "corpus"
    for seed_path in seed_dir.glob("*.md"):
        shutil.copy(seed_path, tmp_path / seed_path.name)

    path = tmp_path / "patents-act-section-3-p.md"
    repository = FakeRepository()
    embedder = FakeEmbedder()

    first = await ingest_directory(tmp_path, repository, embedder)
    assert first.inserted == 4
    assert first.changed == 0
    assert len(repository.change_log) == 0

    path.write_text(
        path.read_text(encoding="utf-8").replace("version_tag: India Code 2024", "version_tag: India Code 2025")
        + " Updated source text.",
        encoding="utf-8",
    )
    second = await ingest_directory(tmp_path, repository, embedder)

    assert second.changed == 1
    assert len(repository.change_log) == 1
    assert repository.change_log[0]["previous_version_tag"] == "India Code 2024"
    assert repository.change_log[0]["new_version_tag"] == "India Code 2025"
    assert repository.review_requests == [{"changed_document_id": 5, "previous_document_id": 4, "instrument": "Patents Act, 1970"}]
    assert sum(document.active for document in repository.documents) == 4
    assert sum(not document.active for document in repository.documents) == 1
