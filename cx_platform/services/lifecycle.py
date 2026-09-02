from __future__ import annotations

from uuid import uuid4

from cx_platform.domain.models import (
    ActorType,
    CSAT,
    Conversation,
    ConversationStatus,
    Escalation,
    EscalationReason,
    Message,
    Outcome,
    Ticket,
    TicketStatus,
    now,
)
from cx_platform.persistence.sqlite import CXRepositories


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
    def __init__(self, repositories: CXRepositories) -> None:
        self.repositories = repositories

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
        return conversation, ticket

    def append_message(
        self,
        conversation_id: str,
        *,
        actor_type: ActorType,
        actor_id: str,
        content: str,
    ) -> Message:
        if self.repositories.conversation(conversation_id) is None:
            raise KeyError(conversation_id)
        message = Message(
            message_id=self._id("msg"),
            conversation_id=conversation_id,
            actor_type=actor_type,
            actor_id=actor_id,
            content=content,
        )
        return self.repositories.save_message(message)

    def end_conversation(self, conversation_id: str) -> Conversation:
        conversation = self.repositories.conversation(conversation_id)
        if conversation is None:
            raise KeyError(conversation_id)
        if conversation.status is ConversationStatus.ENDED:
            return conversation
        return self.repositories.save_conversation(
            conversation.model_copy(
                update={
                    "status": ConversationStatus.ENDED,
                    "ended_at": now(),
                }
            )
        )

    def transition_ticket(
        self,
        ticket_id: str,
        status: TicketStatus,
        *,
        resolution_code: str | None = None,
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
        return self.repositories.save_ticket(updated_ticket)

    def resolve(
        self,
        ticket_id: str,
        *,
        resolution_code: str,
        outcome_type: str,
        metadata: dict[str, object] | None = None,
    ) -> Ticket:
        ticket = self.transition_ticket(
            ticket_id,
            TicketStatus.RESOLVED,
            resolution_code=resolution_code,
        )
        outcome = Outcome(
            outcome_id=self._id("outcome"),
            ticket_id=ticket_id,
            outcome_type=outcome_type,
            metadata=metadata or {},
        )
        self.repositories.save_outcome(outcome)
        return ticket

    def escalate(
        self,
        ticket_id: str,
        *,
        reason: EscalationReason,
        summary: str,
    ) -> Escalation:
        self.transition_ticket(ticket_id, TicketStatus.ESCALATED)
        escalation = Escalation(
            escalation_id=self._id("esc"),
            ticket_id=ticket_id,
            reason=reason,
            summary=summary,
        )
        return self.repositories.save_escalation(escalation)

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
        return self.repositories.save_csat(csat)

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex}"
