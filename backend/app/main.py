import logging
from collections.abc import Awaitable, Callable
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from classification import TrailStep, load_tree

from .ask import (
    AnthropicClaudeClient,
    AskRequest,
    AskResponse,
    ToolCall,
    answer_question,
)
from .auth import current_user, require_role
from .bhashini import BhashiniClient, IndicLanguage
from .config import get_settings
from .db import check_database_connection
from .escalation import (
    EscalateRequest,
    LoggingNotificationChannel,
    WebhookNotificationChannel,
    create_escalation,
)
from .graph import AsyncpgGraphRepository, RelationshipType
from .ingest import AsyncpgCorpusRepository, VoyageEmbedder
from .observability import (
    annotate_request,
    configure_logging,
    configure_tracing,
    new_request_id,
    request_id_context,
    stage,
)
from .paid_sources import (
    SecretManagerKekProvider,
    StubPaidSourceConnector,
    consent_event,
    envelope_encrypt,
)
from .prompt_policy import format_untrusted_chunk
from .rate_limit import RateLimiter
from .retrieve import AsyncpgCorpusRepositoryAdapter, CohereReranker, RerankedCandidate, retrieve

settings = get_settings()
configure_logging()
app = FastAPI(title=settings.app_name)
configure_tracing(settings, app)
logger = logging.getLogger(__name__)
notification_channel = (WebhookNotificationChannel(settings.notification_webhook_url.get_secret_value())
                        if settings.notification_provider == "webhook" and settings.notification_webhook_url else LoggingNotificationChannel())
rate_limiter = RateLimiter()
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=True,
                   allow_methods=["GET", "POST", "DELETE"], allow_headers=["Authorization", "Content-Type", "X-Request-ID"])


class RetrieveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    jurisdiction: Literal["IN", "INTL", "BOTH"]
    language: IndicLanguage = "en"


class SpeechToTextRequest(BaseModel):
    audio_base64: str = Field(min_length=1, max_length=8_000_000)
    language: IndicLanguage


class TextToSpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    language: IndicLanguage


class SpeechToTextResponse(BaseModel):
    transcript: str


class TextToSpeechResponse(BaseModel):
    audio_base64: str
    audio_format: str


class RetrieveResult(BaseModel):
    chunk_id: str
    document_id: int
    instrument: str
    section: str
    jurisdiction: Literal["IN", "INTL"]
    chunk_text: str
    score: float


class RetrieveResponse(BaseModel):
    results: list[RetrieveResult]


class ReviewQueueItem(BaseModel):
    id: int
    qa_log_id: int
    question: str
    answer_json: dict[str, object]
    changed_instrument: str
    changed_section: str
    relationship_types: list[str]
    status: str
    created_at: str


class ReviewQueueResolution(BaseModel):
    status: Literal["reviewed", "dismissed"]
    resolution_note: str = Field(min_length=1, max_length=4000)


class PaidCredentialRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_-]+$")
    credential: str = Field(min_length=1, max_length=8192)


class PaidSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    consent_accepted: bool


class DataDeletionResponse(BaseModel):
    deleted: dict[str, int]


class ClassifyRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    trail: list[TrailStep] = Field(default_factory=list)
    answer_index: int | None = Field(default=None, ge=0)


class ClassificationResultResponse(BaseModel):
    category: str
    regulatory_path: str
    ip_posture: str
    abs_note: str


class ClassifyResponse(BaseModel):
    complete: bool
    question: str | None = None
    options: list[str] = Field(default_factory=list)
    trail: list[TrailStep]
    result: ClassificationResultResponse | None = None


@app.middleware("http")
async def request_context_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    request_id = request.headers.get("X-Request-ID") or new_request_id()
    token = request_id_context.set(request_id)
    annotate_request(request_id)
    response = None
    try:
        response = await call_next(request)
        return response
    except Exception:
        logger.exception("request.failed", extra={"method": request.method, "path": request.url.path})
        raise
    finally:
        if response is not None:
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "request.completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                },
            )
        request_id_context.reset(token)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    response = await call_next(request)
    response.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                             "Referrer-Policy": "no-referrer", "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
                             "Cross-Origin-Opener-Policy": "same-origin", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'"})
    if settings.deployment_environment == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.middleware("http")
