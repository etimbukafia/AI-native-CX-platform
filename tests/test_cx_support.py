import sqlite3

import pytest
from enterprise_agent_harness import OutcomeStatus, PrincipalContext
from fastapi.testclient import TestClient

from cx_platform.agent import SUPPORT_AGENT_ID, SUPPORT_AGENT_VERSION
from cx_platform.api import create_app as create_cx_app
from cx_platform.domain.models import (
    ApprovalRecord,
    CustomerBinding,
    EscalationReason,
    TicketStatus,
)
from cx_platform.integrations.mock_business import MockBusinessClient
from cx_platform.persistence import CXDatabase, CXRepositories
from cx_platform.services import ConversationService, build_support_service
from src.mock_business.api import create_app as create_business_app


def make_support_service(
    *,
    scenario: str = "normal_delivery",
    tool_id: str = "get_order",
    arguments=None,
    memory=None,
):
    business_api = TestClient(create_business_app(":memory:"))
    business_api.post(f"/scenarios/{scenario}/activate")
    business = MockBusinessClient("http://testserver", client=business_api)
    repositories = CXRepositories(CXDatabase(":memory:"))
    repositories.save_binding(
        CustomerBinding(
            customer_id="cx_cus_01",
            external_customer_id="cus_001",
            display_name="Ada Okafor",
        )
    )
    conversations = ConversationService(repositories)
    conversation, ticket = conversations.start(
        customer_id="cx_cus_01",
        reason="Customer support request",
    )
    selected_arguments = arguments
    if selected_arguments is None and tool_id == "escalate_to_human":
        selected_arguments = {
            "ticket_id": ticket.ticket_id,
            "reason": "CUSTOMER_REQUESTED_HUMAN",
            "summary": "Customer asked for a person.",
        }
    service = build_support_service(
        business,
        conversations,
        memory=memory,
        deterministic_tool_id=tool_id,
        deterministic_arguments=selected_arguments or {"order_id": "ord_001"},
    )
    return service, business_api, conversation, ticket, repositories


def test_support_agent_links_customer_and_agent_messages_to_one_execution() -> None:
    service, _, conversation, ticket, repositories = make_support_service()

    result = service.handle_message(conversation.conversation_id, "Where is my order?")

    assert service.agent.manifest.manifest_id == "customer-support-agent@1.0.0"
    assert result.status is OutcomeStatus.COMPLETED
    assert result.ticket_status is TicketStatus.RESOLVED
    messages = repositories.messages(conversation.conversation_id)
    assert [message.execution_id for message in messages] == [
        result.execution_id,
        result.execution_id,
    ]
    workflow = service.workflow_state.load(
        PrincipalContext(
            principal_id="cx_cus_01",
            tenant_id="cx-platform",
            session_id=conversation.conversation_id,
        ),
        customer_id="cx_cus_01",
        conversation_id=conversation.conversation_id,
    )
    assert workflow.agent_id == SUPPORT_AGENT_ID
    assert workflow.agent_version == SUPPORT_AGENT_VERSION
    assert repositories.ticket(ticket.ticket_id).status is TicketStatus.RESOLVED


def test_refund_waits_for_harness_approval_and_business_sees_one_decision() -> None:
    service, business_api, conversation, ticket, repositories = make_support_service(
        scenario="refund_requires_approval",
        tool_id="request_refund",
        arguments={
            "order_id": "ord_001",
            "payment_id": "pay_001",
            "amount": "197.00",
            "reason": "Damaged item",
        },
    )

    waiting = service.handle_message(
        conversation.conversation_id, "Please refund this order."
    )
    assert waiting.status is OutcomeStatus.ESCALATED
    assert waiting.ticket_status is TicketStatus.WAITING_APPROVAL
    assert repositories.ticket(ticket.ticket_id).status is TicketStatus.WAITING_APPROVAL
    assert service.approval_records()[0].status.value == "PENDING"
    assert not any(
        event["event_type"].startswith("refund.")
        for event in business_api.get("/events").json()
    )

    cx_api = TestClient(create_cx_app(service))
    approval_response = cx_api.post(
        f"/approvals/{waiting.execution_id}/approve",
        json={"decided_by": "operator-01"},
    )

    assert approval_response.status_code == 200
    assert approval_response.json()["status"] == OutcomeStatus.COMPLETED.value
    assert approval_response.json()["ticket_status"] == TicketStatus.RESOLVED.value
    assert service.approval_records()[0].status.value == "APPROVED"
    event_types = [event["event_type"] for event in business_api.get("/events").json()]
    assert "refund.approved" in event_types
    assert "refund.approval_required" not in event_types


