import logging
from asyncio import Lock
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal, cast

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
from .auth import audit_record_user, current_user, issue_test_token, require_role
from .bhashini import BhashiniClient, IndicLanguage
from .config import get_settings
from .db import check_database_connection
from .demo import DemoClaudeClient, DemoRepository, add_demo_session_upload, retrieve_demo
from .escalation import (
    EscalateRequest,
    LoggingNotificationChannel,
    WebhookNotificationChannel,
    create_escalation,
)
from .file_extract import extract_text as extract_file_text
from .gdrive import GoogleDriveClient
from .graph import AsyncpgGraphRepository, RelationshipType
from .ingest import (
    AsyncpgCorpusRepository,
    VoyageEmbedder,
    ingest_from_gdrive,
    ingest_from_text,
    ingest_from_url,
)
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
from .pinecone_store import OpenAIEmbedder, PineconeStore
from .prompt_policy import format_untrusted_chunk
from .rate_limit import RateLimiter
from .retrieve import AsyncpgCorpusRepositoryAdapter, CohereReranker, RerankedCandidate, retrieve
from .scraper import WebScraper
from .session_documents import (
    AsyncpgSessionUploadRepository,
    ingest_upload_for_session,
    retrieve_session_upload_chunks,
)
from .web_discovery import (
    GLOBAL_DEMO_STAGING_REPO,
    AsyncpgStagingRepository,
    BraveSearchProvider,
    StagingRepository,
    load_topics,
    run_discovery,
)

settings = get_settings()
configure_logging()
logger = logging.getLogger(__name__)
notification_channel = (WebhookNotificationChannel(settings.notification_webhook_url.get_secret_value())
                        if settings.notification_provider == "webhook" and settings.notification_webhook_url else LoggingNotificationChannel())
rate_limiter = RateLimiter()


