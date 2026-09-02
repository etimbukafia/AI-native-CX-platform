from enterprise_agent_harness import CapabilityRegistry
from fastapi.testclient import TestClient

from cx_platform.agent import build_support_capabilities
from cx_platform.domain.models import CustomerBinding
from cx_platform.integrations.mock_business import MockBusinessClient
from cx_platform.persistence import CXDatabase, CXRepositories
from cx_platform.services import ConversationService
from cx_platform.tools.support import build_support_tools
from mock_business.api import create_app

EXPECTED_TOOL_IDS = {
    "delivery_resolution": {
        "get_customer_orders",
        "get_order",
        "get_shipment",
        "get_fulfillment_issues",
        "get_policy",
        "search_knowledge",
        "request_refund",
        "escalate_to_human",
    },
    "payment_issue_resolution": {
        "get_customer_orders",
        "get_order",
        "get_order_payments",
        "get_policy",
        "search_knowledge",
        "request_refund",
        "escalate_to_human",
    },
    "refund_resolution": {
        "get_order",
        "get_order_payments",
        "get_shipment",
        "get_policy",
        "search_knowledge",
        "request_refund",
        "escalate_to_human",
    },
    "return_resolution": {
        "get_order",
        "get_order_lines",
        "get_shipment",
        "get_fulfillment_issues",
        "get_policy",
        "search_knowledge",
        "get_returns",
        "request_return",
        "request_refund",
        "escalate_to_human",
    },
    "cancellation_resolution": {
        "get_order",
        "get_shipment",
        "get_policy",
        "search_knowledge",
        "cancel_order",
        "escalate_to_human",
    },
    "damaged_item_resolution": {
        "get_order",
        "get_order_lines",
        "get_fulfillment_issues",
        "get_order_payments",
        "get_policy",
        "search_knowledge",
        "request_return",
        "request_refund",
        "escalate_to_human",
    },
    "missing_item_resolution": {
        "get_order",
        "get_order_lines",
        "get_fulfillment_issues",
        "get_order_payments",
        "get_policy",
        "search_knowledge",
        "request_refund",
        "escalate_to_human",
    },
}


def make_capability_registry(tmp_path) -> CapabilityRegistry:
    repositories = CXRepositories(CXDatabase(str(tmp_path / "cx.db")))
    repositories.save_binding(
        CustomerBinding(
            customer_id="cx_cus_01",
            external_customer_id="cus_001",
            display_name="Ada Okafor",
        )
    )
    service = ConversationService(repositories)
    api = TestClient(create_app(":memory:"))
    tools = build_support_tools(
        MockBusinessClient("http://testserver", client=api), service
    )
    return build_support_capabilities(tools)


def test_customer_service_capabilities_are_registered_with_deliberate_tools(
    tmp_path,
) -> None:
    registry = make_capability_registry(tmp_path)

    capabilities = {item.capability_id: item for item in registry.list()}

    assert set(capabilities) == set(EXPECTED_TOOL_IDS)
    assert all(item.version == "1.0.0" for item in capabilities.values())
    assert all(item.owner_id == "cx-platform" for item in capabilities.values())
    assert {
        item.capability_id: set(item.allowed_tool_ids) for item in capabilities.values()
    } == EXPECTED_TOOL_IDS


def test_capabilities_are_scenario_independent_and_searchable_by_intent(
    tmp_path,
) -> None:
    registry = make_capability_registry(tmp_path)
    scenario_ids = {
        "normal_delivery",
        "delayed_delivery",
        "lost_package",
        "duplicate_charge",
        "refund_requires_approval",
        "refund_denied_policy",
        "damaged_item",
        "missing_item",
        "cancellation_before_shipment",
        "cancellation_after_shipment",
        "shipping_service_outage",
    }

    for capability in registry.list():
        metadata = capability.model_dump()
        assert not scenario_ids.intersection(_string_values(metadata))

    delivery_matches = registry.search(intent="delivery_problem")

    assert [item.capability_id for item in delivery_matches] == ["delivery_resolution"]


def _string_values(value: object) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, dict):
        values: set[str] = set()
        for item in value.values():
            values.update(_string_values(item))
        return values
    if isinstance(value, (list, tuple, set)):
        values = set()
        for item in value:
            values.update(_string_values(item))
        return values
    return set()
