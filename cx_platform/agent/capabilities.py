"""Phase 4 customer-service capability definitions."""

from __future__ import annotations

from collections.abc import Sequence

from enterprise_agent_harness import (
    AgentLifecycleStatus,
    CapabilityDefinition,
    CapabilityRegistry,
    RiskLevel,
    ToolRegistry,
)

CAPABILITY_VERSION = "1.0.0"


def build_support_capabilities(tools: ToolRegistry) -> CapabilityRegistry:
    """Build the active customer-service capability registry."""

    registry = CapabilityRegistry(tools=tools)
    for capability in _capability_definitions():
        registry.register(capability)
    return registry


def _capability_definitions() -> tuple[CapabilityDefinition, ...]:
    return (
        _capability(
            capability_id="delivery_resolution",
            description=(
                "Resolve delivery concerns with current order and shipment evidence "
                "and supported remedies."
            ),
            operations=("read", "action"),
            intents=("delivery_status", "delivery_problem"),
            tools=(
                "get_customer_orders",
                "get_order",
                "get_shipment",
                "get_fulfillment_issues",
                "get_policy",
                "search_knowledge",
                "request_refund",
                "escalate_to_human",
            ),
        ),
        _capability(
            capability_id="payment_issue_resolution",
            description=(
                "Investigate payment concerns and apply a supported correction "
                "when the current payment evidence allows it."
            ),
            operations=("read", "action"),
            intents=("payment_problem", "duplicate_payment"),
            tools=(
                "get_customer_orders",
                "get_order",
                "get_order_payments",
                "get_policy",
                "search_knowledge",
                "request_refund",
                "escalate_to_human",
            ),
        ),
        _capability(
            capability_id="refund_resolution",
            description=(
                "Assess refund requests against current order, payment, shipment, "
                "and policy evidence."
            ),
            operations=("read", "action"),
            intents=("refund_request", "refund_problem"),
            tools=(
                "get_order",
                "get_order_payments",
                "get_shipment",
                "get_policy",
                "search_knowledge",
                "request_refund",
                "escalate_to_human",
            ),
        ),
        _capability(
            capability_id="return_resolution",
            description=(
                "Manage eligible product return requests and related refunds "
                "for an order."
            ),
            operations=("read", "write", "action"),
            intents=("return_request", "return_problem"),
            tools=(
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
            ),
        ),
        _capability(
            capability_id="cancellation_resolution",
            description=(
                "Resolve order cancellation requests with current order and "
                "shipment state."
            ),
            operations=("read", "action"),
            intents=("cancellation_request", "cancellation_problem"),
            tools=(
                "get_order",
                "get_shipment",
                "get_policy",
                "search_knowledge",
                "cancel_order",
                "escalate_to_human",
            ),
        ),
        _capability(
            capability_id="damaged_item_resolution",
            description=(
                "Resolve confirmed product damage for the affected order line "
                "with a supported remedy."
            ),
            operations=("read", "write", "action"),
            intents=("damaged_product", "damaged_line"),
            tools=(
                "get_order",
                "get_order_lines",
                "get_fulfillment_issues",
                "get_order_payments",
                "get_policy",
                "search_knowledge",
                "request_return",
                "request_refund",
                "escalate_to_human",
            ),
        ),
        _capability(
            capability_id="missing_item_resolution",
            description=(
                "Resolve confirmed missing order lines with a supported refund "
                "or a safe handoff."
            ),
            operations=("read", "action"),
            intents=("missing_product", "missing_line"),
            tools=(
                "get_order",
                "get_order_lines",
                "get_fulfillment_issues",
                "get_order_payments",
                "get_policy",
                "search_knowledge",
                "request_refund",
                "escalate_to_human",
            ),
        ),
    )


def _capability(
    *,
    capability_id: str,
    description: str,
    operations: Sequence[str],
    intents: Sequence[str],
    tools: Sequence[str],
) -> CapabilityDefinition:
    """Create one active capability with the shared CX ownership metadata."""

    return CapabilityDefinition(
        capability_id=capability_id,
        version=CAPABILITY_VERSION,
        description=description,
        supported_operations=list(operations),
        supported_intents=list(intents),
        supported_languages=["en"],
        allowed_tool_ids=list(tools),
        risk_level=RiskLevel.HIGH,
        owner_id="cx-platform",
        lifecycle=AgentLifecycleStatus.ACTIVE,
        tags=["customer-support", "commerce"],
    )


__all__ = ["CAPABILITY_VERSION", "build_support_capabilities"]
