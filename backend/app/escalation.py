from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, Field

from .observability import record_escalation, stage

Priority = Literal["low", "normal", "high", "urgent"]
ABSTAINED_REASON = "abstained-answer"


class EscalateRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=4000)
    reason: str = Field(min_length=1, max_length=256)
    priority: Priority = "normal"


@dataclass(frozen=True)
class Escalation:
    tracking_id: str
    session_id: str
    question: str
    reason: str
    priority: Priority


class EscalationRepository(Protocol):
    async def create_escalation(
        self,
        session_id: str,
        question: str,
        reason: str,
        priority: Priority,
    ) -> int: ...


class NotificationChannel(Protocol):
    async def notify(self, escalation: Escalation) -> None: ...


class LoggingNotificationChannel:
    """Default channel; replace this class with email or Slack delivery later."""

    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)

    async def notify(self, escalation: Escalation) -> None:
        self._logger.info(
            "escalation.created",
            extra={
                "tracking_id": escalation.tracking_id,
                "session_id": escalation.session_id,
                "priority": escalation.priority,
                "reason": escalation.reason,
            },
        )


class WebhookNotificationChannel:
    """Production notification delivery; sends IDs only, never the question text."""
    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url

    async def notify(self, escalation: Escalation) -> None:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(self._webhook_url, json={"tracking_id": escalation.tracking_id,
                "priority": escalation.priority, "reason": escalation.reason})
            response.raise_for_status()


def effective_priority(priority: Priority, reason: str) -> Priority:
    if reason == ABSTAINED_REASON and priority in ("low", "normal"):
        return "high"
    return priority


async def create_escalation(
    request: EscalateRequest,
    repository: EscalationRepository,
    notification_channel: NotificationChannel,
) -> Escalation:
    priority = effective_priority(request.priority, request.reason)
    with stage("escalation", priority=priority, reason=request.reason):
        database_id = await repository.create_escalation(request.session_id, request.question, request.reason, priority)
        escalation = Escalation(tracking_id=str(database_id), session_id=request.session_id,
                                question=request.question, reason=request.reason, priority=priority)
        await notification_channel.notify(escalation)
    record_escalation(priority, request.reason)
    return escalation
