from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, Self, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .bhashini import IndicLanguage
from .observability import outbound_headers, record_citation_failure, stage
from .prompt_policy import SYSTEM_PROMPT_POLICY, SYSTEM_PROMPT_VERSION, format_untrusted_chunk
from .retrieve import JurisdictionMode, RerankedCandidate

if TYPE_CHECKING:
    from .config import Settings

logger = logging.getLogger(__name__)
INFORMATION_DISCLAIMER = "Information only, not legal advice."


class AskRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    language: IndicLanguage = "en"
    translated_query: str | None = None
    jurisdiction: JurisdictionMode
    session_id: str = Field(min_length=1, max_length=128)
    multi_hop: bool = False


class AskAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["single", "split"]
    answer: str | None = None
    sections: list[dict[str, Any]] | None = None
    citations: list[str]
    confidence: Literal["high", "medium", "low"]
    abstain: bool

    @model_validator(mode="after")
    def validate_shape(self) -> AskAnswer:
        if self.abstain:
            return self
        if self.mode == "single" and not self.answer:
            raise ValueError("single mode requires answer")
        if self.mode == "split" and not self.sections:
            raise ValueError("split mode requires sections")
        return self


class AskResponse(BaseModel):
    mode: Literal["single", "split"] | None = None
    answer: str | None = None
    sections: list[dict[str, Any]] | None = None
    citations: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] | None = None
    abstain: bool
    reason: str | None = None
    disclaimer: str = INFORMATION_DISCLAIMER


class ClaudeClient(Protocol):
    async def answer(self, system_prompt: str, user_prompt: str) -> AskAnswer: ...


@dataclass(frozen=True)
class ToolCall:
    name: Literal["retrieve_chunks", "graph_lookup"]
    arguments: dict[str, Any]
    call_id: str


@dataclass(frozen=True)
class AgentTurn:
    content: list[dict[str, Any]]
    answer: AskAnswer | None
    tool_calls: list[ToolCall]


class AgenticClaudeClient(ClaudeClient, Protocol):
    async def agent_turn(self, system_prompt: str, messages: list[dict[str, Any]]) -> AgentTurn: ...


class QaWriter(Protocol):
    async def write_qa_log(
        self,
        session_id: str,
        question: str,
        jurisdiction: JurisdictionMode,
        retrieved_chunk_ids: Sequence[str],
        reranker_scores: dict[str, float],
        answer_json: dict[str, Any],
        confidence: str | None,
        abstained: bool,
        request_id: str,
        tool_calls: Sequence[dict[str, Any]] = (),
    ) -> None: ...


class RetrieveFn(Protocol):
    async def __call__(self, query: str, jurisdiction: JurisdictionMode) -> list[RerankedCandidate]: ...


class AnthropicClaudeClient:
    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        self._api_url = settings.anthropic_api_url
        self._model = settings.anthropic_model
        self._api_version = settings.anthropic_api_version
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> Self:
        self._client = httpx.AsyncClient(timeout=90)
        return self

    async def __aexit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        if self._client is not None:
            await self._client.aclose()

    async def answer(self, system_prompt: str, user_prompt: str) -> AskAnswer:
        if self._api_key is None:
            raise RuntimeError("ANTHROPIC_API_KEY must be set to use /ask")
        if self._client is None:
            raise RuntimeError("AnthropicClaudeClient must be used as an async context manager")
        with stage("llm.generation", provider="anthropic", mode="single"):
            response = await self._client.post(
                self._api_url, headers=outbound_headers({"x-api-key": self._api_key,
                "anthropic-version": self._api_version, "content-type": "application/json"}), json={
                "model": self._model,
                "max_tokens": 1800,
                "system": [
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                "messages": [{"role": "user", "content": user_prompt}],
            })
            response.raise_for_status()
        content = response.json().get("content", [])
        text = "".join(block.get("text", "") for block in content if block.get("type") == "text")
        try:
            return AskAnswer.model_validate_json(text)
        except ValueError as error:
            raise RuntimeError("Claude returned invalid strict JSON") from error

    async def agent_turn(self, system_prompt: str, messages: list[dict[str, Any]]) -> AgentTurn:
        if self._api_key is None or self._client is None:
            raise RuntimeError("AnthropicClaudeClient is not ready for /ask")
        with stage("llm.generation", provider="anthropic", mode="agentic"):
            response = await self._client.post(
            self._api_url,
            headers=outbound_headers({"x-api-key": self._api_key, "anthropic-version": self._api_version, "content-type": "application/json"}),
            json={"model": self._model, "max_tokens": 1800, "system": system_prompt, "messages": messages,
                  "tools": [{"name": "retrieve_chunks", "description": "Retrieve grounded corpus chunks.", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}, "jurisdiction": {"type": "string", "enum": ["IN", "INTL", "BOTH"]}}, "required": ["query", "jurisdiction"]}},
                            {"name": "graph_lookup", "description": "Look up outgoing legal-graph relationships.", "input_schema": {"type": "object", "properties": {"entity": {"type": "string"}, "relation": {"type": "string", "enum": ["CITES", "SUPERSEDES", "APPLIES_TO_CATEGORY", "CROSS_REFERENCES"]}}, "required": ["entity", "relation"]}}]},
        )
            response.raise_for_status()
        content = response.json().get("content", [])
        calls = [ToolCall(block["name"], block.get("input", {}), block["id"]) for block in content if block.get("type") == "tool_use"]
        if calls:
            return AgentTurn(content, None, calls)
        text = "".join(block.get("text", "") for block in content if block.get("type") == "text")
        try:
            return AgentTurn(content, AskAnswer.model_validate_json(text), [])
        except ValueError as error:
            raise RuntimeError("Claude returned invalid strict JSON") from error


