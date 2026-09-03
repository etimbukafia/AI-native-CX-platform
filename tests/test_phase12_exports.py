"""Public backend read-contract tests for CX evidence export."""

from __future__ import annotations

from fastapi.testclient import TestClient
from test_cx_support import make_support_service

from cx_platform.api import create_app
from cx_platform.domain.models import ResolutionCode, TicketStatus


def test_public_reads_reconstruct_one_support_journey_without_sqlite_access() -> None:
    service, business_api, conversation, ticket, _ = make_support_service(
        scenario="normal_delivery",
        tool_id="get_shipment",
        arguments={"order_id": "ord_001"},
    )
    result = service.handle_message(
        conversation.conversation_id,
        "Where is my order?",
    )
    api = TestClient(create_app(service))

    tickets = api.get("/tickets", params={"customer_id": "cx_cus_01"})
    ticket_read = api.get(f"/tickets/{ticket.ticket_id}")
    conversation_read = api.get(f"/conversations/{conversation.conversation_id}")
    outcomes = api.get("/outcomes", params={"ticket_id": ticket.ticket_id})
    execution = api.get(f"/executions/{result.execution_id}")
    events = api.get("/events")

    assert tickets.status_code == 200
    ticket_payload = tickets.json()[0]
    assert ticket_payload["ticket_id"] == ticket.ticket_id
    assert ticket_payload["status"] == TicketStatus.RESOLVED.value
    assert ticket_payload["resolution_code"] == ResolutionCode.DELIVERY_EXPLAINED.value
    assert ticket_read.status_code == 200
    ticket_payload = ticket_read.json()
    assert ticket_payload["ticket"]["ticket_id"] == ticket.ticket_id
    assert ticket_payload["conversation"]["conversation_id"] == conversation.conversation_id
    assert [item["actor_type"] for item in ticket_payload["messages"]] == [
        "CUSTOMER",
        "AI_AGENT",
    ]
    assert ticket_payload["outcomes"][0]["outcome_id"] == result.outcome_id

    assert conversation_read.status_code == 200
    conversation_payload = conversation_read.json()
    assert conversation_payload["conversation"]["ticket_id"] == ticket.ticket_id
    assert [item["message_id"] for item in conversation_payload["messages"]] == [
        item["message_id"] for item in ticket_payload["messages"]
    ]

    assert outcomes.status_code == 200
    outcome_payload = outcomes.json()[0]
    assert outcome_payload["ticket_id"] == ticket.ticket_id
    assert outcome_payload["execution_id"] == result.execution_id
    assert outcome_payload["resolution_code"] == ResolutionCode.DELIVERY_EXPLAINED.value

    assert execution.status_code == 200
    assert execution.json()["execution_id"] == result.execution_id
    assert execution.json()["agent_id"] == "customer-support-agent"
    assert "trace" not in execution.json()

    event_payload = events.json()
    assert any(
        item["ticket_id"] == ticket.ticket_id
        and item["execution_id"] == result.execution_id
        for item in event_payload
    )
    assert any(
        item["event_type"] == "shipment.read"
        for item in business_api.get("/events").json()
    )


def test_public_reads_return_typed_not_found_and_simple_pagination_errors() -> None:
    service, _, _, _, _ = make_support_service()
    api = TestClient(create_app(service))

    assert api.get("/tickets/ticket_missing").status_code == 404
    assert api.get("/conversations/conversation_missing").status_code == 404
    assert api.get("/executions/execution_missing").status_code == 404
    assert api.get("/tickets", params={"limit": 0}).status_code == 400
    assert api.get("/outcomes", params={"limit": 0}).status_code == 400


def test_ticket_read_preserves_approval_and_escalation_references() -> None:
    service, _, conversation, ticket, _ = make_support_service(
        scenario="refund_requires_approval",
        tool_id="request_refund",
        arguments={
            "order_id": "ord_001",
            "payment_id": "pay_001",
            "amount": "197.00",
            "reason": "Customer requested a refund.",
        },
    )
    waiting = service.handle_message(
        conversation.conversation_id,
        "Please refund this order.",
    )
    api = TestClient(create_app(service))

    payload = api.get(f"/tickets/{ticket.ticket_id}").json()

    assert payload["approvals"][0]["execution_id"] == waiting.execution_id
    assert payload["approvals"][0]["harness_request_id"]
    assert payload["escalations"] == []
