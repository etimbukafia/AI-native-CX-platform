"""Customer-service skills registered with Enterprise Agent Harness."""

from __future__ import annotations

from collections.abc import Sequence

from enterprise_agent_harness import (
    AgentLifecycleStatus,
    ComponentReference,
    ComponentType,
    RiskLevel,
    SkillDefinition,
    SkillRegistry,
    ToolRegistry,
)

SKILL_VERSION = "1.0.0"
_TOOL_VERSION = "1.0.0"


def build_support_skills(tools: ToolRegistry) -> SkillRegistry:
    """Build the seven active customer-service skills."""

    registry = SkillRegistry(tools=tools)
    for skill in _skill_definitions():
        registry.register(skill)
    return registry


def _skill_definitions() -> tuple[SkillDefinition, ...]:
    """Return the stable support skill metadata and dependency graph."""

    return (
        _skill(
            skill_id="delivery_resolution",
            name="Delivery resolution",
            description=(
                "Resolve delivery concerns with current order and shipment evidence "
                "and supported remedies."
            ),
            operations=("read", "action"),
            intents=("delivery_status", "delivery_problem"),
            required=(
                "get_customer_orders",
                "get_order",
                "get_shipment",
                "get_fulfillment_issues",
                "get_policy",
            ),
            optional=("search_knowledge", "request_refund", "escalate_to_human"),
        ),
        _skill(
            skill_id="payment_issue_resolution",
            name="Payment issue resolution",
            description=(
                "Investigate payment concerns and apply a supported correction "
                "when current payment evidence allows it."
            ),
            operations=("read", "action"),
            intents=("payment_problem", "duplicate_payment"),
            required=(
                "get_customer_orders",
                "get_order",
                "get_order_payments",
                "get_policy",
            ),
            optional=("search_knowledge", "request_refund", "escalate_to_human"),
        ),
        _skill(
            skill_id="refund_resolution",
            name="Refund resolution",
            description=(
                "Assess refund requests against current order, payment, shipment, "
                "and policy evidence."
            ),
            operations=("read", "action"),
            intents=("refund_request", "refund_problem"),
            required=("get_order", "get_order_payments", "get_shipment", "get_policy"),
            optional=("search_knowledge", "request_refund", "escalate_to_human"),
        ),
        _skill(
            skill_id="return_resolution",
            name="Return resolution",
            description=(
                "Manage eligible product return requests and related refunds "
                "for an order."
            ),
            operations=("read", "write", "action"),
            intents=("return_request", "return_problem"),
            required=(
                "get_order",
                "get_order_lines",
                "get_shipment",
                "get_returns",
                "get_policy",
            ),
            optional=(
                "get_fulfillment_issues",
                "search_knowledge",
                "request_return",
                "request_refund",
                "escalate_to_human",
            ),
        ),
        _skill(
            skill_id="cancellation_resolution",
            name="Cancellation resolution",
            description=(
                "Resolve order cancellation requests with current order and "
                "shipment state."
            ),
            operations=("read", "action"),
            intents=("cancellation_request", "cancellation_problem"),
            required=("get_order", "get_shipment", "get_policy"),
            optional=("search_knowledge", "cancel_order", "escalate_to_human"),
        ),
        _skill(
            skill_id="damaged_item_resolution",
            name="Damaged item resolution",
            description=(
                "Resolve confirmed product damage for the affected order line "
                "with a supported remedy."
            ),
            operations=("read", "write", "action"),
            intents=("damaged_product", "damaged_line"),
            required=(
                "get_order",
                "get_order_lines",
                "get_fulfillment_issues",
                "get_policy",
            ),
            optional=(
                "get_order_payments",
                "search_knowledge",
                "request_return",
                "request_refund",
                "escalate_to_human",
            ),
        ),
        _skill(
            skill_id="missing_item_resolution",
            name="Missing item resolution",
            description=(
                "Resolve confirmed missing order lines with a supported refund "
                "or a safe handoff."
            ),
            operations=("read", "action"),
            intents=("missing_product", "missing_line"),
            required=(
                "get_order",
                "get_order_lines",
                "get_fulfillment_issues",
                "get_policy",
            ),
            optional=(
                "get_order_payments",
                "search_knowledge",
                "request_refund",
                "escalate_to_human",
            ),
        ),
    )


def _skill(
    *,
    skill_id: str,
    name: str,
    description: str,
    operations: Sequence[str],
    intents: Sequence[str],
    required: Sequence[str],
    optional: Sequence[str],
) -> SkillDefinition:
    """Create one skill with explicit required and optional tool dependencies."""

    return SkillDefinition(
        skill_id=skill_id,
        version=SKILL_VERSION,
        name=name,
        description=description,
        supported_operations=tuple(operations),
        supported_intents=tuple(intents),
        supported_languages=("en",),
        required_tool_refs=tuple(_tool_reference(tool_id) for tool_id in required),
        optional_tool_refs=tuple(_tool_reference(tool_id) for tool_id in optional),
        risk_level=RiskLevel.HIGH,
        owner_id="cx-platform",
        lifecycle=AgentLifecycleStatus.ACTIVE,
        tags=("customer-support", "commerce"),
    )


def _tool_reference(tool_id: str) -> ComponentReference:
    """Return one exact CX tool reference used by a skill."""

    return ComponentReference(
        component_type=ComponentType.TOOL,
        component_id=tool_id,
        version=_TOOL_VERSION,
    )


__all__ = ["SKILL_VERSION", "build_support_skills"]