async def request_size_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > settings.max_request_body_bytes:
                return JSONResponse(status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                                    content={"detail": "Request body too large"})
        except ValueError:
            return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST,
                                content={"detail": "Invalid Content-Length"})
    return await call_next(request)


@app.middleware("http")
async def expensive_endpoint_rate_limit(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    limits = {"/ask": settings.ask_rate_limit_per_minute, "/retrieve": settings.retrieve_rate_limit_per_minute,
              "/escalate": settings.ask_rate_limit_per_minute, "/classify/next": settings.retrieve_rate_limit_per_minute}
    limit = limits.get(request.url.path)
    if request.method == "POST" and limit is not None:
        client_id = request.client.host if request.client else "unknown"
        if settings.rate_limit_backend == "memory" and not rate_limiter.allow(request.url.path, client_id, limit):
            return JSONResponse(status_code=status.HTTP_429_TOO_MANY_REQUESTS, content={"detail": "Rate limit exceeded"}, headers={"Retry-After": "60"})
    return await call_next(request)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> JSONResponse:
    database_ready = await check_database_connection()
    if not database_ready:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "database": "unavailable"},
        )
    return JSONResponse(content={"status": "ready", "database": "available"})


async def retrieve_for_request(query: str, jurisdiction: Literal["IN", "INTL", "BOTH"]) -> list[RerankedCandidate]:
    repository = await AsyncpgCorpusRepository.create(settings.database_url.get_secret_value())
    try:
        async with VoyageEmbedder(settings) as embedder, CohereReranker(settings) as reranker:
            return await retrieve(
                query, jurisdiction, AsyncpgCorpusRepositoryAdapter(repository), embedder, reranker,
                settings.min_relevance,
            )
    finally:
        await repository.close()


async def english_query(query: str, language: IndicLanguage) -> str:
    """Translate the retrieval representation without mutating the submitted query."""
    if language == "en":
        return query
    return await BhashiniClient(settings).translate(query, language, "en")


@app.post("/retrieve", response_model=RetrieveResponse)
async def retrieve_endpoint(payload: RetrieveRequest) -> RetrieveResponse:
    try:
        results = await retrieve_for_request(await english_query(payload.query, payload.language), payload.jurisdiction)
    except (RuntimeError, httpx.HTTPError) as error:
        logger.warning("retrieve.unavailable", extra={"error_type": type(error).__name__})
        raise HTTPException(status_code=503, detail="Retrieval service unavailable") from error

    return RetrieveResponse(
        results=[
            RetrieveResult(
                chunk_id=result.candidate.chunk_id,
                document_id=result.candidate.document_id,
                instrument=result.candidate.instrument,
                section=result.candidate.section,
                jurisdiction=result.candidate.jurisdiction,
                chunk_text=result.candidate.chunk_text,
                score=result.relevance_score,
            )
            for result in results
        ]
    )


@app.post("/speech/transcribe", response_model=SpeechToTextResponse)
async def transcribe_endpoint(payload: SpeechToTextRequest) -> SpeechToTextResponse:
    try:
        return SpeechToTextResponse(
            transcript=await BhashiniClient(settings).transcribe(payload.audio_base64, payload.language)
        )
    except (RuntimeError, httpx.HTTPError) as error:
        logger.warning("retrieve.unavailable", extra={"error_type": type(error).__name__})
        raise HTTPException(status_code=503, detail="Retrieval service unavailable") from error


