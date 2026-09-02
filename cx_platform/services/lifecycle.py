from __future__ import annotations

from uuid import uuid4

from cx_platform.domain.models import ActorType, CSAT, Conversation, ConversationStatus, Escalation, EscalationReason, Outcome, Ticket, TicketStatus, now
from cx_platform.persistence.sqlite import CXRepositories


class InvalidTicketTransition(ValueError): pass


_TRANSITIONS = {
    TicketStatus.OPEN: {TicketStatus.IN_PROGRESS, TicketStatus.ESCALATED, TicketStatus.RESOLVED},
    TicketStatus.IN_PROGRESS: {TicketStatus.WAITING_APPROVAL, TicketStatus.ESCALATED, TicketStatus.RESOLVED},
    TicketStatus.WAITING_APPROVAL: {TicketStatus.IN_PROGRESS, TicketStatus.ESCALATED, TicketStatus.RESOLVED},
    TicketStatus.ESCALATED: {TicketStatus.RESOLVED}, TicketStatus.RESOLVED: {TicketStatus.CLOSED}, TicketStatus.CLOSED: set(),
}


class ConversationService:
    def __init__(self, repositories: CXRepositories) -> None: self.repositories = repositories

    def start(self, *, customer_id: str, reason: str, priority: str = "NORMAL") -> tuple[Conversation, Ticket]:
        conversation_id, ticket_id = self._id("conv"), self._id("ticket")
        ticket = self.repositories.save_ticket(Ticket(ticket_id=ticket_id, customer_id=customer_id, conversation_id=conversation_id, reason=reason, priority=priority))
        return self.repositories.save_conversation(Conversation(conversation_id=conversation_id, ticket_id=ticket_id, customer_id=customer_id)), ticket

    def append_message(self, conversation_id: str, *, actor_type: ActorType, actor_id: str, content: str):
        if self.repositories.conversation(conversation_id) is None: raise KeyError(conversation_id)
        from cx_platform.domain.models import Message
        return self.repositories.save_message(Message(message_id=self._id("msg"), conversation_id=conversation_id, actor_type=actor_type, actor_id=actor_id, content=content))

    def end_conversation(self, conversation_id: str) -> Conversation:
        conversation = self.repositories.conversation(conversation_id)
        if conversation is None: raise KeyError(conversation_id)
        if conversation.status is ConversationStatus.ENDED: return conversation
        return self.repositories.save_conversation(conversation.model_copy(update={"status": ConversationStatus.ENDED, "ended_at": now()}))

    def transition_ticket(self, ticket_id: str, status: TicketStatus, *, resolution_code: str | None = None) -> Ticket:
        ticket = self.repositories.ticket(ticket_id)
        if ticket is None: raise KeyError(ticket_id)
        if status not in _TRANSITIONS[ticket.status]: raise InvalidTicketTransition(f"Cannot transition ticket from {ticket.status} to {status}")
        resolved_at = now() if status is TicketStatus.RESOLVED else ticket.resolved_at
        return self.repositories.save_ticket(ticket.model_copy(update={"status": status, "resolution_code": resolution_code or ticket.resolution_code, "resolved_at": resolved_at}))

    def resolve(self, ticket_id: str, *, resolution_code: str, outcome_type: str, metadata: dict[str, object] | None = None) -> Ticket:
        ticket = self.transition_ticket(ticket_id, TicketStatus.RESOLVED, resolution_code=resolution_code)
        self.repositories.save_outcome(Outcome(outcome_id=self._id("outcome"), ticket_id=ticket_id, outcome_type=outcome_type, metadata=metadata or {}))
        return ticket

    def escalate(self, ticket_id: str, *, reason: EscalationReason, summary: str) -> Escalation:
        self.transition_ticket(ticket_id, TicketStatus.ESCALATED)
        return self.repositories.save_escalation(Escalation(escalation_id=self._id("esc"), ticket_id=ticket_id, reason=reason, summary=summary))

    def submit_csat(self, ticket_id: str, *, score: int, comment: str | None = None) -> CSAT:
        if self.repositories.ticket(ticket_id) is None: raise KeyError(ticket_id)
        return self.repositories.save_csat(CSAT(csat_id=self._id("csat"), ticket_id=ticket_id, score=score, comment=comment))

    @staticmethod
    def _id(prefix: str) -> str: return f"{prefix}_{uuid4().hex}"