@asynccontextmanager
async def application_lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Own long-lived outbound connections for the lifetime of one worker."""
    application.state.http_client = httpx.AsyncClient(timeout=90)
    application.state.repository = None
    application.state.repository_lock = Lock()
    try:
        yield
    finally:
        repository = application.state.repository
        if repository is not None:
            await repository.close()
        await application.state.http_client.aclose()


app = FastAPI(title=settings.app_name, lifespan=application_lifespan)
configure_tracing(settings, app)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=True,
                   allow_methods=["GET", "POST", "DELETE"], allow_headers=["Authorization", "Content-Type", "X-Request-ID"])


async def get_repository(request: Request) -> AsyncpgCorpusRepository:
    if settings.demo_mode:
        return cast(AsyncpgCorpusRepository, DemoRepository())
    repository = cast(AsyncpgCorpusRepository | None, getattr(request.app.state, "repository", None))
    if repository is not None:
        return repository
    lock = cast(Lock, getattr(request.app.state, "repository_lock", None) or Lock())
    request.app.state.repository_lock = lock
    async with lock:
        repository = cast(AsyncpgCorpusRepository | None, getattr(request.app.state, "repository", None))
        if repository is None:
            repository = await AsyncpgCorpusRepository.create(settings.database_url.get_secret_value())
            request.app.state.repository = repository
    return repository


def get_http_client(request: Request) -> httpx.AsyncClient:
    client = cast(httpx.AsyncClient | None, getattr(request.app.state, "http_client", None))
    if client is None:
        client = httpx.AsyncClient(timeout=90)
        request.app.state.http_client = client
    return client


RepositoryDep = Annotated[AsyncpgCorpusRepository, Depends(get_repository)]
HttpClientDep = Annotated[httpx.AsyncClient, Depends(get_http_client)]


class RetrieveRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    jurisdiction: Literal["IN", "INTL", "BOTH"]
    language: IndicLanguage = "en"
    session_id: str | None = None


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
    jurisdiction: Literal["IN", "INTL", "USER_UPLOAD"]
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


class DevSessionResponse(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int = 14_400


class ClassifyRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    trail: list[TrailStep] = Field(default_factory=list)
    answer_index: int | None = Field(default=None, ge=0)


class ClassificationResultResponse(BaseModel):
    category: str
    regulatory_path: str
    ip_posture: str
    abs_note: str
    abs_actions: list[str]
    tkdl_prior_art_guidance: str | None = None
    recommended_ip_routes: list[str]
    official_sources: list["OfficialSourceLink"]


class OfficialSourceLink(BaseModel):
    """A human-operated public portal; this service does not submit searches to it."""

    label: str
    url: str
    description: str


def official_sources_for(category: str) -> list[OfficialSourceLink]:
    """Return relevant public research portals without implying a clearance search."""
    sources = [OfficialSourceLink(
        label="IP India E-Services",
        url="https://ipindia.gov.in/pages/e-services",
        description="Official Indian public-search and status-service directory.",
    )]
    if category in {"patent-or-proprietary", "new/non-classical drug", "phytopharmaceutical", "cosmetic"}:
        sources.append(OfficialSourceLink(
            label="WIPO PATENTSCOPE",
            url="https://patentscope.wipo.int/search/en/search.jsf",
            description="WIPO's public search portal for international and national patent collections.",
        ))
    if category in {"classical/generic", "Ayurveda-Aahar/nutraceutical", "phytopharmaceutical"}:
        sources.append(OfficialSourceLink(
            label="Traditional Knowledge Digital Library (TKDL)",
            url="https://www.tkdl.res.in/tkdl/langdefault/common/Home.asp?GL=Eng",
            description="Official TKDL information; database access is subject to its access arrangements.",
        ))
    sources.append(OfficialSourceLink(
        label="WIPO Global Brand Database",
        url="https://branddb.wipo.int/",
        description="WIPO's public brand, appellation-of-origin, and official-emblem search portal.",
    ))
    return sources


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
    csp = "default-src 'none'; frame-ancestors 'none'"
    if request.url.path in {"/docs", "/redoc", "/openapi.json"}:
        csp = "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; frame-ancestors 'none'"
    response.headers.update({
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Content-Security-Policy": csp,
    })
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
    limits = {
        "/ask": settings.ask_rate_limit_per_minute,
        "/retrieve": settings.retrieve_rate_limit_per_minute,
        "/escalate": settings.ask_rate_limit_per_minute,
        "/classify/next": settings.retrieve_rate_limit_per_minute,
        "/ask/upload": settings.ask_rate_limit_per_minute,
    }
    limit = limits.get(request.url.path)
    if request.method == "POST" and limit is not None:
        client_id = request.client.host if request.client else "unknown"
        if settings.rate_limit_backend == "memory" and not rate_limiter.allow(request.url.path, client_id, limit):
            return JSONResponse(status_code=status.HTTP_429_TOO_MANY_REQUESTS, content={"detail": "Rate limit exceeded"}, headers={"Retry-After": "60"})
    return await call_next(request)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/auth/dev-session", response_model=DevSessionResponse)
async def create_dev_session() -> DevSessionResponse:
    """Issue an ephemeral local-demo identity; unreachable unless explicitly enabled."""
    if not settings.enable_dev_session_endpoint:
        raise HTTPException(status_code=404, detail="Not found")
    return DevSessionResponse(access_token=issue_test_token(f"local-{new_request_id()}", expires_in_seconds=14_400))


@app.get("/ready")
async def ready() -> JSONResponse:
    database_ready = await check_database_connection()
    if not database_ready:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready", "database": "unavailable"},
        )
    return JSONResponse(content={"status": "ready", "database": "available"})


async def retrieve_for_request(
    query: str,
    jurisdiction: Literal["IN", "INTL", "BOTH"],
    repository: AsyncpgCorpusRepository,
    http_client: httpx.AsyncClient,
    session_id: str | None = None,
) -> list[RerankedCandidate]:
    if settings.demo_mode:
        return retrieve_demo(query, jurisdiction, Path(__file__).resolve().parents[2] / "corpus", session_id=session_id)
    async with VoyageEmbedder(settings, http_client) as embedder, CohereReranker(settings, http_client) as reranker:
        results = await retrieve(
            query, jurisdiction, AsyncpgCorpusRepositoryAdapter(repository), embedder, reranker,
            settings.min_relevance,
        )
        pool = getattr(repository, "pool", getattr(repository, "_pool", None))
        if session_id and pool is not None:
            upload_repo = AsyncpgSessionUploadRepository(pool)
            session_chunks = await retrieve_session_upload_chunks(
                session_id=session_id,
                query=query,
                embedder=embedder,
                repository=upload_repo,
            )
            if session_chunks:
                session_candidates = [
                    RerankedCandidate(candidate=chunk, relevance_score=chunk.fused_score)
                    for chunk in session_chunks
                ]
                results = session_candidates + results
        return results


async def english_query(query: str, language: IndicLanguage, http_client: httpx.AsyncClient) -> str:
    """Translate the retrieval representation without mutating the submitted query."""
    if language == "en":
        return query
    if not settings.bhashini_api_key:
        return query
    try:
        return await BhashiniClient(settings, http_client).translate(query, language, "en")
    except Exception as error:
        logger.warning("translation.fallback", extra={"error_type": type(error).__name__})
        return query


@app.post("/retrieve", response_model=RetrieveResponse)
async def retrieve_endpoint(
    payload: RetrieveRequest,
    repository: RepositoryDep,
    http_client: HttpClientDep,
) -> RetrieveResponse:
    try:
        results = await retrieve_for_request(
            await english_query(payload.query, payload.language, http_client),
            payload.jurisdiction,
            repository,
            http_client,
            session_id=payload.session_id,
        )
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
async def transcribe_endpoint(payload: SpeechToTextRequest, http_client: HttpClientDep) -> SpeechToTextResponse:
    try:
        return SpeechToTextResponse(
            transcript=await BhashiniClient(settings, http_client).transcribe(payload.audio_base64, payload.language)
        )
    except (RuntimeError, httpx.HTTPError) as error:
        logger.warning("retrieve.unavailable", extra={"error_type": type(error).__name__})
        raise HTTPException(status_code=503, detail="Retrieval service unavailable") from error


@app.post("/speech/synthesize", response_model=TextToSpeechResponse)
async def synthesize_endpoint(payload: TextToSpeechRequest, http_client: HttpClientDep) -> TextToSpeechResponse:
    try:
        audio, audio_format = await BhashiniClient(settings, http_client).synthesize(payload.text, payload.language)
        return TextToSpeechResponse(audio_base64=audio, audio_format=audio_format)
    except (RuntimeError, httpx.HTTPError) as error:
        logger.warning("speech.unavailable", extra={"error_type": type(error).__name__})
        raise HTTPException(status_code=503, detail="Speech service unavailable") from error


@app.post("/ask", response_model=AskResponse)
async def ask_endpoint(
    payload: AskRequest,
    repository: RepositoryDep,
    http_client: HttpClientDep,
    user_id: str | None = Depends(audit_record_user),
) -> AskResponse:
    try:
        translated_payload = payload.model_copy(
            update={"translated_query": await english_query(payload.query, payload.language, http_client)}
        )
        if settings.demo_mode:
            return await answer_question(
                translated_payload,
                lambda query, jurisdiction: retrieve_for_request(query, jurisdiction, repository, http_client, payload.session_id),
                DemoClaudeClient(),
                repository,
                request_id_context.get(),
                settings.weak_reranker_score,
                high_confidence_reranker_score=settings.high_confidence_reranker_score,
                user_id=user_id,
            )
        async with AnthropicClaudeClient(settings, http_client) as claude:
                async def execute_tool(call: ToolCall) -> dict[str, object]:
                    if call.name == "retrieve_chunks":
                        query = call.arguments.get("query")
                        jurisdiction = call.arguments.get("jurisdiction")
                        if not isinstance(query, str) or jurisdiction not in {"IN", "INTL", "BOTH"}:
                            return {"error": "retrieve_chunks requires query and a valid jurisdiction"}
                        results = await retrieve_for_request(query, jurisdiction, repository, http_client, payload.session_id)
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
                        graph = AsyncpgGraphRepository(repository.pool)
                        relationships = await graph.lookup(entity, RelationshipType(relation))
                    except ValueError:
                        return {"error": "graph_lookup received an unsupported relation"}
                    return {"relationships": [{"source": edge.source.name, "relation": edge.relationship_type.value,
                                                "target": edge.target.name} for edge in relationships]}

                return await answer_question(
                    translated_payload,
                    lambda query, jurisdiction: retrieve_for_request(query, jurisdiction, repository, http_client, payload.session_id),
                    claude,
                    repository,
                    request_id_context.get(),
                    settings.weak_reranker_score,
                    execute_tool,
                    settings.agentic_timeout_seconds,
                    settings.high_confidence_reranker_score,
                    user_id,
                )
    except (RuntimeError, httpx.HTTPError) as error:
        logger.warning("ask.unavailable", extra={"error_type": type(error).__name__})
        raise HTTPException(status_code=503, detail="Answer service unavailable") from error


@app.get("/admin/review-queue", response_model=list[ReviewQueueItem])
async def list_review_queue(
    repository: RepositoryDep,
    limit: int = 100,
    _: str = Depends(require_role("legal_reviewer")),
) -> list[ReviewQueueItem]:
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    return [ReviewQueueItem(**{**item, "created_at": item["created_at"].isoformat()})
            for item in await repository.list_review_queue(limit)]


@app.patch("/admin/review-queue/{queue_id}", status_code=status.HTTP_204_NO_CONTENT)
async def resolve_review_queue_item(
    queue_id: int,
    payload: ReviewQueueResolution,
    repository: RepositoryDep,
    reviewer: str = Depends(require_role("legal_reviewer")),
) -> Response:
    if not await repository.resolve_review_queue_item(queue_id, payload.status, reviewer, payload.resolution_note):
        raise HTTPException(status_code=404, detail="Pending review-queue item not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/paid-sources/credentials", status_code=status.HTTP_204_NO_CONTENT)
async def save_paid_source_credential(payload: PaidCredentialRequest, repository: RepositoryDep, user_id: str = Depends(current_user)) -> Response:
    with stage("paid_source.credentials", provider=payload.provider):
        kek_version, kek = await SecretManagerKekProvider(settings.credential_kek_secret_resource).get_kek()
        encrypted = envelope_encrypt(payload.credential, kek)
        await repository.store_paid_source_credential(user_id, payload.provider, encrypted, kek_version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/paid-sources/{provider}/search")
async def paid_source_search(provider: str, payload: PaidSearchRequest, repository: RepositoryDep, user_id: str = Depends(current_user)) -> dict[str, object]:
    if not payload.consent_accepted:
        raise HTTPException(status_code=422, detail="Explicit consent is required before a paid-source call")
    if provider != StubPaidSourceConnector.provider or not settings.allow_stub_connectors:
        raise HTTPException(status_code=404, detail="Unknown paid-source provider")
    with stage("paid_source.connector", provider=provider):
        await repository.log_paid_source_consent(user_id, provider, await consent_event(user_id, provider, payload.query))
        results = await StubPaidSourceConnector().search(payload.query)
    return {"results": results}


@app.get("/privacy/export")
async def export_own_data(repository: RepositoryDep, user_id: str = Depends(current_user)) -> dict[str, object]:
    return await repository.export_user_data(user_id)


@app.delete("/privacy/data", response_model=DataDeletionResponse)
async def delete_own_data(repository: RepositoryDep, user_id: str = Depends(current_user)) -> DataDeletionResponse:
    return DataDeletionResponse(deleted=await repository.delete_user_data(user_id))


@app.post("/classify/next", response_model=ClassifyResponse)
async def classify_next(
    payload: ClassifyRequest,
    repository: RepositoryDep,
) -> ClassifyResponse:
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
        await repository.write_classification_result(
            payload.session_id,
            {
                "trail": [item.model_dump() for item in step.trail],
                "result": step.result.__dict__,
            },
            step.result.category,
        )

    return ClassifyResponse(
        complete=step.result is not None,
        question=step.question,
        options=step.options,
        trail=step.trail,
        result=(
            ClassificationResultResponse(
                **step.result.__dict__, official_sources=official_sources_for(step.result.category)
            ) if step.result is not None else None
        ),
    )


class EscalateResponse(BaseModel):
    tracking_id: str
    priority: str
    status: Literal["accepted"] = "accepted"


@app.post("/escalate", response_model=EscalateResponse)
async def escalate_endpoint(
    payload: EscalateRequest,
    repository: RepositoryDep,
    user_id: str = Depends(current_user),
) -> EscalateResponse:
    escalation = await create_escalation(payload, repository, notification_channel, user_id)
    return EscalateResponse(tracking_id=escalation.tracking_id, priority=escalation.priority)


class IngestGDriveRequest(BaseModel):
    file_id: str = Field(min_length=1)
    jurisdiction: Literal["IN", "INTL"] = "IN"


class IngestUrlRequest(BaseModel):
    url: str = Field(min_length=1)
    jurisdiction: Literal["IN", "INTL"] = "IN"


class IngestUploadRequest(BaseModel):
    filename: str = Field(min_length=1)
    content: str = Field(min_length=1)
    jurisdiction: Literal["IN", "INTL"] = "IN"


class IngestResponse(BaseModel):
    status: Literal["inserted", "changed", "unchanged"]
    chunk_count: int
    pinecone_synced: bool = False


@app.post("/ingest/gdrive", response_model=IngestResponse)
async def ingest_gdrive_endpoint(
    payload: IngestGDriveRequest,
    repository: RepositoryDep,
    http_client: HttpClientDep,
    _: str = Depends(require_role("legal_reviewer")),
) -> IngestResponse:
    if settings.demo_mode:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document ingestion is disabled in DEMO_MODE",
        )
    if not settings.voyage_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="VOYAGE_API_KEY must be configured for document ingestion",
        )
    if not settings.google_drive_credentials_json:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GOOGLE_DRIVE_CREDENTIALS_JSON must be configured for Google Drive ingestion",
        )

    try:
        async with (
            GoogleDriveClient(settings, http_client) as gdrive_client,
            VoyageEmbedder(settings, http_client) as embedder,
        ):
            pinecone_store, pinecone_embedder = None, None
            pinecone_synced = False
            if settings.pinecone_api_key and settings.openai_api_key:
                pinecone_store = PineconeStore(settings, http_client)
                pinecone_embedder = OpenAIEmbedder(settings, http_client)
                pinecone_synced = True

            outcome = await ingest_from_gdrive(
                file_id=payload.file_id,
                gdrive_client=gdrive_client,
                repository=repository,
                embedder=embedder,
                pinecone_store=pinecone_store,
                pinecone_embedder=pinecone_embedder,
                jurisdiction=payload.jurisdiction,
            )
            return IngestResponse(
                status=outcome.status,
                chunk_count=outcome.chunk_count,
                pinecone_synced=pinecone_synced,
            )
    except (RuntimeError, ValueError, httpx.HTTPError) as error:
        logger.warning("ingest.gdrive.failed", extra={"error_type": type(error).__name__})
        raise HTTPException(status_code=502, detail=f"Google Drive ingestion failed: {error}") from error


@app.post("/ingest/url", response_model=IngestResponse)
async def ingest_url_endpoint(
    payload: IngestUrlRequest,
    repository: RepositoryDep,
    http_client: HttpClientDep,
    _: str = Depends(require_role("legal_reviewer")),
) -> IngestResponse:
    if settings.demo_mode:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document ingestion is disabled in DEMO_MODE",
        )
    if not settings.voyage_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="VOYAGE_API_KEY must be configured for document ingestion",
        )

    try:
        async with (
            WebScraper(settings, http_client) as scraper,
            VoyageEmbedder(settings, http_client) as embedder,
        ):
            pinecone_store, pinecone_embedder = None, None
            pinecone_synced = False
            if settings.pinecone_api_key and settings.openai_api_key:
                pinecone_store = PineconeStore(settings, http_client)
                pinecone_embedder = OpenAIEmbedder(settings, http_client)
                pinecone_synced = True

            outcome = await ingest_from_url(
                url=payload.url,
                scraper=scraper,
                repository=repository,
                embedder=embedder,
                pinecone_store=pinecone_store,
                pinecone_embedder=pinecone_embedder,
                jurisdiction=payload.jurisdiction,
            )
            return IngestResponse(
                status=outcome.status,
                chunk_count=outcome.chunk_count,
                pinecone_synced=pinecone_synced,
            )
    except (RuntimeError, ValueError, httpx.HTTPError) as error:
        logger.warning("ingest.url.failed", extra={"error_type": type(error).__name__})
        raise HTTPException(status_code=502, detail=f"Web scraping ingestion failed: {error}") from error


@app.post("/ingest/upload", response_model=IngestResponse)
async def ingest_upload_endpoint(
    payload: IngestUploadRequest,
    repository: RepositoryDep,
    http_client: HttpClientDep,
    _: str = Depends(require_role("legal_reviewer")),
) -> IngestResponse:
    if settings.demo_mode:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document ingestion is disabled in DEMO_MODE",
        )
    if not settings.voyage_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="VOYAGE_API_KEY must be configured for document ingestion",
        )

    try:
        async with VoyageEmbedder(settings, http_client) as embedder:
            pinecone_store, pinecone_embedder = None, None
            pinecone_synced = False
            if settings.pinecone_api_key and settings.openai_api_key:
                pinecone_store = PineconeStore(settings, http_client)
                pinecone_embedder = OpenAIEmbedder(settings, http_client)
                pinecone_synced = True

            outcome = await ingest_from_text(
                filename=payload.filename,
                text=payload.content,
                repository=repository,
                embedder=embedder,
                pinecone_store=pinecone_store,
                pinecone_embedder=pinecone_embedder,
                jurisdiction=payload.jurisdiction,
            )
            return IngestResponse(
                status=outcome.status,
                chunk_count=outcome.chunk_count,
                pinecone_synced=pinecone_synced,
            )
    except (RuntimeError, ValueError, httpx.HTTPError) as error:
        logger.warning("ingest.upload.failed", extra={"error_type": type(error).__name__})
        raise HTTPException(status_code=502, detail=f"Upload ingestion failed: {error}") from error


# ──────────────────────────────────────────────────────────────────────────────
# Web Discovery & Corpus Staging
# ──────────────────────────────────────────────────────────────────────────────


class DiscoveryResponse(BaseModel):
    candidates_found: int
    staged: int
    duplicate: int
    robots_blocked: int
    fetch_failed: int
    empty: int


class StagedCandidateResponse(BaseModel):
    id: int
    url: str
    title: str
    topic: str
    jurisdiction: Literal["IN", "INTL"]
    body_text: str
    source_hash: str
    status: Literal["pending_review", "promoted", "rejected"]
    reviewed_by: str | None = None
    rejection_reason: str | None = None


class StagingActionRequest(BaseModel):
    action: Literal["promote", "reject"]
    reason: str = Field(default="", max_length=4000)


@app.post("/discover", response_model=DiscoveryResponse)
async def run_discovery_endpoint(
    repository: RepositoryDep,
    http_client: HttpClientDep,
    _: str = Depends(require_role("legal_reviewer")),
) -> DiscoveryResponse:
    """Crawl seed sources and stage new candidate documents for review."""
    topics = load_topics()
    search_provider = None
    if settings.brave_search_api_key:
        search_provider = BraveSearchProvider(
            settings.brave_search_api_key.get_secret_value(), http_client
        )

    staging_repo: StagingRepository
    if settings.demo_mode:
        staging_repo = GLOBAL_DEMO_STAGING_REPO
    else:
        staging_repo = AsyncpgStagingRepository(repository.pool)

    async with WebScraper(settings, http_client) as scraper:
        stats = await run_discovery(
            topics,
            scraper,
            staging_repo,
            search_provider,
            settings.discovery_max_candidates_per_topic,
        )

    return DiscoveryResponse(
        candidates_found=stats.candidates_found,
        staged=stats.staged,
        duplicate=stats.duplicate,
        robots_blocked=stats.robots_blocked,
        fetch_failed=stats.fetch_failed,
        empty=stats.empty,
    )


@app.get(
    "/admin/corpus-staging", response_model=list[StagedCandidateResponse]
)
async def list_staging_candidates(
    repository: RepositoryDep,
    _: str = Depends(require_role("legal_reviewer")),
) -> list[StagedCandidateResponse]:
    staging_repo: StagingRepository = GLOBAL_DEMO_STAGING_REPO if settings.demo_mode else AsyncpgStagingRepository(repository.pool)
    candidates = await staging_repo.list_pending()
    return [StagedCandidateResponse(**c.__dict__) for c in candidates]


@app.get(
    "/admin/corpus-staging/{staging_id}",
    response_model=StagedCandidateResponse,
)
async def get_staging_candidate(
    staging_id: int,
    repository: RepositoryDep,
    _: str = Depends(require_role("legal_reviewer")),
) -> StagedCandidateResponse:
    staging_repo: StagingRepository = GLOBAL_DEMO_STAGING_REPO if settings.demo_mode else AsyncpgStagingRepository(repository.pool)
    candidate = await staging_repo.get(staging_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Staging candidate not found")
    return StagedCandidateResponse(**candidate.__dict__) if hasattr(candidate, "__dict__") else candidate


@app.patch(
    "/admin/corpus-staging/{staging_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def act_on_staging_candidate(
    staging_id: int,
    payload: StagingActionRequest,
    repository: RepositoryDep,
    http_client: HttpClientDep,
    reviewer: str = Depends(require_role("legal_reviewer")),
) -> Response:
    staging_repo: StagingRepository = GLOBAL_DEMO_STAGING_REPO if settings.demo_mode else AsyncpgStagingRepository(repository.pool)
    candidate = await staging_repo.get(staging_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Staging candidate not found")
    if candidate.status != "pending_review":
        raise HTTPException(
            status_code=409, detail=f"Candidate already {candidate.status}"
        )
    if payload.action == "promote":
        if not settings.demo_mode:
            if not settings.voyage_api_key:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="VOYAGE_API_KEY must be configured to ingest promoted candidate",
                )
            async with VoyageEmbedder(settings, http_client) as embedder:
                await ingest_from_text(
                    filename=f"staged-{candidate.id}.md",
                    text=candidate.body_text,
                    repository=repository,
                    embedder=embedder,
                    jurisdiction=candidate.jurisdiction,
                )
        await staging_repo.mark_promoted(staging_id, reviewer)
    else:
        await staging_repo.mark_rejected(staging_id, reviewer, payload.reason)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ──────────────────────────────────────────────────────────────────────────────
# Session-scoped file upload for /ask
# ──────────────────────────────────────────────────────────────────────────────


class SessionUploadRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    filename: str = Field(min_length=1, max_length=512)
    content_base64: str = Field(min_length=1)
    content_type: str = Field(default="application/octet-stream")


class SessionUploadResponse(BaseModel):
    upload_id: int
    filename: str
    chunk_count: int
    char_count: int


@app.post("/ask/upload", response_model=SessionUploadResponse)
async def upload_session_document(
    payload: SessionUploadRequest,
    repository: RepositoryDep,
    http_client: HttpClientDep,
    user_id: str | None = Depends(audit_record_user),
) -> SessionUploadResponse:
    """Upload a document for session-scoped Q&A. Not added to the verified corpus."""
    import base64
    import binascii

    try:
        file_bytes = base64.b64decode(payload.content_base64)
    except (binascii.Error, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid base64 content",
        ) from None

    text = extract_file_text(file_bytes, payload.filename, payload.content_type)
    if not text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No extractable text in uploaded file",
        )

    if settings.demo_mode:
        chunk_count = add_demo_session_upload(payload.session_id, payload.filename, text)
        return SessionUploadResponse(
            upload_id=1, filename=payload.filename, chunk_count=chunk_count, char_count=len(text)
        )

    if not settings.voyage_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="VOYAGE_API_KEY must be configured",
        )

    async with VoyageEmbedder(settings, http_client) as embedder:
        session_repo = AsyncpgSessionUploadRepository(repository.pool)
        result = await ingest_upload_for_session(
            session_id=payload.session_id,
            filename=payload.filename,
            text=text,
            content_type=payload.content_type,
            embedder=embedder,
            repository=session_repo,
            uploaded_by=user_id,
            ttl_hours=settings.session_upload_ttl_hours,
        )

    return SessionUploadResponse(
        upload_id=result.upload_id,
        filename=result.filename,
        chunk_count=result.chunk_count,
        char_count=result.char_count,
    )
