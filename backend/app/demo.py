"""Explicit development-only local corpus demo; never enabled in production."""

from __future__ import annotations

import html
import re
from itertools import count
from pathlib import Path
from typing import cast

from .ask import AskAnswer
from .ingest import chunk_body, parse_source_file
from .retrieve import JurisdictionMode, RerankedCandidate, SearchCandidate, jurisdictions_for

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def retrieve_demo(query: str, jurisdiction: str, corpus_dir: Path) -> list[RerankedCandidate]:
    terms = set(TOKEN_PATTERN.findall(query.lower()))
    allowed = set(jurisdictions_for(cast(JurisdictionMode, jurisdiction)))
    results: list[RerankedCandidate] = []
    for document_id, path in enumerate(sorted(corpus_dir.glob("*.md")), start=1):
        source = parse_source_file(path)
        if source.metadata.jurisdiction not in allowed:
            continue
        for index, chunk in enumerate(chunk_body(source.body, source.metadata.tags), start=1):
            chunk_terms = set(TOKEN_PATTERN.findall(chunk.text.lower()))
            overlap = len(terms & chunk_terms)
            if overlap == 0:
                continue
            score = min(0.95, 0.4 + overlap / max(len(terms), 1))
            results.append(RerankedCandidate(
                SearchCandidate(
                    chunk_id=f"demo-{path.stem}-{index}", document_id=document_id,
                    instrument=source.metadata.instrument, section=source.metadata.section,
                    jurisdiction=source.metadata.jurisdiction, chunk_text=chunk.text,
                ),
                score,
            ))
    return sorted(results, key=lambda item: item.relevance_score, reverse=True)[:5]


class DemoClaudeClient:
    """Returns a visibly limited extract from local evidence; it is not an LLM."""

    async def answer(self, system_prompt: str, user_prompt: str) -> AskAnswer:
        match = re.search(r'<untrusted_chunk id="([^"]+)"[^>]*>\n(.*?)\n</untrusted_chunk>', system_prompt, re.DOTALL)
        if match is None:
            return AskAnswer(mode="single", citations=[], confidence="low", abstain=True)
        chunk_id, text = match.groups()
        excerpt = html.unescape(text).strip()
        return AskAnswer(
            mode="single",
            answer=f"Demo mode — based only on the bundled local corpus: {excerpt} [{chunk_id}]",
            citations=[chunk_id],
            confidence="medium",
            abstain=False,
        )


class DemoRepository:
    """Deliberately non-persistent adapter for the local bundled-corpus demo."""

    _escalation_ids = count(1)

    async def write_qa_log(self, *args: object, **kwargs: object) -> None:
        return None

    async def write_classification_result(self, *args: object, **kwargs: object) -> None:
        return None

    async def create_escalation(self, *args: object, **kwargs: object) -> int:
        return next(self._escalation_ids)

    async def log_paid_source_consent(self, *args: object, **kwargs: object) -> None:
        return None

    async def store_paid_source_credential(self, *args: object, **kwargs: object) -> None:
        """Deliberately discard credentials: demo mode must never persist them."""

    async def list_review_queue(self, limit: int) -> list[dict[str, object]]:
        """The bundled corpus has no persistent review queue."""
        return []

    async def resolve_review_queue_item(
        self, queue_id: int, status: str, reviewer: str, resolution_note: str
    ) -> bool:
        """There are no retained review-queue records in demo mode."""
        return False

    async def export_user_data(self, user_id: str) -> dict[str, object]:
        return {
            "user_id": user_id,
            "demo_mode": True,
            "notice": "Demo mode does not persist personal data, questions, or credentials.",
            "qa_log": [],
            "escalations": [],
            "paid_source_credentials": [],
        }

    async def delete_user_data(self, user_id: str) -> dict[str, int]:
        return {"qa_log": 0, "escalations": 0, "paid_source_credentials": 0}
