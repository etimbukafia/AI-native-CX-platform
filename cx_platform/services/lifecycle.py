from __future__ import annotations

from uuid import uuid4

from cx_platform.domain.models import (
    CSAT,
    ActorType,
    Conversation,
    ConversationStatus,
    CXEventType,
    Escalation,
    EscalationReason,
    Message,
    Outcome,
    Ticket,
    TicketStatus,
    now,
)
from cx_platform.persistence.sqlite import CXRepositories
from cx_platform.services.events import CXEventService


class InvalidTicketTransition(ValueError):
    pass


class InvalidCSATSubmission(ValueError):
    pass


_TRANSITIONS = {
    TicketStatus.OPEN: {
        TicketStatus.IN_PROGRESS,
        TicketStatus.ESCALATED,
        TicketStatus.RESOLVED,
    },
    TicketStatus.IN_PROGRESS: {
        TicketStatus.WAITING_APPROVAL,
        TicketStatus.ESCALATED,
        TicketStatus.RESOLVED,
    },
    TicketStatus.WAITING_APPROVAL: {
        TicketStatus.IN_PROGRESS,
        TicketStatus.ESCALATED,
        TicketStatus.RESOLVED,
    },
    TicketStatus.ESCALATED: {TicketStatus.RESOLVED},
    TicketStatus.RESOLVED: {TicketStatus.CLOSED},
    TicketStatus.CLOSED: set(),
}


