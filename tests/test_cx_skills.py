from enterprise_agent_harness import (
    AgentDefinition,
    AgentLifecycleStatus,
    AgentRegistry,
    AgentVersion,
    ComponentReference,
    ComponentType,
    IncompatibleRegistrationError,
    ProviderProfile,
    ToolRegistry,
)
from fastapi.testclient import TestClient

from cx_platform.agent import (
    SUPPORT_PROMPT_ID,
    SUPPORT_PROMPT_VERSION,
    build_support_policy,
    build_support_prompt_registry,
    build_support_skills,
)
from cx_platform.domain.models import CustomerBinding
from cx_platform.integrations.mock_business import MockBusinessClient
from cx_platform.persistence import CXDatabase, CXRepositories
from cx_platform.services import ConversationService
from cx_platform.tools.support import build_support_tools
from mock_business.api import create_app

EXPECTED_REQUIRED_TOOL_IDS = {
    "delivery_resolution": {
        "get_customer_orders",
        "get_order",
        "get_shipment",
        "get_fulfillment_issues",
        "get_policy",
    },
    "payment_issue_resolution": {
        "get_customer_orders",
        "get_order",
        "get_order_payments",
        "get_policy",
    },
    "refund_resolution": {
        "get_order",
        "get_order_payments",
        "get_shipment",
        "get_policy",
    },
    "return_resolution": {
        "get_order",
        "get_order_lines",
        "get_shipment",
        "get_returns",
        "get_policy",
    },
    "cancellation_resolution": {"get_order", "get_shipment", "get_policy"},
    "damaged_item_resolution": {
        "get_order",
        "get_order_lines",
        "get_fulfillment_issues",
        "get_policy",
    },
    "missing_item_resolution": {
        "get_order",
        "get_order_lines",
        "get_fulfillment_issues",
        "get_policy",
    },
}

EXPECTED_OPTIONAL_TOOL_IDS = {
    "delivery_resolution": {"search_knowledge", "request_refund", "escalate_to_human"},
    "payment_issue_resolution": {
        "search_knowledge",
        "request_refund",
        "escalate_to_human",
    },
    "refund_resolution": {"search_knowledge", "request_refund", "escalate_to_human"},
    "return_resolution": {
        "get_fulfillment_issues",
        "search_knowledge",
        "request_return",
        "request_refund",
        "escalate_to_human",
    },
    "cancellation_resolution": {
        "search_knowledge",
        "cancel_order",
        "escalate_to_human",
    },
    "damaged_item_resolution": {
        "get_order_payments",
        "search_knowledge",
        "request_return",
        "request_refund",
        "escalate_to_human",
    },
    "missing_item_resolution": {
        "get_order_payments",
        "search_knowledge",
        "request_refund",
        "escalate_to_human",
    },
}


def make_skill_registry(tmp_path):
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
    return build_support_skills(tools), tools


def test_customer_service_skills_register_with_deliberate_dependencies(
    tmp_path,
) -> None:
    registry, _ = make_skill_registry(tmp_path)

    skills = {item.skill_id: item for item in registry.list()}

    assert set(skills) == set(EXPECTED_REQUIRED_TOOL_IDS)
    assert all(item.version == "1.0.0" for item in skills.values())
    assert all(item.owner_id == "cx-platform" for item in skills.values())
    assert {
        item.skill_id: {ref.component_id for ref in item.required_tool_refs}
        for item in skills.values()
    } == EXPECTED_REQUIRED_TOOL_IDS
    assert {
        item.skill_id: {ref.component_id for ref in item.optional_tool_refs}
        for item in skills.values()
    } == EXPECTED_OPTIONAL_TOOL_IDS
    assert all(
        ref.component_type is ComponentType.TOOL
        for item in skills.values()
        for ref in item.tool_refs
    )


def test_skills_are_scenario_independent_and_searchable_by_intent(tmp_path) -> None:
    registry, _ = make_skill_registry(tmp_path)
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

    for skill in registry.list():
        assert not scenario_ids.intersection(_string_values(skill.model_dump()))

    delivery_matches = registry.search(intent="delivery_problem")

    assert [item.skill_id for item in delivery_matches] == ["delivery_resolution"]


def test_missing_required_skill_tool_blocks_registration(tmp_path) -> None:
    _, tools = make_skill_registry(tmp_path)
    missing_tool = "get_order"
    reduced_tools = ToolRegistry(
        tool for tool in tools.list() if tool.tool_id != missing_tool
    )

    try:
        build_support_skills(reduced_tools)
    except IncompatibleRegistrationError as exc:
        assert missing_tool in str(exc)
    else:
        raise AssertionError("a missing required skill tool must block registration")


def test_missing_optional_skill_tool_does_not_block_registration(tmp_path) -> None:
    _, tools = make_skill_registry(tmp_path)
    reduced_tools = ToolRegistry(
        tool for tool in tools.list() if tool.tool_id != "request_refund"
    )

    registry = build_support_skills(reduced_tools)

    assert len(registry.list()) == 7
    delivery = registry.get("delivery_resolution", "1.0.0")
    assert "request_refund" in {ref.component_id for ref in delivery.optional_tool_refs}


def test_optional_skill_dependency_does_not_grant_agent_tool_authority(
    tmp_path,
) -> None:
    skills, tools = make_skill_registry(tmp_path)
    delivery = skills.get("delivery_resolution", "1.0.0")
    policy = build_support_policy()
    registry = AgentRegistry(
        prompts=build_support_prompt_registry(),
        skills=skills,
        tools=tools,
        policies=[policy],
    )
    agent = AgentDefinition(
        identity=AgentVersion(agent_id="optional-authority-check", version="1.0.0"),
        goal="Check delivery evidence.",
        supported_intents=["delivery_problem"],
        supported_languages=["en"],
        prompt_ref=ComponentReference(
            component_type=ComponentType.PROMPT,
            component_id=SUPPORT_PROMPT_ID,
            version=SUPPORT_PROMPT_VERSION,
        ),
        skill_refs=[
            ComponentReference(
                component_type=ComponentType.SKILL,
                component_id=delivery.skill_id,
                version=delivery.version,
            )
        ],
        tool_refs=list(delivery.required_tool_refs),
        policy_refs=[
            ComponentReference(
                component_type=ComponentType.POLICY,
                component_id=policy.policy_id,
                version=policy.version,
            )
        ],
        provider_profile=ProviderProfile(
            provider_id="deterministic",
            version="1.0.0",
            model="test-model",
        ),
        risk_level=delivery.risk_level,
        owner_id="cx-platform",
        lifecycle=AgentLifecycleStatus.DRAFT,
    )

    registry.register(agent)
    registry.activate(agent.agent_id, agent.version)

    optional_tool = "request_refund"
    assert optional_tool in {ref.component_id for ref in delivery.optional_tool_refs}
    assert registry.agents_using_tool(optional_tool, "1.0.0") == []
    assert [
        item.agent_id
        for item in registry.agents_with_skill_referencing_tool(
            optional_tool,
            "1.0.0",
        )
    ] == [agent.agent_id]
    assert {
        ref.component_id
        for ref in registry.get(agent.agent_id, agent.version).tool_refs
    } == {ref.component_id for ref in delivery.required_tool_refs}


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
