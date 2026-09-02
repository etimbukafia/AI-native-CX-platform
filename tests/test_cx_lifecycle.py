import sqlite3

import pytest

from cx_platform.domain.models import (
    ActorType,
    CSAT,
    CustomerBinding,
    Conversation,
    Escalation,
    EscalationReason,
    Message,
    Outcome,
    Ticket,
    TicketStatus,
)
from cx_platform.persistence import CXDatabase, CXRepositories
from cx_platform.services import (
    ConversationService,
    InvalidCSATSubmission,
    InvalidTicketTransition,
)


def make_service(tmp_path) -> ConversationService:
    repositories = CXRepositories(CXDatabase(str(tmp_path / "cx.db")))
    repositories.save_binding(
        CustomerBinding(
            customer_id="cx_cus_01",
            external_customer_id="cus_001",
            display_name="Ada Okafor",
        )
    )
    return ConversationService(repositories)


def test_conversation_lifecycle_persists_messages_resolution_and_csat(tmp_path) -> None:
    service = make_service(tmp_path)
    conversation, ticket = service.start(
        customer_id="cx_cus_01",
        reason="Delayed delivery",
    )
    message = service.append_message(
        conversation.conversation_id,
        actor_type=ActorType.CUSTOMER,
        actor_id="cx_cus_01",
        content="Where is my order?",
    )
    service.transition_ticket(ticket.ticket_id, TicketStatus.IN_PROGRESS)
    resolved = service.resolve(
        ticket.ticket_id,
        resolution_code="DELIVERY_UPDATE",
        outcome_type="delivery_update",
    )
    csat = service.submit_csat(ticket.ticket_id, score=5, comment="Clear answer")

    assert message.content == "Where is my order?"
    assert resolved.status is TicketStatus.RESOLVED
    assert service.repositories.outcomes(ticket.ticket_id)[0].outcome_type == "delivery_update"
    assert csat.score == 5


@pytest.mark.parametrize(
    "transitions",
    [
        (),
        (TicketStatus.IN_PROGRESS,),
        (TicketStatus.IN_PROGRESS, TicketStatus.WAITING_APPROVAL),
        (TicketStatus.ESCALATED,),
    ],
)
def test_csat_rejects_a_ticket_without_resolution(tmp_path, transitions) -> None:
    service = make_service(tmp_path)
    _, ticket = service.start(customer_id="cx_cus_01", reason="Support request")
    for status in transitions:
        service.transition_ticket(ticket.ticket_id, status)

    with pytest.raises(InvalidCSATSubmission, match="resolved"):
        service.submit_csat(ticket.ticket_id, score=4)


def test_csat_accepts_closed_ticket_after_resolution(tmp_path) -> None:
    service = make_service(tmp_path)
    _, ticket = service.start(customer_id="cx_cus_01", reason="Support request")
    service.resolve(
        ticket.ticket_id,
        resolution_code="ANSWERED",
        outcome_type="answer_provided",
    )
    service.transition_ticket(ticket.ticket_id, TicketStatus.CLOSED)

    assert service.submit_csat(ticket.ticket_id, score=4).score == 4


def test_escalation_moves_ticket_to_escalated_and_rejects_invalid_transition(tmp_path) -> None:
    service = make_service(tmp_path)
    _, ticket = service.start(customer_id="cx_cus_01", reason="Need a human")
    escalation = service.escalate(
        ticket.ticket_id,
        reason=EscalationReason.CUSTOMER_REQUESTED_HUMAN,
        summary="Customer asked for a person",
    )

    assert escalation.ticket_id == ticket.ticket_id
    assert service.repositories.ticket(ticket.ticket_id).status is TicketStatus.ESCALATED
    with pytest.raises(InvalidTicketTransition):
        service.transition_ticket(ticket.ticket_id, TicketStatus.CLOSED)


def test_persistence_rejects_orphan_cx_records(tmp_path) -> None:
    repositories = CXRepositories(CXDatabase(str(tmp_path / "cx.db")))

    with pytest.raises(sqlite3.IntegrityError):
        repositories.save_ticket(
            Ticket(
                ticket_id="ticket_orphan",
                customer_id="cx_missing",
                conversation_id="conv_orphan",
                reason="Support request",
                priority="NORMAL",
            )
        )
    repositories.save_binding(
        CustomerBinding(
            customer_id="cx_cus_01",
            external_customer_id="cus_001",
            display_name="Ada Okafor",
        )
    )
    with pytest.raises(sqlite3.IntegrityError):
        repositories.save_conversation(
            Conversation(
                conversation_id="conv_orphan",
                ticket_id="ticket_missing",
                customer_id="cx_cus_01",
            )
        )
    with pytest.raises(sqlite3.IntegrityError):
        repositories.save_message(
            Message(
                message_id="msg_orphan",
                conversation_id="conv_missing",
                actor_type=ActorType.CUSTOMER,
                actor_id="cx_cus_01",
                content="Help",
            )
        )
    with pytest.raises(sqlite3.IntegrityError):
        repositories.save_escalation(
            Escalation(
                escalation_id="esc_orphan",
                ticket_id="ticket_missing",
                reason=EscalationReason.AGENT_UNCERTAIN,
                summary="Need help",
            )
        )
    with pytest.raises(sqlite3.IntegrityError):
        repositories.save_outcome(
            Outcome(
                outcome_id="outcome_orphan",
                ticket_id="ticket_missing",
                outcome_type="unavailable",
            )
        )
    with pytest.raises(sqlite3.IntegrityError):
        repositories.save_csat(
            CSAT(csat_id="csat_orphan", ticket_id="ticket_missing", score=1)
        )
