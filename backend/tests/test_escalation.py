from dataclasses import dataclass

import pytest

from app.escalation import EscalateRequest, Escalation, create_escalation


@dataclass
class FakeRepository:
    next_id: int = 42
    calls: list[tuple[str, str, str, str]] | None = None

    async def create_escalation(
        self,
        session_id: str,
        question: str,
        reason: str,
        priority: str,
    ) -> int:
        if self.calls is None:
            self.calls = []
        self.calls.append((session_id, question, reason, priority))
        return self.next_id


class FakeChannel:
    def __init__(self) -> None:
        self.notifications: list[Escalation] = []

    async def notify(self, escalation: Escalation) -> None:
        self.notifications.append(escalation)


@pytest.mark.asyncio
async def test_general_question_is_persisted_and_notified() -> None:
    repository = FakeRepository()
    channel = FakeChannel()
    escalation = await create_escalation(
        EscalateRequest(session_id="s1", question="What applies?", reason="general-question"),
        repository,
        channel,
    )
    assert escalation.tracking_id == "42"
    assert escalation.priority == "normal"
    assert repository.calls == [("s1", "What applies?", "general-question", "normal")]
    assert channel.notifications == [escalation]


@pytest.mark.asyncio
async def test_abstained_answer_is_elevated_to_high_priority() -> None:
    repository = FakeRepository()
    channel = FakeChannel()
    escalation = await create_escalation(
        EscalateRequest(session_id="s2", question="Unanswered", reason="abstained-answer"),
        repository,
        channel,
    )
    assert escalation.priority == "high"
    assert repository.calls == [("s2", "Unanswered", "abstained-answer", "high")]


@pytest.mark.asyncio
async def test_explicit_urgent_priority_is_preserved() -> None:
    repository = FakeRepository()
    channel = FakeChannel()
    escalation = await create_escalation(
        EscalateRequest(
            session_id="s3",
            question="Urgent unanswered question",
            reason="abstained-answer",
            priority="urgent",
        ),
        repository,
        channel,
    )
    assert escalation.priority == "urgent"
