from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue


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
    execution_id: str | None = Field(default=None, min_length=1)
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
    conversation_id: str | None = Field(default=None, min_length=1)
    execution_id: str | None = Field(default=None, min_length=1)
    customer_goal: str | None = Field(default=None, min_length=1)
    active_order_id: str | None = Field(default=None, min_length=1)
    active_item_id: str | None = Field(default=None, min_length=1)
    actions_attempted: list[str] = Field(default_factory=list)
    tool_result_refs: list[str] = Field(default_factory=list)
    reason: EscalationReason
    summary: str = Field(min_length=1)
    status: EscalationStatus = EscalationStatus.OPEN
    created_at: datetime = Field(default_factory=now)
    resolved_at: datetime | None = None


class ApprovalRecordStatus(StrEnum):
    """CX view of one Harness approval request."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    EXPIRED = "EXPIRED"


class ApprovalRecord(BaseModel):
    """Minimal CX-owned reference to a governed Harness approval."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    ticket_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    harness_request_id: str = Field(min_length=1)
    action_digest: str = Field(min_length=1)
    tool_id: str = Field(min_length=1)
    action_summary: str = Field(min_length=1, max_length=500)
    status: ApprovalRecordStatus = ApprovalRecordStatus.PENDING
    harness_approval_id: str | None = Field(default=None, min_length=1)
    decided_by: str | None = Field(default=None, min_length=1)
    decision_reason: str | None = Field(default=None, min_length=1)
    requested_at: datetime = Field(default_factory=now)
    decided_at: datetime | None = None


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


class CXEventType(StrEnum):
    """Operational event types owned by the CX platform."""

    CONVERSATION_STARTED = "conversation.started"
    CONVERSATION_ENDED = "conversation.ended"
    MESSAGE_CUSTOMER_RECEIVED = "message.customer_received"
    MESSAGE_AGENT_SENT = "message.agent_sent"
    TICKET_CREATED = "ticket.created"
    TICKET_STATUS_CHANGED = "ticket.status_changed"
    TICKET_RESOLVED = "ticket.resolved"
    TICKET_ESCALATED = "ticket.escalated"
    AGENT_EXECUTION_STARTED = "agent.execution_started"
    AGENT_EXECUTION_COMPLETED = "agent.execution_completed"
    AGENT_EXECUTION_FAILED = "agent.execution_failed"
    AGENT_TOOL_CALLED = "agent.tool_called"
    AGENT_TOOL_SUCCEEDED = "agent.tool_succeeded"
    AGENT_TOOL_FAILED = "agent.tool_failed"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_APPROVED = "approval.approved"
    APPROVAL_REJECTED = "approval.rejected"
    OUTCOME_RECORDED = "outcome.recorded"
    CSAT_RECEIVED = "csat.received"


class CXEvent(BaseModel):
    """One append-only operational fact owned by the CX platform."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1)
    event_type: CXEventType
    occurred_at: datetime = Field(default_factory=now)
    customer_id: str | None = Field(default=None, min_length=1)
    ticket_id: str | None = Field(default=None, min_length=1)
    conversation_id: str | None = Field(default=None, min_length=1)
    message_id: str | None = Field(default=None, min_length=1)
    execution_id: str | None = Field(default=None, min_length=1)
    actor_type: ActorType = ActorType.SYSTEM
    actor_id: str = Field(default="cx-platform", min_length=1)
    data: dict[str, JsonValue] = Field(default_factory=dict)


class ExecutionReference(BaseModel):
    """Small CX link to one Harness execution and its exported trace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_id: str = Field(min_length=1)
    ticket_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    agent_version: str = Field(min_length=1)
    trace_reference: str | None = Field(default=None, min_length=1)
    started_at: datetime = Field(default_factory=now)
    completed_at: datetime | None = None
    outcome_status: str | None = Field(default=None, min_length=1)


class MemoryOperation(StrEnum):
    READ = "read"
    WRITE = "write"
    CONTEXT = "context"
    OUTCOME = "outcome"
    FAILURE = "failure"


class MemoryReference(BaseModel):
    """Small CX-owned reference to an external memory operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reference_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    customer_id: str | None = Field(default=None, min_length=1)
    conversation_id: str | None = Field(default=None, min_length=1)
    memory_provider: str = Field(min_length=1)
    memory_entry_id: str = Field(min_length=1)
    memory_key: str = Field(min_length=1)
    memory_version: int | None = Field(default=None, ge=1)
    memory_scope: str = Field(min_length=1)
    operation: MemoryOperation
    outcome_id: str | None = Field(default=None, min_length=1)
    csat_id: str | None = Field(default=None, min_length=1)
    occurred_at: datetime = Field(default_factory=now)


class CustomerHistory(BaseModel):
    """Authoritative service history for one CX customer."""

    model_config = ConfigDict(frozen=True)

    customer_id: str = Field(min_length=1)
    conversations: list[Conversation] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)
    tickets: list[Ticket] = Field(default_factory=list)
    escalations: list[Escalation] = Field(default_factory=list)
    outcomes: list[Outcome] = Field(default_factory=list)
    csat: list[CSAT] = Field(default_factory=list)