def build_system_prompt(retrieved: Sequence[RerankedCandidate]) -> str:
    evidence = [
        format_untrusted_chunk(result.candidate.chunk_id, result.candidate.jurisdiction, result.candidate.chunk_text)
        for result in retrieved
    ]
    return "\n\n".join(
        [
            f"System prompt policy version: {SYSTEM_PROMPT_VERSION}.",
            SYSTEM_PROMPT_POLICY,
            "<untrusted_retrieved_evidence>",
            *evidence,
            "</untrusted_retrieved_evidence>",
        ]
    )


async def run_agentic_answer(
    claude: AgenticClaudeClient,
    system_prompt: str,
    user_prompt: str,
    tool_executor: Any,
    timeout_seconds: float,
) -> tuple[AskAnswer | None, list[dict[str, Any]], str | None]:
    """Run Claude tools under a backend-owned deadline and call budget."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_prompt}]
    audit: list[dict[str, Any]] = []
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return None, audit, "agent_timeout"
        try:
            turn = await asyncio.wait_for(claude.agent_turn(system_prompt, messages), timeout=remaining)
        except TimeoutError:
            return None, audit, "agent_timeout"
        if turn.answer is not None:
            return turn.answer, audit, None
        messages.append({"role": "assistant", "content": turn.content})
        tool_results: list[dict[str, Any]] = []
        for call in turn.tool_calls:
            if len(audit) >= 3:
                return None, audit, "agent_tool_call_limit"
            remaining = deadline - loop.time()
            if remaining <= 0:
                return None, audit, "agent_timeout"
            try:
                result = await asyncio.wait_for(tool_executor(call), timeout=remaining)
            except TimeoutError:
                return None, audit, "agent_timeout"
            audit.append({"name": call.name, "arguments": call.arguments, "result": result})
            tool_results.append({"type": "tool_result", "tool_use_id": call.call_id, "content": json.dumps(result)})
        if not turn.tool_calls:
            return None, audit, "agent_invalid_turn"
        messages.append({"role": "user", "content": tool_results})


def build_user_prompt(query: str) -> str:
    return f"Question: {query}\nReturn only the required JSON object."


async def answer_question(
    request: AskRequest,
    retrieve_fn: RetrieveFn,
    claude: ClaudeClient,
    qa_writer: QaWriter,
    request_id: str,
    weak_reranker_score: float,
    tool_executor: Any | None = None,
    agentic_timeout_seconds: float = 30.0,
    high_confidence_reranker_score: float = 0.65,
) -> AskResponse:
    retrieval_query = request.translated_query or request.query
    with stage("answer.retrieval", jurisdiction=request.jurisdiction):
        retrieved = await retrieve_fn(retrieval_query, request.jurisdiction)
    retrieved_ids = {result.candidate.chunk_id for result in retrieved}
    score_map = {result.candidate.chunk_id: result.relevance_score for result in retrieved}
    def audit_payload(answer: AskResponse) -> dict[str, Any]:
        payload = answer.model_dump()
        payload["_query_audit"] = {
            "original_query": request.query,
            "translated_query": retrieval_query,
            "language": request.language,
        }
        return payload
    if not retrieved:
        answer = AskResponse(abstain=True, reason="no_retrieval")
        await qa_writer.write_qa_log(
            request.session_id,
            request.query,
            request.jurisdiction,
            [],
            {},
            audit_payload(answer),
            None,
            True,
            request_id,
        )
        return answer

    max_reranker_score = max(score_map.values())
    if max_reranker_score < weak_reranker_score:
        logger.info("ask.abstain_weak_retrieval", extra={"max_reranker_score": max_reranker_score})
        answer = AskResponse(abstain=True, confidence="low", reason="weak_retrieval")
        await qa_writer.write_qa_log(
            request.session_id, request.query, request.jurisdiction, sorted(retrieved_ids), score_map,
            audit_payload(answer), "low", True, request_id,
        )
        return answer

    tool_audit: list[dict[str, Any]] = []
    if request.multi_hop:
        if tool_executor is None or not hasattr(claude, "agent_turn"):
            raise RuntimeError("Agentic mode is not configured")
        model_answer, tool_audit, agent_reason = await run_agentic_answer(cast(AgenticClaudeClient, claude), build_system_prompt(retrieved), build_user_prompt(retrieval_query), tool_executor, agentic_timeout_seconds)
        if agent_reason is not None:
            answer = AskResponse(abstain=True, reason=agent_reason)
            await qa_writer.write_qa_log(request.session_id, request.query, request.jurisdiction, sorted(retrieved_ids), score_map, audit_payload(answer), None, True, request_id, tool_audit)
            return answer
        assert model_answer is not None
    else:
        model_answer = await claude.answer(build_system_prompt(retrieved), build_user_prompt(retrieval_query))
    with stage("citation.validation") as citation_span:
        invalid_citations = set(model_answer.citations) - retrieved_ids
        missing_citations = not model_answer.abstain and not model_answer.citations
        citation_span.set_attribute("app.invalid_citation_count", len(invalid_citations))
        citation_span.set_attribute("app.missing_citations", missing_citations)
    if invalid_citations or missing_citations:
        record_citation_failure()
        reason = "invalid_citation" if invalid_citations else "missing_citation"
        logger.warning("ask.citation_validation_failed", extra={"invalid_citation_count": len(invalid_citations), "missing_citations": missing_citations, "stage": "citation.validation"})
        answer = AskResponse(abstain=True, confidence="low", reason=reason)
        await qa_writer.write_qa_log(
            request.session_id,
            request.query,
            request.jurisdiction,
            sorted(retrieved_ids),
            score_map,
            audit_payload(answer),
            model_answer.confidence,
            True,
            request_id, tool_audit,
        )
        return answer

    if model_answer.abstain:
        answer = AskResponse(abstain=True, confidence="low", reason="model_abstained")
        await qa_writer.write_qa_log(
            request.session_id, request.query, request.jurisdiction, sorted(retrieved_ids), score_map,
            audit_payload(answer), "low", True, request_id, tool_audit,
        )
        return answer

    evidence_confidence: Literal["high", "medium", "low"] = (
        "high" if max_reranker_score >= high_confidence_reranker_score else "medium"
    )
    confidence_rank = {"low": 0, "medium": 1, "high": 2}
    confidence = min((model_answer.confidence, evidence_confidence), key=confidence_rank.__getitem__)
    if confidence != model_answer.confidence:
        logger.info("ask.confidence_capped_by_evidence", extra={"model_confidence": model_answer.confidence, "evidence_confidence": evidence_confidence, "max_reranker_score": max_reranker_score})

    answer = AskResponse(
        mode=model_answer.mode,
        answer=model_answer.answer,
        sections=model_answer.sections,
        citations=model_answer.citations,
        confidence=confidence,
        abstain=model_answer.abstain,
    )
    if tool_audit:
        await qa_writer.write_qa_log(
            request.session_id, request.query, request.jurisdiction, sorted(retrieved_ids), score_map,
            audit_payload(answer), confidence, answer.abstain, request_id, tool_audit,
        )
    else:
        await qa_writer.write_qa_log(
            request.session_id, request.query, request.jurisdiction, sorted(retrieved_ids), score_map,
            audit_payload(answer), confidence, answer.abstain, request_id,
        )
    return answer
