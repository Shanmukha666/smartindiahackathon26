from dataclasses import dataclass
from typing import Any

import pytest

from app.ask import AskAnswer, AskRequest, answer_question
from app.bhashini import BhashiniClient
from app.retrieve import RerankedCandidate, SearchCandidate


def candidate(chunk_id: str = "patents-3p") -> RerankedCandidate:
    return RerankedCandidate(
        SearchCandidate(chunk_id, 1, "Patents Act", "Section 3(p)", "IN", "English corpus text."),
        0.9,
    )


@dataclass
class Claude:
    response: AskAnswer

    async def answer(self, system_prompt: str, user_prompt: str) -> AskAnswer:
        return self.response


class AuditWriter:
    def __init__(self) -> None:
        self.args: tuple[Any, ...] | None = None

    async def write_qa_log(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs


@pytest.mark.asyncio
async def test_bhashini_translation_round_trip_uses_pipeline_response(monkeypatch: pytest.MonkeyPatch) -> None:
    client = object.__new__(BhashiniClient)
    seen: list[tuple[str, str]] = []

    async def translate(text: str, source: str, target: str = "en") -> str:
        seen.append((source, target))
        return "What is excluded?" if target == "en" else "क्या बाहर है?"

    monkeypatch.setattr(client, "translate", translate)
    english = await client.translate("क्या बाहर है?", "hi")
    hindi = await client.translate(english, "en", "hi")

    assert english == "What is excluded?"
    assert hindi == "क्या बाहर है?"
    assert seen == [("hi", "en"), ("en", "hi")]


@pytest.mark.asyncio
async def test_non_english_query_retrieves_english_source_and_preserves_citation_ids() -> None:
    retrieved_queries: list[str] = []
    audit = AuditWriter()

    async def retrieve(query: str, jurisdiction: str) -> list[RerankedCandidate]:
        retrieved_queries.append(query)
        return [candidate()]

    response = await answer_question(
        AskRequest(
            query="पेटेंट अधिनियम में क्या बाहर रखा गया है?",
            translated_query="What is excluded under the Patents Act?",
            language="hi",
            jurisdiction="IN",
            session_id="indic-session",
        ),
        retrieve,
        Claude(AskAnswer(mode="single", answer="It is excluded [patents-3p].", citations=["patents-3p"], confidence="high", abstain=False)),
        audit,
        "indic-request",
        0.35,
    )

    assert retrieved_queries == ["What is excluded under the Patents Act?"]
    assert response.citations == ["patents-3p"]
    assert audit.args[5]["_query_audit"] == {
        "original_query": "पेटेंट अधिनियम में क्या बाहर रखा गया है?",
        "translated_query": "What is excluded under the Patents Act?",
        "language": "hi",
    }


@pytest.mark.asyncio
async def test_bhashini_client_sends_language_pair_and_extracts_translation() -> None:
    client = object.__new__(BhashiniClient)

    async def run(task: dict[str, Any], input_data: dict[str, Any]) -> dict[str, Any]:
        assert task["config"]["language"] == {"sourceLanguage": "ta", "targetLanguage": "en"}
        assert input_data == {"input": [{"source": "எது விலக்கப்பட்டுள்ளது?"}]}
        return {"pipelineResponse": [{"output": [{"target": "What is excluded?"}]}]}

    client._run = run  # type: ignore[method-assign]
    assert await client.translate("எது விலக்கப்பட்டுள்ளது?", "ta") == "What is excluded?"
