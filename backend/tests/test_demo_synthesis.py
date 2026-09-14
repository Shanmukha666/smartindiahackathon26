from __future__ import annotations

from app.demo import _synthesize_answer


def test_demo_synthesize_citations_found() -> None:
    text = "Here is Citation 1: Charaka Samhita Sutrasthana chapter 4 decoction. And details."
    answer = _synthesize_answer("What are the citations?", "chunk-1", text)
    assert "Charaka Samhita" in answer
    assert "Section 3(p)" in answer


def test_demo_synthesize_no_citations_honestly_reports_none() -> None:
    text = "General discussion on botanical formulations without any specific textual references."
    answer = _synthesize_answer("What are the prior art citations?", "chunk-1", text)
    assert "No specific prior art citations were identified" in answer
    # Must NOT have fabricated citations
    assert "Bhavaprakasha" not in answer
