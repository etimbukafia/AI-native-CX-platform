import sqlite3

import pytest
from enterprise_agent_harness import (
    AgentLifecycleStatus,
    DefaultPermissionBroker,
    OutcomeStatus,
    PolicyDefinition,
    PolicyEffect,
)
from fastapi.testclient import TestClient
from test_cx_support import make_support_service

from cx_platform.api import create_app
from cx_platform.domain.models import CXEventType


def test_support_timeline_links_cx_records_to_one_harness_trace() -> None:
    service, _, conversation, ticket, repositories = make_support_service()

    result = service.handle_message(conversation.conversation_id, "Where is my order?")
    service.conversations.submit_csat(ticket.ticket_id, score=5, comment="Clear")

    events = service.events()
    event_types = [event.event_type for event in events]
    expected = [
        CXEventType.TICKET_CREATED,
        CXEventType.CONVERSATION_STARTED,
        CXEventType.MESSAGE_CUSTOMER_RECEIVED,
        CXEventType.TICKET_STATUS_CHANGED,
        CXEventType.AGENT_EXECUTION_STARTED,
        CXEventType.AGENT_TOOL_CALLED,
        CXEventType.AGENT_TOOL_SUCCEEDED,
        CXEventType.AGENT_EXECUTION_COMPLETED,
        CXEventType.TICKET_STATUS_CHANGED,
        CXEventType.TICKET_RESOLVED,
        CXEventType.OUTCOME_RECORDED,
        CXEventType.MESSAGE_AGENT_SENT,
        CXEventType.CSAT_RECEIVED,
    ]

    assert event_types == expected
    assert all(
        event.customer_id == "cx_cus_01"
        and event.ticket_id == ticket.ticket_id
        and event.conversation_id == conversation.conversation_id
        for event in events
        if event.event_type
        not in {
            CXEventType.AGENT_EXECUTION_STARTED,
            CXEventType.AGENT_EXECUTION_COMPLETED,
        }
    )
    assert all(event.execution_id == result.execution_id for event in events[2:])
    assert all(
        "Where is my order?" not in event.model_dump_json() for event in events
    )

    reference = repositories.execution_reference(result.execution_id)
    trace = service.agent.trace_for(result.execution_id)
    assert reference is not None
    assert reference.agent_id == "customer-support-agent"
    assert reference.agent_version == "1.0.0"
    assert reference.trace_reference == trace.trace_id
    assert reference.outcome_status == result.status.value
    assert reference.completed_at is not None

    response = TestClient(create_app(service)).get(
        f"/executions/{result.execution_id}"
    )
    assert response.status_code == 200
    assert response.json()["trace_reference"] == trace.trace_id
    assert "trace" not in response.json()


def test_cx_events_poll_after_id_and_reject_duplicate_append() -> None:
    service, _, conversation, _, repositories = make_support_service()
    service.handle_message(conversation.conversation_id, "Where is my order?")

    events = service.events()
    assert service.events(after=events[0].event_id) == events[1:]
    assert service.events(after="0") == events

    api = TestClient(create_app(service))
    response = api.get(
        "/events",
        params={"after": events[0].event_id, "limit": 1},
    )
    assert response.status_code == 200
    assert response.json() == [events[1].model_dump(mode="json")]

    with pytest.raises(sqlite3.IntegrityError):
        repositories.append_event(events[0])
    with pytest.raises(sqlite3.IntegrityError), repositories.database.connect() as connection:
        connection.execute(
            "UPDATE cx_events SET actor_id=? WHERE event_id=?",
            ("operator-01", events[0].event_id),
        )


def test_failed_harness_tool_emits_failure_without_success() -> None:
    service, _, conversation, _, _ = make_support_service(
        scenario="shipping_service_outage",
        tool_id="get_shipment",
        arguments={"order_id": "ord_001"},
    )

    result = service.handle_message(conversation.conversation_id, "Where is the shipment?")
    execution_events = [
        event
        for event in service.events()
        if event.execution_id == result.execution_id
    ]

    assert any(
        event.event_type is CXEventType.AGENT_TOOL_FAILED
        for event in execution_events
    )
    assert not any(
        event.event_type is CXEventType.AGENT_TOOL_SUCCEEDED
        for event in execution_events
    )


def test_governance_tool_rejection_is_not_recorded_as_generic_failure() -> None:
    deny_policy = PolicyDefinition(
        policy_id="test-deny-tool",
        version="1.0.0",
        description="Deny this support action.",
        default_effect=PolicyEffect.DENY,
        lifecycle=AgentLifecycleStatus.ACTIVE,
    )
    service, _, conversation, _, _ = make_support_service(
        tool_id="request_return",
        arguments={
            "order_id": "ord_001",
            "line_id": "line_001",
            "quantity": 1,
            "reason": "Damaged",
        },
        permission_broker=DefaultPermissionBroker(policies=[deny_policy]),
    )

    result = service.handle_message(
        conversation.conversation_id,
        "Please return the damaged item.",
    )
    execution_events = [
        event
        for event in service.events()
        if event.execution_id == result.execution_id
    ]
    tool_called = next(
        event
        for event in execution_events
        if event.event_type is CXEventType.AGENT_TOOL_CALLED
    )

    assert result.status is OutcomeStatus.REFUSED
    assert tool_called.data["result_status"] == "permission_denied"
    assert not any(
        event.event_type is CXEventType.AGENT_TOOL_FAILED
        for event in execution_events
    )


def test_escalation_event_keeps_ticket_and_execution_correlation() -> None:
    service, _, conversation, ticket, _ = make_support_service(
        tool_id="escalate_to_human",
    )

    result = service.handle_message(conversation.conversation_id, "I need a person.")
    escalated = [
        event
        for event in service.events()
        if event.event_type is CXEventType.TICKET_ESCALATED
    ]

    assert len(escalated) == 1
    assert escalated[0].ticket_id == ticket.ticket_id
    assert escalated[0].conversation_id == conversation.conversation_id
    assert escalated[0].execution_id == result.execution_id


def test_approval_pause_and_resume_keep_one_execution_timeline() -> None:
    service, _, conversation, _, repositories = make_support_service(
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
        conversation.conversation_id,
        "Please refund this order.",
    )
    before = service.events()
    approval_event = next(
        event
        for event in before
        if event.event_type is CXEventType.APPROVAL_REQUESTED
    )
    assert approval_event.execution_id == waiting.execution_id
    assert not any(
        event.event_type is CXEventType.AGENT_EXECUTION_COMPLETED
        and event.execution_id == waiting.execution_id
        for event in before
    )

    resumed = service.approve(waiting.execution_id, decided_by="operator-01")
    after = service.events()
    decision_event = next(
        event
        for event in after
        if event.event_type is CXEventType.APPROVAL_APPROVED
    )
    assert resumed.execution_id == waiting.execution_id
    assert decision_event.execution_id == waiting.execution_id
    assert decision_event.data["approval_id"] == approval_event.data["approval_id"]
    assert sum(
        event.event_type is CXEventType.AGENT_EXECUTION_STARTED
        and event.execution_id == waiting.execution_id
        for event in after
    ) == 1
    assert sum(
        event.event_type is CXEventType.AGENT_EXECUTION_COMPLETED
        and event.execution_id == waiting.execution_id
        for event in after
    ) == 1
    assert repositories.execution_reference(waiting.execution_id).trace_reference
