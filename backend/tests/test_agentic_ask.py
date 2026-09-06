from dataclasses import dataclass, field
from typing import Any

import pytest

from app.ask import AgentTurn, AskAnswer, AskRequest, ToolCall, answer_question
from app.retrieve import RerankedCandidate, SearchCandidate


def evidence(chunk_id: str) -> RerankedCandidate:
    return RerankedCandidate(
        SearchCandidate(chunk_id, 1, "Patents Act, 1970", "Section 3(p)", "IN", "Traditional knowledge."), 0.9
    )


@dataclass
class QaAudit:
    rows: list[tuple[Any, ...]] = field(default_factory=list)

    async def write_qa_log(self, *args: Any) -> None:
        self.rows.append(args)


class ScriptedAgent:
    def __init__(self, turns: list[AgentTurn]) -> None:
        self.turns = turns

    async def agent_turn(self, system_prompt: str, messages: list[dict[str, Any]]) -> AgentTurn:
        return self.turns.pop(0)


def tool_turn(name: str, call_id: str, arguments: dict[str, Any]) -> AgentTurn:
    return AgentTurn([{"type": "tool_use", "id": call_id, "name": name, "input": arguments}], None, [ToolCall(name, arguments, call_id)])  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_agentic_answer_uses_retrieval_then_graph_lookup() -> None:
    agent = ScriptedAgent([
        tool_turn("retrieve_chunks", "call-1", {"query": "Section 3(p)", "jurisdiction": "IN"}),
        tool_turn("graph_lookup", "call-2", {"entity": "Patents Act, 1970 - Section 3(p)", "relation": "APPLIES_TO_CATEGORY"}),
        AgentTurn([], AskAnswer(mode="single", answer="Section 3(p) applies to classical formulations. [seed]", citations=["seed"], confidence="high", abstain=False), []),
    ])
    audit = QaAudit()
    executed: list[str] = []

    async def retrieve(query: str, jurisdiction: str) -> list[RerankedCandidate]:
        return [evidence("seed")]

    async def execute(call: ToolCall) -> dict[str, object]:
        executed.append(call.name)
        return {"ok": call.name}

    response = await answer_question(
        AskRequest(query="Which category does Section 3(p) apply to?", jurisdiction="IN", session_id="agent-1", multi_hop=True),
        retrieve, agent, audit, "request-1", 0.35, execute, 5,
    )

    assert response.abstain is False
    assert response.answer == "Section 3(p) applies to classical formulations. [seed]"
    assert executed == ["retrieve_chunks", "graph_lookup"]
    assert [entry["name"] for entry in audit.rows[0][-1]] == executed


@pytest.mark.asyncio
async def test_agentic_tool_call_cap_stops_fourth_call_server_side() -> None:
    agent = ScriptedAgent([tool_turn("retrieve_chunks", f"call-{number}", {"query": "q", "jurisdiction": "IN"}) for number in range(1, 5)])
    audit = QaAudit()
    executed: list[str] = []

    async def retrieve(query: str, jurisdiction: str) -> list[RerankedCandidate]:
        return [evidence("seed")]

    async def execute(call: ToolCall) -> dict[str, object]:
        executed.append(call.call_id)
        return {"ok": True}

    response = await answer_question(
        AskRequest(query="Keep searching", jurisdiction="IN", session_id="agent-2", multi_hop=True),
        retrieve, agent, audit, "request-2", 0.35, execute, 5,
    )

    assert response.abstain is True
    assert response.reason == "agent_tool_call_limit"
    assert executed == ["call-1", "call-2", "call-3"]
    assert len(audit.rows[0][-1]) == 3
