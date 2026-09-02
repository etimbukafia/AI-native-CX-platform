from cx_platform.domain.models import ActorType, EscalationReason, TicketStatus
from cx_platform.persistence import CXDatabase, CXRepositories
from cx_platform.services import ConversationService, InvalidTicketTransition
import pytest


def test_conversation_lifecycle_persists_messages_resolution_and_csat(tmp_path) -> None:
    repositories = CXRepositories(CXDatabase(str(tmp_path / "cx.db")))
    service = ConversationService(repositories)
    conversation, ticket = service.start(customer_id="cx_cus_01", reason="Delayed delivery")
    message = service.append_message(conversation.conversation_id, actor_type=ActorType.CUSTOMER, actor_id="cx_cus_01", content="Where is my order?")
    service.transition_ticket(ticket.ticket_id, TicketStatus.IN_PROGRESS)
    resolved = service.resolve(ticket.ticket_id, resolution_code="DELIVERY_UPDATE", outcome_type="delivery_update")
    csat = service.submit_csat(ticket.ticket_id, score=5, comment="Clear answer")
    assert message.content == "Where is my order?"
    assert resolved.status is TicketStatus.RESOLVED
    assert repositories.outcomes(ticket.ticket_id)[0].outcome_type == "delivery_update"
    assert csat.score == 5


def test_escalation_moves_ticket_to_escalated_and_rejects_invalid_transition(tmp_path) -> None:
    service = ConversationService(CXRepositories(CXDatabase(str(tmp_path / "cx.db"))))
    _, ticket = service.start(customer_id="cx_cus_01", reason="Need a human")
    escalation = service.escalate(ticket.ticket_id, reason=EscalationReason.CUSTOMER_REQUESTED_HUMAN, summary="Customer asked for a person")
    assert escalation.ticket_id == ticket.ticket_id
    assert service.repositories.ticket(ticket.ticket_id).status is TicketStatus.ESCALATED
    with pytest.raises(InvalidTicketTransition): service.transition_ticket(ticket.ticket_id, TicketStatus.CLOSED)