def test_rejected_refund_does_not_call_business_action() -> None:
    service, business_api, conversation, ticket, repositories = make_support_service(
        scenario="refund_requires_approval",
        tool_id="request_refund",
        arguments={
            "order_id": "ord_001",
            "payment_id": "pay_001",
            "amount": "197.00",
            "reason": "Damaged item",
        },
    )

    waiting = service.handle_message(
        conversation.conversation_id, "Please refund this order."
    )
    rejected = service.reject(waiting.execution_id, decided_by="operator-01")

    assert rejected.status is OutcomeStatus.REFUSED
    assert rejected.ticket_status is TicketStatus.ESCALATED
    assert repositories.ticket(ticket.ticket_id).status is TicketStatus.ESCALATED
    assert service.approval_records()[0].status.value == "REJECTED"
    event_types = [event["event_type"] for event in business_api.get("/events").json()]
    assert "refund.approved" not in event_types
    assert "refund.approval_required" not in event_types


def test_dependency_failure_is_escalated_without_inventing_business_state() -> None:
    service, _, conversation, ticket, repositories = make_support_service(
        scenario="shipping_service_outage",
        tool_id="get_shipment",
        arguments={"order_id": "ord_001"},
    )

    result = service.handle_message(
        conversation.conversation_id, "Where is the shipment?"
    )

    assert result.status is OutcomeStatus.FAILED
    assert result.ticket_status is TicketStatus.ESCALATED
    escalation = repositories.escalations(ticket.ticket_id)[0]
    assert escalation.reason is EscalationReason.BUSINESS_SYSTEM_UNAVAILABLE
    assert "could not verify" in result.response


def test_escalation_contains_execution_and_action_context() -> None:
    service, _, conversation, ticket, repositories = make_support_service(
        tool_id="escalate_to_human",
    )

    result = service.handle_message(conversation.conversation_id, "I need a person.")
    escalation = repositories.escalations(ticket.ticket_id)[0]

    assert result.ticket_status is TicketStatus.ESCALATED
    assert escalation.conversation_id == conversation.conversation_id
    assert escalation.execution_id == result.execution_id
    assert escalation.customer_goal == ticket.reason
    assert escalation.actions_attempted == ["escalate_to_human"]


def test_unauthorized_write_is_refused_before_business_execution() -> None:
    service, business_api, conversation, ticket, repositories = make_support_service(
        tool_id="delete_customer",
        arguments={"customer_id": "cus_001"},
    )

    result = service.handle_message(conversation.conversation_id, "Delete my account.")

    assert result.status is OutcomeStatus.FAILED
    assert result.ticket_status is TicketStatus.ESCALATED
    escalation = repositories.escalations(ticket.ticket_id)[0]
    assert escalation.reason is EscalationReason.BUSINESS_SYSTEM_UNAVAILABLE
    assert not any(
        event["event_type"].startswith("customer.delete")
        for event in business_api.get("/events").json()
    )


class UnavailableMemory:
    provider = "senselab"

    def search_relevant(self, **_: object):
        raise RuntimeError("SenseLab is unavailable")


def test_senselab_failure_keeps_deterministic_support_available() -> None:
    service, _, conversation, ticket, _ = make_support_service(
        memory=UnavailableMemory(),
    )

    result = service.handle_message(conversation.conversation_id, "Where is my order?")

    assert result.status is OutcomeStatus.COMPLETED
    assert result.ticket_status is TicketStatus.RESOLVED
    assert ticket.ticket_id == result.ticket_id


def test_orphan_approval_reference_is_rejected_by_cx_foreign_keys() -> None:
    repositories = CXRepositories(CXDatabase(":memory:"))

    with pytest.raises(sqlite3.IntegrityError):
        repositories.save_approval(
            ApprovalRecord(
                approval_id="approval_orphan",
                customer_id="cx_missing",
                ticket_id="ticket_missing",
                conversation_id="conversation_missing",
                execution_id="execution_01",
                session_id="session_01",
                harness_request_id="harness_request_01",
                action_digest="digest",
                tool_id="request_refund",
                action_summary="Review refund action.",
            )
        )
