from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def now() -> datetime:
    return datetime.now(UTC)


class ActorType(StrEnum):
    CUSTOMER = "CUSTOMER"
    AI_AGENT = "AI_AGENT"
    SYSTEM = "SYSTEM"
    HUMAN_AGENT = "HUMAN_AGENT"


class ConversationStatus(StrEnum):
    OPEN = "OPEN"
    ENDED = "ENDED"


class TicketStatus(StrEnum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class EscalationStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class EscalationReason(StrEnum):
    CUSTOMER_REQUESTED_HUMAN = "CUSTOMER_REQUESTED_HUMAN"
    ACTION_REQUIRES_HUMAN = "ACTION_REQUIRES_HUMAN"
    BUSINESS_SYSTEM_UNAVAILABLE = "BUSINESS_SYSTEM_UNAVAILABLE"
    UNSUPPORTED_REQUEST = "UNSUPPORTED_REQUEST"
    AMBIGUOUS_ACCOUNT = "AMBIGUOUS_ACCOUNT"
    AGENT_UNCERTAIN = "AGENT_UNCERTAIN"
    POLICY_CONFLICT = "POLICY_CONFLICT"


class CustomerBinding(BaseModel):
    model_config = ConfigDict(frozen=True)
    customer_id: str
    external_customer_id: str
    display_name: str
    created_at: datetime = Field(default_factory=now)


class Conversation(BaseModel):
    model_config = ConfigDict(frozen=True)
    conversation_id: str
    ticket_id: str
    customer_id: str
    status: ConversationStatus = ConversationStatus.OPEN
    started_at: datetime = Field(default_factory=now)
    ended_at: datetime | None = None


class Message(BaseModel):
    model_config = ConfigDict(frozen=True)
    message_id: str
    conversation_id: str
    actor_type: ActorType
    actor_id: str
    content: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=now)


class Ticket(BaseModel):
    model_config = ConfigDict(frozen=True)
    ticket_id: str
    customer_id: str
    conversation_id: str
    status: TicketStatus = TicketStatus.OPEN
    reason: str
    priority: str
    resolution_code: str | None = None
    created_at: datetime = Field(default_factory=now)
    resolved_at: datetime | None = None


class Escalation(BaseModel):
    model_config = ConfigDict(frozen=True)
    escalation_id: str
    ticket_id: str
    reason: EscalationReason
    summary: str = Field(min_length=1)
    status: EscalationStatus = EscalationStatus.OPEN
    created_at: datetime = Field(default_factory=now)
    resolved_at: datetime | None = None


class Outcome(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome_id: str
    ticket_id: str
    outcome_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=now)


class CSAT(BaseModel):
    model_config = ConfigDict(frozen=True)
    csat_id: str
    ticket_id: str
    score: int = Field(ge=1, le=5)
    comment: str | None = None
    submitted_at: datetime = Field(default_factory=now)

