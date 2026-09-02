from fastapi.testclient import TestClient
from enterprise_agent_harness import ExecutionContext, PrincipalContext
from enterprise_agent_harness.tools import ToolInvocationError
import pytest

from cx_platform.domain.models import EscalationReason
from cx_platform.integrations.mock_business import MockBusinessClient
from cx_platform.persistence import CXDatabase, CXRepositories
from cx_platform.services import ConversationService
from cx_platform.tools.support import EscalationInput, build_support_tools
from mock_business.api import create_app


def test_support_catalog_exposes_governed_business_and_cx_tools(tmp_path) -> None:
    api = TestClient(create_app(":memory:"))
    api.post("/scenarios/delayed_delivery/activate")
    service = ConversationService(CXRepositories(CXDatabase(str(tmp_path / "cx.db"))))
    registry = build_support_tools(MockBusinessClient("http://testserver", client=api), service)
    tools = {tool.tool_id: tool for tool in registry.list()}
    assert tools["get_order"].kind.value == "read"
    assert tools["request_return"].kind.value == "write"
    assert tools["cancel_order"].kind.value == "action"
    assert len(tools) == 14


def test_escalation_tool_handler_creates_cx_handoff(tmp_path) -> None:
    service = ConversationService(CXRepositories(CXDatabase(str(tmp_path / "cx.db"))))
    _, ticket = service.start(customer_id="cx_cus_01", reason="Need a human")
    api = TestClient(create_app(":memory:"))
    registry = build_support_tools(MockBusinessClient("http://testserver", client=api), service)
    tool = registry.get("escalate_to_human", "1.0.0")
    result = tool.invoke(ExecutionContext(execution_id="exec_01", agent_id="support", agent_version="1.0.0", principal=PrincipalContext(principal_id="operator", tenant_id="demo", session_id="session_01"), state_id="state_01"), EscalationInput(ticket_id=ticket.ticket_id, reason=EscalationReason.CUSTOMER_REQUESTED_HUMAN, summary="Customer asked for a person").model_dump())
    assert result.output["ticket_id"] == ticket.ticket_id
    assert service.repositories.ticket(ticket.ticket_id).status.value == "ESCALATED"


def test_governed_tool_does_not_turn_business_outage_into_data(tmp_path) -> None:
    api = TestClient(create_app(":memory:"))
    api.post("/scenarios/shipping_service_outage/activate")
    service = ConversationService(CXRepositories(CXDatabase(str(tmp_path / "cx.db"))))
    tool = build_support_tools(MockBusinessClient("http://testserver", client=api), service).get("get_shipment", "1.0.0")
    context = ExecutionContext(execution_id="exec_01", agent_id="support", agent_version="1.0.0", principal=PrincipalContext(principal_id="operator", tenant_id="demo", session_id="session_01"), state_id="state_01")
    with pytest.raises(ToolInvocationError, match="failed"): tool.invoke(context, {"order_id": "ord_001"})


def test_all_registered_handlers_use_typed_business_or_cx_boundaries(tmp_path) -> None:
    api = TestClient(create_app(":memory:"))
    api.post("/scenarios/delayed_delivery/activate")
    service = ConversationService(CXRepositories(CXDatabase(str(tmp_path / "cx.db"))))
    _, ticket = service.start(customer_id="cx_cus_01", reason="Support request")
    registry = build_support_tools(MockBusinessClient("http://testserver", client=api), service)
    context = ExecutionContext(execution_id="exec_02", agent_id="support", agent_version="1.0.0", principal=PrincipalContext(principal_id="operator", tenant_id="demo", session_id="session_02"), state_id="state_02")
    inputs = {
        "get_customer": {"customer_id": "cus_001"}, "get_customer_orders": {"customer_id": "cus_001"},
        "get_order": {"order_id": "ord_001"}, "get_order_lines": {"order_id": "ord_001"},
        "get_order_payments": {"order_id": "ord_001"}, "get_shipment": {"order_id": "ord_001"},
        "get_fulfillment_issues": {"order_id": "ord_001"}, "get_returns": {"order_id": "ord_001"},
        "get_policy": {"topic": "delivery"}, "search_knowledge": {"topic": "delivery"},
    }
    for tool_id, arguments in inputs.items(): assert registry.get(tool_id, "1.0.0").invoke(context, arguments).status.value == "succeeded"
    api.post("/scenarios/cancellation_before_shipment/activate")
    assert registry.get("cancel_order", "1.0.0").invoke(context, {"order_id": "ord_001"}).status.value == "succeeded"
    api.post("/scenarios/damaged_item/activate")
    assert registry.get("request_return", "1.0.0").invoke(context, {"order_id": "ord_001", "line_id": "line_001", "quantity": 1, "reason": "Damaged"}).status.value == "succeeded"
    api.post("/scenarios/refund_requires_approval/activate")
    assert registry.get("request_refund", "1.0.0").invoke(context, {"order_id": "ord_001", "payment_id": "pay_001", "amount": "50.00", "reason": "Requested"}).status.value == "succeeded"
    assert registry.get("escalate_to_human", "1.0.0").invoke(context, {"ticket_id": ticket.ticket_id, "reason": "AGENT_UNCERTAIN", "summary": "Need a person"}).status.value == "succeeded"
