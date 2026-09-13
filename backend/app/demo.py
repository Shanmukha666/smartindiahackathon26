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

# In-memory store for session uploads in demo mode: session_id -> list of SearchCandidate
DEMO_SESSION_UPLOADS: dict[str, list[SearchCandidate]] = {}


def add_demo_session_upload(session_id: str, filename: str, text: str) -> int:
    """Store chunks in demo session memory so they can be retrieved."""
    chunks = chunk_body(text, tags=["user-upload"])
    existing = DEMO_SESSION_UPLOADS.setdefault(session_id, [])
    doc_id = len(existing) + 1
    for idx, chunk in enumerate(chunks, start=1):
        existing.append(
            SearchCandidate(
                chunk_id=f"upload-{session_id[:6]}-{doc_id}-{idx}",
                document_id=doc_id,
                instrument=filename,
                section="Uploaded document",
                jurisdiction="USER_UPLOAD",
                chunk_text=chunk.text,
                fused_score=0.92,
            )
        )
    return len(chunks)


def retrieve_demo(
    query: str,
    jurisdiction: str,
    corpus_dir: Path,
    session_id: str | None = None,
) -> list[RerankedCandidate]:
    terms = set(TOKEN_PATTERN.findall(query.lower()))
    allowed = set(jurisdictions_for(cast(JurisdictionMode, jurisdiction)))
    results: list[RerankedCandidate] = []

    # 1. Search session uploaded files first if available
    if session_id and session_id in DEMO_SESSION_UPLOADS:
        for candidate in DEMO_SESSION_UPLOADS[session_id]:
            chunk_terms = set(TOKEN_PATTERN.findall(candidate.chunk_text.lower()))
            overlap = len(terms & chunk_terms)
            score = min(0.98, 0.5 + (overlap / max(len(terms), 1))) if overlap > 0 else 0.75
            results.append(RerankedCandidate(candidate, score))

    # 2. Search local bundled corpus
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


def _synthesize_answer(query: str, chunk_id: str, raw_text: str) -> str:
    """Synthesize a direct, grounded answer matching the user query."""
    q_lower = query.lower()
    text = html.unescape(raw_text).strip()

    # 1. NBA Form and Biodiversity Approval
    if "form" in q_lower or "nba" in q_lower or "biodiversity" in q_lower:
        match = re.search(r"(Form\s+[I|V|X\d]+[^\.\n]*)", text, re.IGNORECASE)
        form_name = match.group(1).strip() if match else "Form III under Section 19/20"
        return (
            f"The required regulatory filing is **{form_name}** under Section 19/20 of the Biological Diversity Act, 2002. "
            f"Mandatory prior approval from the National Biodiversity Authority (NBA) must be secured before obtaining "
            f"or commercializing any intellectual property right based on Indian biological resources or traditional knowledge."
        )

    # 2. TKDL and Prior Art Citations
    if "citation" in q_lower or "prior art" in q_lower or "tkdl" in q_lower or "classical" in q_lower:
        citations = []
        for line in text.splitlines():
            line_str = line.strip().lstrip("-* ")
            if any(k in line_str.lower() for k in ["citation", "charaka", "bhavaprakasha", "nighantu", "samhita"]):
                citations.append(f"- {line_str}")
        if citations:
            cit_block = "\n".join(citations)
            return (
                f"The identified prior art citations in the document are:\n{cit_block}\n\n"
                f"Under Section 3(p) of the Patents Act 1970, traditional knowledge citations anticipate patent claims "
                f"unless unexpected synergistic efficacy or a non-obvious inventive formulation is established."
            )

    # 3. Overcoming Section 3(p) and 3(e)
    if "3(p)" in q_lower or "3(e)" in q_lower or "overcome" in q_lower or "synerg" in q_lower:
        return (
            "To overcome Section 3(p) (traditional knowledge) and Section 3(e) (mere admixture) objections:\n"
            "1. **Synergistic Efficacy**: Demonstrate quantifiable non-obvious synergy exceeding additive effects.\n"
            "2. **Novel Technical Process**: Provide evidence of an inventive formulation or delivery technology.\n"
            "3. **NBA Compliance**: Secure NBA Form III approval under the Biological Diversity Act 2002."
        )

    # Clean default: extract meaningful sentences without raw headers
    lines = [l.strip().lstrip("-*# ") for l in text.splitlines() if l.strip() and not l.startswith("##")]
    summary = " ".join(lines[:4])
    prefix = "According to the document:" if "upload-" in chunk_id else "Based on statutory corpus:"
    return f"{prefix} {summary}"


class DemoClaudeClient:
    """Synthesizes structured legal answers from local evidence in demo mode."""

    async def answer(self, system_prompt: str, user_prompt: str) -> AskAnswer:
        match = re.search(r'<untrusted_chunk id="([^"]+)"[^>]*>\n(.*?)\n</untrusted_chunk>', system_prompt, re.DOTALL)
        if match is None:
            return AskAnswer(mode="single", citations=[], confidence="low", abstain=True)
        chunk_id, text = match.groups()

        q_match = re.search(r"Question:\s*(.*?)(?:\nReturn|$)", user_prompt, re.DOTALL)
        query = q_match.group(1).strip() if q_match else ""

        answer_text = _synthesize_answer(query, chunk_id, text)
        return AskAnswer(
            mode="single",
            answer=f"{answer_text} [{chunk_id}]",
            citations=[chunk_id],
            confidence="high" if "upload-" in chunk_id else "medium",
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
