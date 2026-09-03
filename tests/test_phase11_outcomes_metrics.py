"""Behavior tests for structured CX outcomes and aggregate metrics."""

from __future__ import annotations

from enterprise_agent_harness import (
    AgentLifecycleStatus,
    DefaultPermissionBroker,
    OutcomeStatus,
    PolicyDefinition,
    PolicyEffect,
)
from test_cx_support import make_support_service

from cx_platform.domain.models import (
    CXEventType,
    ResolutionCode,
    TicketStatus,
)


def test_outcome_read_is_derived_from_persisted_support_evidence() -> None:
    service, _, conversation, ticket, _ = make_support_service(
        scenario="delayed_delivery",
        tool_id="get_shipment",
        arguments={"order_id": "ord_001"},
    )

    result = service.handle_message(conversation.conversation_id, "My delivery is late.")
    service.conversations.submit_csat(ticket.ticket_id, score=5)

    outcome = service.outcomes()[0]

    assert result.status is OutcomeStatus.COMPLETED
    assert outcome.outcome_id == result.outcome_id
    assert outcome.ticket_id == ticket.ticket_id
    assert outcome.execution_id == result.execution_id
    assert outcome.resolution_code is ResolutionCode.DELIVERY_EXPLAINED
    assert outcome.resolved is True
    assert outcome.escalated is False
    assert outcome.turn_count == 1
    assert outcome.tool_call_count == 1
    assert outcome.tool_failure_count == 0
    assert outcome.approval_required is False
    assert outcome.approval_result is None
    assert outcome.duration is not None
    assert outcome.csat_score == 5
    assert outcome.tool_ids == ["get_shipment"]


def test_escalated_outcome_preserves_dependency_classification() -> None:
    service, _, conversation, ticket, _ = make_support_service(
        scenario="shipping_service_outage",
        tool_id="get_shipment",
        arguments={"order_id": "ord_001"},
    )

    result = service.handle_message(
        conversation.conversation_id,
        "Where is my shipment?",
    )
    outcome = service.outcomes()[0]

    assert result.ticket_status is TicketStatus.ESCALATED
    assert outcome.ticket_id == ticket.ticket_id
    assert outcome.resolution_code is ResolutionCode.DEPENDENCY_UNAVAILABLE
    assert outcome.resolved is False
    assert outcome.escalated is True
    assert outcome.tool_failure_count == 1


def test_permission_denial_does_not_inflate_tool_failure_metric() -> None:
    deny_policy = PolicyDefinition(
        policy_id="metrics-deny-tool",
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

    service.handle_message(conversation.conversation_id, "Please return this item.")
    metrics = service.metrics()

    assert metrics.tool_call_count == 1
    assert metrics.tool_failure_count == 0
    assert metrics.tool_failure_rate == 0.0
    assert not any(
        event.event_type is CXEventType.AGENT_TOOL_FAILED
        for event in service.events()
    )


def test_metrics_use_terminal_outcomes_and_actual_tool_failures() -> None:
    service, business_api, first_conversation, _, _ = make_support_service(
        scenario="delayed_delivery",
        tool_id="get_shipment",
        arguments={"order_id": "ord_001"},
    )
    first = service.handle_message(
        first_conversation.conversation_id,
        "My delivery is late.",
    )
    second_conversation, second_ticket = service.conversations.start(
        customer_id="cx_cus_01",
        reason="Shipment unavailable",
    )
    business_api.post("/scenarios/shipping_service_outage/activate")
    second = service.handle_message(
        second_conversation.conversation_id,
        "Where is my shipment?",
    )

    metrics = service.metrics()

    assert first.status is OutcomeStatus.COMPLETED
    assert second.ticket_status is TicketStatus.ESCALATED
    assert service.tickets(status=TicketStatus.ESCALATED)[0].ticket_id == (
        second_ticket.ticket_id
    )
    assert metrics.conversation_count == 2
    assert metrics.terminal_outcome_count == 2
    assert metrics.resolved_count == 1
    assert metrics.resolution_rate == 0.5
    assert metrics.escalated_count == 1
    assert metrics.escalation_rate == 0.5
    assert metrics.average_turns == 1.0
    assert metrics.tool_call_count == 2
    assert metrics.tool_failure_count == 1
    assert metrics.tool_failure_rate == 0.5
    assert metrics.average_submitted_csat is None
    assert metrics.outcome_distribution == {
        ResolutionCode.DELIVERY_EXPLAINED.value: 1,
        ResolutionCode.DEPENDENCY_UNAVAILABLE.value: 1,
    }


def test_approval_rate_uses_decided_approval_records() -> None:
    service, _, conversation, _, _ = make_support_service(
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
    before = service.metrics()
    service.approve(waiting.execution_id, decided_by="operator-01")
    after = service.metrics()

    assert before.approval_count == 1
    assert before.approval_decided_count == 0
    assert before.approval_rate == 0.0
    assert after.approval_count == 1
    assert after.approval_decided_count == 1
    assert after.approval_rate == 1.0
