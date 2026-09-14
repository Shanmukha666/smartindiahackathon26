from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from app.config import Settings
from app.demo import DEMO_SESSION_UPLOADS, add_demo_session_upload
from app.main import retrieve_for_request
from app.retrieve import RerankedCandidate, SearchCandidate


@pytest.mark.asyncio
async def test_demo_upload_retrieval_wiring() -> None:
    """In demo mode, uploaded session documents are indexed in DEMO_SESSION_UPLOADS
    and retrieved with realistic scores based on query overlap."""
    session_id = "test_demo_wiring_sess_1"
    DEMO_SESSION_UPLOADS.pop(session_id, None)

    num_chunks = add_demo_session_upload(
        session_id=session_id,
        filename="turmeric_formulation.txt",
        text="Curcuma longa rhizome extraction method for topical inflammation and joint mobility.",
    )
    assert num_chunks > 0

    dummy_repo = MagicMock()
    with patch("app.main.settings", Settings(demo_mode=True)):
        async with httpx.AsyncClient() as client:
            results = await retrieve_for_request(
                query="Curcuma longa extraction",
                jurisdiction="IN",
                repository=dummy_repo,
                http_client=client,
                session_id=session_id,
            )

    # Should find the uploaded chunk with jurisdiction="USER_UPLOAD"
    upload_results = [
        r for r in results if r.candidate.jurisdiction == "USER_UPLOAD"
    ]
    assert len(upload_results) >= 1
    assert "Curcuma longa" in upload_results[0].candidate.chunk_text
    # Relevance score should be calculated dynamically
    assert 0.5 <= upload_results[0].relevance_score <= 1.0


@pytest.mark.asyncio
async def test_non_demo_session_upload_retrieval_preserves_authentic_fused_score() -> None:
    """In production mode, retrieve_for_request uses chunk.fused_score
    rather than a hardcoded 0.92 score."""
    test_settings = Settings(demo_mode=False)

    fake_candidate = SearchCandidate(
        chunk_id="chunk-up-1",
        document_id=999,
        instrument="Client Prior Art Report.pdf",
        section="Section 1",
        jurisdiction="USER_UPLOAD",
        chunk_text="Client describes an Ayurvedic compound including ashwagandha and pippali.",
        fused_score=0.8123,
    )

    fake_corpus_candidate = SearchCandidate(
        chunk_id="chunk-corp-1",
        document_id=1,
        instrument="Patents Act, 1970",
        section="Section 3(p)",
        jurisdiction="IN",
        chunk_text="Inventions relating to traditional knowledge not patentable.",
        fused_score=0.88,
    )

    repo = MagicMock()
    repo.pool = MagicMock()

    client = AsyncMock(spec=httpx.AsyncClient)

    with patch("app.main.settings", test_settings), \
         patch("app.main.VoyageEmbedder") as mock_voyage, \
         patch("app.main.CohereReranker") as mock_cohere, \
         patch("app.main.retrieve", new_callable=AsyncMock) as mock_retrieve, \
         patch("app.main.retrieve_session_upload_chunks", new_callable=AsyncMock) as mock_retrieve_uploads:

        mock_voyage.return_value.__aenter__.return_value = AsyncMock()
        mock_cohere.return_value.__aenter__.return_value = AsyncMock()

        mock_retrieve.return_value = [
            RerankedCandidate(candidate=fake_corpus_candidate, relevance_score=0.88)
        ]
        mock_retrieve_uploads.return_value = [fake_candidate]

        results = await retrieve_for_request(
            query="ashwagandha formulation prior art",
            jurisdiction="IN",
            repository=repo,
            http_client=client,
            session_id="session_abc_123",
        )

        assert len(results) == 2
        # Session upload chunk is prepended
        first = results[0]
        assert first.candidate.jurisdiction == "USER_UPLOAD"
        # Authentic score 0.8123 preserved, NOT hardcoded 0.92
        assert first.relevance_score == 0.8123
        assert first.relevance_score != 0.92