@app.post("/speech/synthesize", response_model=TextToSpeechResponse)
async def synthesize_endpoint(payload: TextToSpeechRequest) -> TextToSpeechResponse:
    try:
        audio, audio_format = await BhashiniClient(settings).synthesize(payload.text, payload.language)
        return TextToSpeechResponse(audio_base64=audio, audio_format=audio_format)
    except (RuntimeError, httpx.HTTPError) as error:
        logger.warning("speech.unavailable", extra={"error_type": type(error).__name__})
        raise HTTPException(status_code=503, detail="Speech service unavailable") from error


@app.post("/ask", response_model=AskResponse)
async def ask_endpoint(payload: AskRequest) -> AskResponse:
    try:
        translated_payload = payload.model_copy(
            update={"translated_query": await english_query(payload.query, payload.language)}
        )
        repository = await AsyncpgCorpusRepository.create(settings.database_url.get_secret_value())
        try:
            if hasattr(repository, "purge_expired_qa_logs"):
                await repository.purge_expired_qa_logs(settings.qa_retention_days)
            async with AnthropicClaudeClient(settings) as claude:
                async def execute_tool(call: ToolCall) -> dict[str, object]:
                    if call.name == "retrieve_chunks":
                        query = call.arguments.get("query")
                        jurisdiction = call.arguments.get("jurisdiction")
                        if not isinstance(query, str) or jurisdiction not in {"IN", "INTL", "BOTH"}:
                            return {"error": "retrieve_chunks requires query and a valid jurisdiction"}
                        results = await retrieve_for_request(query, jurisdiction)
                        return {"chunks": [{"id": item.candidate.chunk_id,
                                            "untrusted_evidence": format_untrusted_chunk(
                                                item.candidate.chunk_id, item.candidate.jurisdiction, item.candidate.chunk_text
                                            ),
                                            "jurisdiction": item.candidate.jurisdiction}
                                           for item in results]}
                    entity = call.arguments.get("entity")
                    relation = call.arguments.get("relation")
                    if not isinstance(entity, str) or not isinstance(relation, str):
                        return {"error": "graph_lookup requires entity and relation"}
                    try:
                        graph = AsyncpgGraphRepository(repository._pool)
                        relationships = await graph.lookup(entity, RelationshipType(relation))
                    except ValueError:
                        return {"error": "graph_lookup received an unsupported relation"}
                    return {"relationships": [{"source": edge.source.name, "relation": edge.relationship_type.value,
                                                "target": edge.target.name} for edge in relationships]}

                return await answer_question(
                    translated_payload,
                    retrieve_for_request,
                    claude,
                    repository,
                    request_id_context.get(),
                    settings.weak_reranker_score,
                    execute_tool,
                    settings.agentic_timeout_seconds,
                    settings.high_confidence_reranker_score,
                )
        finally:
            await repository.close()
    except (RuntimeError, httpx.HTTPError) as error:
        logger.warning("ask.unavailable", extra={"error_type": type(error).__name__})
        raise HTTPException(status_code=503, detail="Answer service unavailable") from error


@app.get("/admin/review-queue", response_model=list[ReviewQueueItem])
async def list_review_queue(limit: int = 100, _: str = Depends(require_role("legal_reviewer"))) -> list[ReviewQueueItem]:
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    repository = await AsyncpgCorpusRepository.create(settings.database_url.get_secret_value())
    try:
        return [ReviewQueueItem(**{**item, "created_at": item["created_at"].isoformat()})
                for item in await repository.list_review_queue(limit)]
    finally:
        await repository.close()


@app.patch("/admin/review-queue/{queue_id}", status_code=status.HTTP_204_NO_CONTENT)
async def resolve_review_queue_item(
    queue_id: int,
    payload: ReviewQueueResolution,
    reviewer: str = Depends(require_role("legal_reviewer")),
) -> Response:
    repository = await AsyncpgCorpusRepository.create(settings.database_url.get_secret_value())
    try:
        if not await repository.resolve_review_queue_item(queue_id, payload.status, reviewer, payload.resolution_note):
            raise HTTPException(status_code=404, detail="Pending review-queue item not found")
    finally:
        await repository.close()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/paid-sources/credentials", status_code=status.HTTP_204_NO_CONTENT)
