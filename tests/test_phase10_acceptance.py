"""Reference business-scenario acceptance tests for the governed CX path."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from enterprise_agent_harness import (
    AgentPlan,
    DeterministicProvider,
    OutcomeStatus,
    PlanningRequest,
    PlanStep,
)
from test_cx_support import make_support_service

from cx_platform.domain.models import ResolutionCode, TicketStatus


class ScenarioProvider(DeterministicProvider):
    """Return one repeatable governed plan for a reference scenario."""

    def __init__(self, steps: list[PlanStep]) -> None:
        super().__init__(tool_id=steps[0].tool_id if steps else None)
        self.steps = steps
        self.ticket_id: str | None = None

    def plan(self, *, request: PlanningRequest) -> AgentPlan:
        del request
        return AgentPlan(steps=[self._resolve_ticket(step) for step in self.steps])

    def _resolve_ticket(self, step: PlanStep) -> PlanStep:
        if self.ticket_id is None:
            return step
        arguments = {
            key: self.ticket_id if value == "$ticket_id" else value
            for key, value in step.arguments.items()
        }
        return step.model_copy(update={"arguments": arguments})


@dataclass(frozen=True)
class ScenarioCase:
    scenario_id: str
    request: str
    steps: tuple[PlanStep, ...]
    expected_status: OutcomeStatus
    expected_ticket_status: TicketStatus
    required_events: tuple[str, ...]
    forbidden_events: tuple[str, ...]


def read_step(
    step_id: str,
    tool_id: str,
    arguments: dict[str, object],
) -> PlanStep:
    return PlanStep(
        step_id=step_id,
        tool_id=tool_id,
        tool_version="1.0.0",
        purpose=f"Run the {tool_id} reference operation.",
        arguments=arguments,
    )


def action_step(
    step_id: str,
    tool_id: str,
    arguments: dict[str, object],
) -> PlanStep:
    return read_step(step_id, tool_id, arguments).model_copy(
        update={"idempotency_key": f"acceptance:{step_id}"}
    )


CASES = (
    ScenarioCase(
        "normal_delivery",
        "Where is my order?",
        (read_step("shipment", "get_shipment", {"order_id": "ord_001"}),),
        OutcomeStatus.COMPLETED,
        TicketStatus.RESOLVED,
        ("shipment.read",),
        ("refund.approved", "return.approved", "order.cancelled"),
    ),
    ScenarioCase(
        "delayed_delivery",
        "My delivery is late.",
        (read_step("shipment", "get_shipment", {"order_id": "ord_001"}),),
        OutcomeStatus.COMPLETED,
        TicketStatus.RESOLVED,
        ("shipment.read",),
        ("refund.approved", "return.approved", "order.cancelled"),
    ),
    ScenarioCase(
        "lost_package",
        "My package is lost.",
        (
            read_step("shipment", "get_shipment", {"order_id": "ord_001"}),
            read_step("policy", "get_policy", {"topic": "delivery"}),
            action_step(
                "escalation",
                "escalate_to_human",
                {
                    "ticket_id": "$ticket_id",
                    "reason": "AGENT_UNCERTAIN",
                    "summary": "The carrier marked this shipment lost.",
                },
            ),
        ),
        OutcomeStatus.COMPLETED,
        TicketStatus.ESCALATED,
        ("shipment.read", "policy.read"),
        ("refund.approved", "return.approved", "order.cancelled"),
    ),
    ScenarioCase(
        "duplicate_charge",
        "I was charged twice.",
        (
            read_step("payments", "get_order_payments", {"order_id": "ord_001"}),
            action_step(
                "refund",
                "request_refund",
                {
                    "order_id": "ord_001",
                    "payment_id": "pay_002",
                    "amount": "89.00",
                    "reason": "Confirmed duplicate charge.",
                },
            ),
        ),
        OutcomeStatus.COMPLETED,
        TicketStatus.RESOLVED,
        ("order.payments_read", "refund.approved"),
        ("refund.rejected",),
    ),
    ScenarioCase(
        "refund_requires_approval",
        "Please refund this order.",
        (
            action_step(
                "refund",
                "request_refund",
                {
                    "order_id": "ord_001",
                    "payment_id": "pay_001",
                    "amount": "197.00",
                    "reason": "Customer requested a refund.",
                },
            ),
        ),
        OutcomeStatus.COMPLETED,
        TicketStatus.RESOLVED,
        ("refund.approved",),
        ("refund.rejected",),
    ),
    ScenarioCase(
        "refund_denied_policy",
        "Please refund this old order.",
        (
            read_step("payments", "get_order_payments", {"order_id": "ord_001"}),
            action_step(
                "refund",
                "request_refund",
                {
                    "order_id": "ord_001",
                    "payment_id": "pay_001",
                    "amount": "89.00",
                    "reason": "Customer requested a refund.",
                },
            ),
        ),
        OutcomeStatus.PARTIAL,
        TicketStatus.ESCALATED,
        ("order.payments_read", "refund.rejected"),
        ("refund.approved",),
    ),
    ScenarioCase(
        "damaged_item",
        "One headphone is damaged.",
        (
            read_step(
                "issues",
                "get_fulfillment_issues",
                {"order_id": "ord_001"},
            ),
            action_step(
                "return",
                "request_return",
                {
                    "order_id": "ord_001",
                    "line_id": "line_001",
                    "quantity": 1,
                    "reason": "Confirmed damaged item.",
                },
            ),
        ),
        OutcomeStatus.COMPLETED,
        TicketStatus.RESOLVED,
        ("order.fulfillment_issues_read", "return.approved"),
        ("refund.approved",),
    ),
    ScenarioCase(
        "missing_item",
        "The charger is missing from my delivery.",
        (
            read_step(
                "issues",
                "get_fulfillment_issues",
                {"order_id": "ord_001"},
            ),
            action_step(
                "return",
                "request_return",
                {
                    "order_id": "ord_001",
                    "line_id": "line_002",
                    "quantity": 1,
                    "reason": "Confirmed missing item.",
                },
            ),
        ),
        OutcomeStatus.COMPLETED,
        TicketStatus.RESOLVED,
        ("order.fulfillment_issues_read", "return.approved"),
        ("refund.approved",),
    ),
    ScenarioCase(
        "cancellation_before_shipment",
        "Cancel my order.",
        (action_step("cancel", "cancel_order", {"order_id": "ord_001"}),),
        OutcomeStatus.COMPLETED,
        TicketStatus.RESOLVED,
        ("order.cancelled",),
        ("order.cancellation_rejected",),
    ),
    ScenarioCase(
        "cancellation_after_shipment",
        "Cancel my shipped order.",
        (action_step("cancel", "cancel_order", {"order_id": "ord_001"}),),
        OutcomeStatus.FAILED,
        TicketStatus.ESCALATED,
        ("order.cancellation_rejected",),
        ("order.cancelled",),
    ),
    ScenarioCase(
        "shipping_service_outage",
        "Where is my shipment?",
        (read_step("shipment", "get_shipment", {"order_id": "ord_001"}),),
        OutcomeStatus.FAILED,
        TicketStatus.ESCALATED,
        ("shipping.lookup_failed",),
        ("shipment.read",),
    ),
)


@pytest.mark.parametrize("case", CASES, ids=[case.scenario_id for case in CASES])
def test_reference_scenario_uses_the_governed_support_path(case: ScenarioCase) -> None:
    provider = ScenarioProvider(list(case.steps))
    service, business_api, conversation, ticket, repositories = make_support_service(
        scenario=case.scenario_id,
        provider=provider,
    )
    provider.ticket_id = ticket.ticket_id

    result = service.handle_message(conversation.conversation_id, case.request)
    if result.ticket_status is TicketStatus.WAITING_APPROVAL:
        result = service.approve(result.execution_id, decided_by="operator-01")

    business_events = business_api.get("/events").json()
    event_types = [event["event_type"] for event in business_events]

    assert result.status is case.expected_status
    assert result.ticket_status is case.expected_ticket_status
    assert repositories.ticket(ticket.ticket_id).status is case.expected_ticket_status
    for event_type in case.required_events:
        assert event_type in event_types
    for event_type in case.forbidden_events:
        assert event_type not in event_types

    outcome = repositories.outcomes(ticket.ticket_id)
    assert len(outcome) == 1
    assert outcome[0].metadata["execution_id"] == result.execution_id

    if case.scenario_id == "duplicate_charge":
        refund_events = [event for event in business_events if event["event_type"] == "refund.approved"]
        assert refund_events[0]["data"]["payment_id"] == "pay_002"
        assert service.outcomes()[0].resolution_code is ResolutionCode.PAYMENT_ISSUE_RESOLVED
    if case.scenario_id == "damaged_item":
        return_events = [event for event in business_events if event["event_type"] == "return.approved"]
        assert return_events[0]["data"]["line_id"] == "line_001"
    if case.scenario_id == "missing_item":
        return_events = [event for event in business_events if event["event_type"] == "return.approved"]
        assert return_events[0]["data"]["line_id"] == "line_002"


def test_approval_scenario_has_no_business_action_before_approval() -> None:
    provider = ScenarioProvider(
        [
            action_step(
                "refund",
                "request_refund",
                {
                    "order_id": "ord_001",
                    "payment_id": "pay_001",
                    "amount": "197.00",
                    "reason": "Customer requested a refund.",
                },
            )
        ]
    )
    service, business_api, conversation, _, _ = make_support_service(
        scenario="refund_requires_approval",
        provider=provider,
    )

    waiting = service.handle_message(
        conversation.conversation_id,
        "Please refund this order.",
    )

    assert waiting.ticket_status is TicketStatus.WAITING_APPROVAL
    assert not any(
        event["event_type"] in {"refund.approved", "refund.rejected"}
        for event in business_api.get("/events").json()
    )
