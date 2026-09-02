import pytest
from enterprise_agent_harness import ExecutionContext, PrincipalContext
from enterprise_agent_harness.tools import ToolInvocationError
from fastapi.testclient import TestClient

from cx_platform.domain.models import CustomerBinding, EscalationReason
from cx_platform.integrations.mock_business import MockBusinessClient
from cx_platform.persistence import CXDatabase, CXRepositories
from cx_platform.services import ConversationService
from cx_platform.tools.support import EscalationInput, build_support_tools
from mock_business.api import create_app


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


def execution_context(execution_id: str) -> ExecutionContext:
    return ExecutionContext(
        execution_id=execution_id,
        agent_id="support",
        agent_version="1.0.0",
        principal=PrincipalContext(
            principal_id="operator",
            tenant_id="demo",
            session_id=f"session_{execution_id}",
        ),
        state_id=f"state_{execution_id}",
    )


def test_support_catalog_exposes_governed_business_and_cx_tools(tmp_path) -> None:
    api = TestClient(create_app(":memory:"))
    service = make_service(tmp_path)
    registry = build_support_tools(MockBusinessClient("http://testserver", client=api), service)
    tools = {tool.tool_id: tool for tool in registry.list()}

    assert tools["get_order"].kind.value == "read"
    assert tools["request_return"].kind.value == "write"
    assert tools["cancel_order"].kind.value == "action"
    assert len(tools) == 14


def test_tool_descriptors_expose_typed_order_and_refund_outputs(tmp_path) -> None:
    api = TestClient(create_app(":memory:"))
    registry = build_support_tools(
        MockBusinessClient("http://testserver", client=api),
        make_service(tmp_path),
    )
    order_schema = registry.get("get_order", "1.0.0").descriptor.output_schema
    refund_schema = registry.get("request_refund", "1.0.0").descriptor.output_schema
    lines_schema = registry.get("get_order_lines", "1.0.0").descriptor.output_schema

    assert "order_id" in order_schema["properties"]
    assert "refund_id" in refund_schema["properties"]
    assert "order_lines" in lines_schema["properties"]


def test_escalation_tool_creates_cx_handoff(tmp_path) -> None:
    service = make_service(tmp_path)
    _, ticket = service.start(customer_id="cx_cus_01", reason="Need a human")
    api = TestClient(create_app(":memory:"))
    tool = build_support_tools(
        MockBusinessClient("http://testserver", client=api),
        service,
    ).get("escalate_to_human", "1.0.0")
    arguments = EscalationInput(
        ticket_id=ticket.ticket_id,
        reason=EscalationReason.CUSTOMER_REQUESTED_HUMAN,
        summary="Customer asked for a person",
    )

    result = tool.invoke(execution_context("exec_01"), arguments.model_dump())

    assert result.output["ticket_id"] == ticket.ticket_id
    assert service.repositories.ticket(ticket.ticket_id).status.value == "ESCALATED"


def test_governed_tool_does_not_turn_business_outage_into_data(tmp_path) -> None:
    api = TestClient(create_app(":memory:"))
    api.post("/scenarios/shipping_service_outage/activate")
    tool = build_support_tools(
        MockBusinessClient("http://testserver", client=api),
        make_service(tmp_path),
    ).get("get_shipment", "1.0.0")

    with pytest.raises(ToolInvocationError, match="failed"):
        tool.invoke(execution_context("exec_02"), {"order_id": "ord_001"})


def test_all_registered_handlers_use_typed_business_or_cx_boundaries(tmp_path) -> None:
    api = TestClient(create_app(":memory:"))
    api.post("/scenarios/delayed_delivery/activate")
    service = make_service(tmp_path)
    _, ticket = service.start(customer_id="cx_cus_01", reason="Support request")
    registry = build_support_tools(MockBusinessClient("http://testserver", client=api), service)
    context = execution_context("exec_03")
    read_arguments = {
        "get_customer": {"customer_id": "cus_001"},
        "get_customer_orders": {"customer_id": "cus_001"},
        "get_order": {"order_id": "ord_001"},
        "get_order_lines": {"order_id": "ord_001"},
        "get_order_payments": {"order_id": "ord_001"},
        "get_shipment": {"order_id": "ord_001"},
        "get_fulfillment_issues": {"order_id": "ord_001"},
        "get_returns": {"order_id": "ord_001"},
        "get_policy": {"topic": "delivery"},
        "search_knowledge": {"topic": "delivery"},
    }

    for tool_id, arguments in read_arguments.items():
        result = registry.get(tool_id, "1.0.0").invoke(context, arguments)
        assert result.status.value == "succeeded"

    api.post("/scenarios/cancellation_before_shipment/activate")
    cancellation = registry.get("cancel_order", "1.0.0").invoke(
        context,
        {"order_id": "ord_001"},
    )
    assert cancellation.status.value == "succeeded"

    api.post("/scenarios/damaged_item/activate")
    returned = registry.get("request_return", "1.0.0").invoke(
        context,
        {
            "order_id": "ord_001",
            "line_id": "line_001",
            "quantity": 1,
            "reason": "Damaged",
        },
    )
    assert returned.status.value == "succeeded"

    api.post("/scenarios/refund_requires_approval/activate")
    refunded = registry.get("request_refund", "1.0.0").invoke(
        context,
        {
            "order_id": "ord_001",
            "payment_id": "pay_001",
            "amount": "50.00",
            "reason": "Requested",
        },
    )
    assert refunded.status.value == "succeeded"

    escalated = registry.get("escalate_to_human", "1.0.0").invoke(
        context,
        {
            "ticket_id": ticket.ticket_id,
            "reason": "AGENT_UNCERTAIN",
            "summary": "Need a person",
        },
    )
    assert escalated.status.value == "succeeded"