class ConversationService:
    def __init__(
        self,
        repositories: CXRepositories,
        event_service: CXEventService | None = None,
    ) -> None:
        self.repositories = repositories
        self.event_service = event_service or CXEventService(repositories)

    def start(
        self,
        *,
        customer_id: str,
        reason: str,
        priority: str = "NORMAL",
    ) -> tuple[Conversation, Ticket]:
        conversation_id = self._id("conv")
        ticket_id = self._id("ticket")
        ticket = Ticket(
            ticket_id=ticket_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            reason=reason,
            priority=priority,
        )
        self.repositories.save_ticket(ticket)
        conversation = Conversation(
            conversation_id=conversation_id,
            ticket_id=ticket_id,
            customer_id=customer_id,
        )
        self.repositories.save_conversation(conversation)
        self.event_service.emit(
            CXEventType.TICKET_CREATED,
            customer_id=customer_id,
            ticket_id=ticket.ticket_id,
            conversation_id=conversation.conversation_id,
            data={"priority": priority},
        )
        self.event_service.emit(
            CXEventType.CONVERSATION_STARTED,
            customer_id=customer_id,
            ticket_id=ticket.ticket_id,
            conversation_id=conversation.conversation_id,
        )
        return conversation, ticket

    def append_message(
        self,
        conversation_id: str,
        *,
        actor_type: ActorType,
        actor_id: str,
        content: str,
        execution_id: str | None = None,
    ) -> Message:
        if self.repositories.conversation(conversation_id) is None:
            raise KeyError(conversation_id)
        message = Message(
            message_id=self._id("msg"),
            conversation_id=conversation_id,
            actor_type=actor_type,
            actor_id=actor_id,
            content=content,
            execution_id=execution_id,
        )
        saved = self.repositories.save_message(message)
        event_type = {
            ActorType.CUSTOMER: CXEventType.MESSAGE_CUSTOMER_RECEIVED,
            ActorType.AI_AGENT: CXEventType.MESSAGE_AGENT_SENT,
        }.get(actor_type)
        if event_type is not None:
            conversation = self.repositories.conversation(conversation_id)
            self.event_service.emit(
                event_type,
                customer_id=conversation.customer_id if conversation else None,
                ticket_id=conversation.ticket_id if conversation else None,
                conversation_id=conversation_id,
                message_id=saved.message_id,
                execution_id=execution_id,
                actor_type=actor_type,
                actor_id=actor_id,
                data={"content_length": len(content)},
            )
        return saved

    def end_conversation(self, conversation_id: str) -> Conversation:
        conversation = self.repositories.conversation(conversation_id)
        if conversation is None:
            raise KeyError(conversation_id)
        if conversation.status is ConversationStatus.ENDED:
            return conversation
        saved = self.repositories.save_conversation(
            conversation.model_copy(
                update={
                    "status": ConversationStatus.ENDED,
                    "ended_at": now(),
                }
            )
        )
        self.event_service.emit(
            CXEventType.CONVERSATION_ENDED,
            customer_id=saved.customer_id,
            ticket_id=saved.ticket_id,
            conversation_id=saved.conversation_id,
        )
        return saved

    def transition_ticket(
        self,
        ticket_id: str,
        status: TicketStatus,
        *,
        resolution_code: str | None = None,
        execution_id: str | None = None,
    ) -> Ticket:
        ticket = self.repositories.ticket(ticket_id)
        if ticket is None:
            raise KeyError(ticket_id)
        if status not in _TRANSITIONS[ticket.status]:
            raise InvalidTicketTransition(
                f"Cannot transition ticket from {ticket.status} to {status}"
            )
        resolved_at = now() if status is TicketStatus.RESOLVED else ticket.resolved_at
        updated_ticket = ticket.model_copy(
            update={
                "status": status,
                "resolution_code": resolution_code or ticket.resolution_code,
                "resolved_at": resolved_at,
            }
        )
        saved = self.repositories.save_ticket(updated_ticket)
        self.event_service.emit(
            CXEventType.TICKET_STATUS_CHANGED,
            customer_id=saved.customer_id,
            ticket_id=saved.ticket_id,
            conversation_id=saved.conversation_id,
            execution_id=execution_id,
            data={
                "from_status": ticket.status.value,
                "to_status": saved.status.value,
                **(
                    {"resolution_code": saved.resolution_code}
                    if saved.resolution_code is not None
                    else {}
                ),
            },
        )
        if saved.status is TicketStatus.RESOLVED:
            self.event_service.emit(
                CXEventType.TICKET_RESOLVED,
                customer_id=saved.customer_id,
                ticket_id=saved.ticket_id,
                conversation_id=saved.conversation_id,
                execution_id=execution_id,
                data={"resolution_code": saved.resolution_code or ""},
            )
        return saved

    def resolve(
        self,
        ticket_id: str,
        *,
        resolution_code: str,
        outcome_type: str,
        metadata: dict[str, object] | None = None,
        execution_id: str | None = None,
    ) -> Ticket:
        outcome_metadata = metadata or {}
        linked_execution_id = execution_id or _metadata_string(
            outcome_metadata,
            "execution_id",
        )
        ticket = self.transition_ticket(
            ticket_id,
            TicketStatus.RESOLVED,
            resolution_code=resolution_code,
            execution_id=linked_execution_id,
        )
        outcome = Outcome(
            outcome_id=self._id("outcome"),
            ticket_id=ticket_id,
            outcome_type=outcome_type,
            metadata=outcome_metadata,
        )
        saved_outcome = self.repositories.save_outcome(outcome)
        self.event_service.emit(
            CXEventType.OUTCOME_RECORDED,
            customer_id=ticket.customer_id,
            ticket_id=ticket.ticket_id,
            conversation_id=ticket.conversation_id,
            execution_id=linked_execution_id,
            data={
                "outcome_id": saved_outcome.outcome_id,
                "outcome_type": saved_outcome.outcome_type,
            },
        )
        return ticket

    def escalate(
        self,
        ticket_id: str,
        *,
        reason: EscalationReason,
        summary: str,
        conversation_id: str | None = None,
        execution_id: str | None = None,
        customer_goal: str | None = None,
        active_order_id: str | None = None,
        active_item_id: str | None = None,
        actions_attempted: list[str] | None = None,
        tool_result_refs: list[str] | None = None,
    ) -> Escalation:
        ticket = self.transition_ticket(
            ticket_id,
            TicketStatus.ESCALATED,
            execution_id=execution_id,
        )
        linked_conversation_id = conversation_id or ticket.conversation_id
        escalation = Escalation(
            escalation_id=self._id("esc"),
            ticket_id=ticket_id,
            conversation_id=linked_conversation_id,
            execution_id=execution_id,
            customer_goal=customer_goal,
            active_order_id=active_order_id,
            active_item_id=active_item_id,
            actions_attempted=actions_attempted or [],
            tool_result_refs=tool_result_refs or [],
            reason=reason,
            summary=summary,
        )
        saved = self.repositories.save_escalation(escalation)
        self.event_service.emit(
            CXEventType.TICKET_ESCALATED,
            customer_id=ticket.customer_id,
            ticket_id=ticket.ticket_id,
            conversation_id=linked_conversation_id,
            execution_id=execution_id,
            data={
                "escalation_id": saved.escalation_id,
                "reason": saved.reason.value,
            },
        )
        return saved

    def submit_csat(
        self,
        ticket_id: str,
        *,
        score: int,
        comment: str | None = None,
    ) -> CSAT:
        ticket = self.repositories.ticket(ticket_id)
        if ticket is None:
            raise KeyError(ticket_id)
        if ticket.status not in {TicketStatus.RESOLVED, TicketStatus.CLOSED}:
            raise InvalidCSATSubmission("CSAT requires a resolved ticket")
        csat = CSAT(
            csat_id=self._id("csat"),
            ticket_id=ticket_id,
            score=score,
            comment=comment,
        )
        saved = self.repositories.save_csat(csat)
        outcomes = self.repositories.outcomes(ticket_id)
        latest_outcome = outcomes[-1] if outcomes else None
        linked_execution_id = (
            _metadata_string(latest_outcome.metadata, "execution_id")
            if latest_outcome is not None
            else None
        )
        self.event_service.emit(
            CXEventType.CSAT_RECEIVED,
            customer_id=ticket.customer_id,
            ticket_id=ticket.ticket_id,
            conversation_id=ticket.conversation_id,
            execution_id=linked_execution_id,
            actor_type=ActorType.CUSTOMER,
            actor_id=ticket.customer_id,
            data={
                "csat_id": saved.csat_id,
                "score": saved.score,
                "comment_present": comment is not None,
                **(
                    {"outcome_id": latest_outcome.outcome_id}
                    if latest_outcome is not None
                    else {}
                ),
            },
        )
        return saved

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex}"


def _metadata_string(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) and value else None