async def save_paid_source_credential(payload: PaidCredentialRequest, user_id: str = Depends(current_user)) -> Response:
    with stage("paid_source.credentials", provider=payload.provider):
        kek_version, kek = await SecretManagerKekProvider(settings.credential_kek_secret_resource).get_kek()
        encrypted = envelope_encrypt(payload.credential, kek)
        repository = await AsyncpgCorpusRepository.create(settings.database_url.get_secret_value())
        try:
            await repository.store_paid_source_credential(user_id, payload.provider, encrypted, kek_version)
        finally:
            await repository.close()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/paid-sources/{provider}/search")
async def paid_source_search(provider: str, payload: PaidSearchRequest, user_id: str = Depends(current_user)) -> dict[str, object]:
    if not payload.consent_accepted:
        raise HTTPException(status_code=422, detail="Explicit consent is required before a paid-source call")
    if provider != StubPaidSourceConnector.provider or not settings.allow_stub_connectors:
        raise HTTPException(status_code=404, detail="Unknown paid-source provider")
    repository = await AsyncpgCorpusRepository.create(settings.database_url.get_secret_value())
    try:
        with stage("paid_source.connector", provider=provider):
            await repository.log_paid_source_consent(user_id, provider, await consent_event(user_id, provider, payload.query))
            results = await StubPaidSourceConnector().search(payload.query)
    finally:
        await repository.close()
    return {"results": results}


@app.get("/privacy/export")
async def export_own_data(user_id: str = Depends(current_user)) -> dict[str, object]:
    repository = await AsyncpgCorpusRepository.create(settings.database_url.get_secret_value())
    try:
        return await repository.export_user_data(user_id)
    finally:
        await repository.close()


@app.delete("/privacy/data", response_model=DataDeletionResponse)
async def delete_own_data(user_id: str = Depends(current_user)) -> DataDeletionResponse:
    repository = await AsyncpgCorpusRepository.create(settings.database_url.get_secret_value())
    try:
        return DataDeletionResponse(deleted=await repository.delete_user_data(user_id))
    finally:
        await repository.close()


@app.post("/classify/next", response_model=ClassifyResponse)
async def classify_next(payload: ClassifyRequest) -> ClassifyResponse:
    try:
        with stage("classification") as classification_span:
            tree_path = settings.classification_tree_path
            tree = load_tree(tree_path)
            if payload.answer_index is None:
                if payload.trail:
                    raise ValueError("answer_index is required when trail is non-empty")
                step = tree.initial()
            else:
                step = tree.advance(payload.trail, payload.answer_index)
            classification_span.set_attribute("app.complete", step.result is not None)
            if step.result is not None:
                classification_span.set_attribute("app.category", step.result.category)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    if step.result is not None:
        repository = await AsyncpgCorpusRepository.create(settings.database_url.get_secret_value())
        try:
            await repository.write_classification_result(
                payload.session_id,
                {
                    "trail": [item.model_dump() for item in step.trail],
                    "result": step.result.__dict__,
                },
                step.result.category,
            )
        finally:
            await repository.close()

    return ClassifyResponse(
        complete=step.result is not None,
        question=step.question,
        options=step.options,
        trail=step.trail,
        result=(
            ClassificationResultResponse(**step.result.__dict__) if step.result is not None else None
        ),
    )


class EscalateResponse(BaseModel):
    tracking_id: str
    priority: str
    status: Literal["accepted"] = "accepted"


@app.post("/escalate", response_model=EscalateResponse)
async def escalate_endpoint(payload: EscalateRequest, _: str = Depends(current_user)) -> EscalateResponse:
    repository = await AsyncpgCorpusRepository.create(settings.database_url.get_secret_value())
    try:
        escalation = await create_escalation(payload, repository, notification_channel)
    finally:
        await repository.close()
    return EscalateResponse(tracking_id=escalation.tracking_id, priority=escalation.priority)
