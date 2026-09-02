"""Phase 3 support tools registered through enterprise-agent-harness."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from enterprise_agent_harness import ExecutionContext, RiskLevel, ToolDefinition, ToolKind, ToolRegistry
from pydantic import BaseModel, ConfigDict, Field

from cx_platform.domain.models import EscalationReason, EscalationStatus
from cx_platform.integrations.mock_business import (
    CancellationResult,
    Customer,
    FulfillmentIssue,
    KnowledgeArticle,
    MockBusinessClient,
    Order,
    OrderLine,
    Payment,
    Policy,
    Refund,
    RefundRequest,
    Return,
    ReturnRequest,
    Shipment,
)
from cx_platform.services.lifecycle import ConversationService


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CustomerIdInput(Contract):
    customer_id: str = Field(min_length=1)


class OrderIdInput(Contract):
    order_id: str = Field(min_length=1)


class PolicyInput(Contract):
    topic: str = Field(min_length=1)


class KnowledgeInput(Contract):
    topic: str = Field(min_length=1)


class ReturnInput(Contract):
    order_id: str
    line_id: str
    quantity: int = Field(gt=0)
    reason: str = Field(min_length=1)


class RefundInput(Contract):
    order_id: str
    payment_id: str
    amount: Decimal = Field(gt=0)
    reason: str = Field(min_length=1)


class EscalationInput(Contract):
    ticket_id: str
    reason: EscalationReason
    summary: str = Field(min_length=1)


class CustomerOrdersOutput(Contract):
    orders: list[Order]


class OrderLinesOutput(Contract):
    order_lines: list[OrderLine]


class OrderPaymentsOutput(Contract):
    payments: list[Payment]


class FulfillmentIssuesOutput(Contract):
    fulfillment_issues: list[FulfillmentIssue]


class ReturnsOutput(Contract):
    returns: list[Return]


class KnowledgeSearchOutput(Contract):
    articles: list[KnowledgeArticle]


class EscalationOutput(Contract):
    escalation_id: str
    ticket_id: str
    status: EscalationStatus


ToolHandler = Callable[[ExecutionContext, BaseModel], BaseModel]


def build_support_tools(
    client: MockBusinessClient,
    conversations: ConversationService,
) -> ToolRegistry:
    def get_customer(_: ExecutionContext, arguments: CustomerIdInput) -> Customer:
        return client.get_customer(arguments.customer_id)

    def get_customer_orders(
        _: ExecutionContext,
        arguments: CustomerIdInput,
    ) -> CustomerOrdersOutput:
        return CustomerOrdersOutput(orders=client.get_customer_orders(arguments.customer_id))

    def get_order(_: ExecutionContext, arguments: OrderIdInput) -> Order:
        return client.get_order(arguments.order_id)

    def get_order_lines(_: ExecutionContext, arguments: OrderIdInput) -> OrderLinesOutput:
        return OrderLinesOutput(order_lines=client.get_order_lines(arguments.order_id))

    def get_order_payments(
        _: ExecutionContext,
        arguments: OrderIdInput,
    ) -> OrderPaymentsOutput:
        return OrderPaymentsOutput(payments=client.get_order_payments(arguments.order_id))

    def get_shipment(_: ExecutionContext, arguments: OrderIdInput) -> Shipment:
        return client.get_shipment(arguments.order_id)

    def get_fulfillment_issues(
        _: ExecutionContext,
        arguments: OrderIdInput,
    ) -> FulfillmentIssuesOutput:
        return FulfillmentIssuesOutput(
            fulfillment_issues=client.get_fulfillment_issues(arguments.order_id)
        )

    def get_returns(_: ExecutionContext, arguments: OrderIdInput) -> ReturnsOutput:
        return ReturnsOutput(returns=client.get_returns(arguments.order_id))

    def get_policy(_: ExecutionContext, arguments: PolicyInput) -> Policy:
        return client.get_policy(arguments.topic)

    def search_knowledge(
        _: ExecutionContext,
        arguments: KnowledgeInput,
    ) -> KnowledgeSearchOutput:
        return KnowledgeSearchOutput(articles=client.search_knowledge(arguments.topic))

    def cancel_order(_: ExecutionContext, arguments: OrderIdInput) -> CancellationResult:
        return client.cancel_order(arguments.order_id)

    def request_return(_: ExecutionContext, arguments: ReturnInput) -> Return:
        request = ReturnRequest(**arguments.model_dump())
        return client.request_return(request)

    def request_refund(_: ExecutionContext, arguments: RefundInput) -> Refund:
        request = RefundRequest(**arguments.model_dump())
        return client.request_refund(request)

    def escalate_to_human(
        _: ExecutionContext,
        arguments: EscalationInput,
    ) -> EscalationOutput:
        escalation = conversations.escalate(
            arguments.ticket_id,
            reason=arguments.reason,
            summary=arguments.summary,
        )
        return EscalationOutput(
            escalation_id=escalation.escalation_id,
            ticket_id=escalation.ticket_id,
            status=escalation.status,
        )

    tools = [
        _tool("get_customer", "Get one business customer.", CustomerIdInput, Customer, get_customer),
        _tool(
            "get_customer_orders",
            "Get all orders for one business customer.",
            CustomerIdInput,
            CustomerOrdersOutput,
            get_customer_orders,
        ),
        _tool("get_order", "Get one business order.", OrderIdInput, Order, get_order),
        _tool(
            "get_order_lines",
            "Get all lines for one business order.",
            OrderIdInput,
            OrderLinesOutput,
            get_order_lines,
        ),
        _tool(
            "get_order_payments",
            "Get all payments for one business order.",
            OrderIdInput,
            OrderPaymentsOutput,
            get_order_payments,
        ),
        _tool("get_shipment", "Get the shipment for one business order.", OrderIdInput, Shipment, get_shipment),
        _tool(
            "get_fulfillment_issues",
            "Get fulfillment issues for one business order.",
            OrderIdInput,
            FulfillmentIssuesOutput,
            get_fulfillment_issues,
        ),
        _tool("get_returns", "Get return records for one business order.", OrderIdInput, ReturnsOutput, get_returns),
        _tool("get_policy", "Get one current business policy.", PolicyInput, Policy, get_policy),
        _tool(
            "search_knowledge",
            "Search current business knowledge.",
            KnowledgeInput,
            KnowledgeSearchOutput,
            search_knowledge,
        ),
        _tool(
            "cancel_order",
            "Request an authoritative order cancellation.",
            OrderIdInput,
            CancellationResult,
            cancel_order,
            kind=ToolKind.ACTION,
            risk=RiskLevel.HIGH,
        ),
        _tool(
            "request_return",
            "Request an authoritative line-level return.",
            ReturnInput,
            Return,
            request_return,
            kind=ToolKind.WRITE,
            risk=RiskLevel.MEDIUM,
        ),
        _tool(
            "request_refund",
            "Request an authoritative refund.",
            RefundInput,
            Refund,
            request_refund,
            kind=ToolKind.ACTION,
            risk=RiskLevel.HIGH,
        ),
        _tool(
            "escalate_to_human",
            "Create a CX human handoff.",
            EscalationInput,
            EscalationOutput,
            escalate_to_human,
            kind=ToolKind.ACTION,
            risk=RiskLevel.MEDIUM,
        ),
    ]
    return ToolRegistry(tools)


def _tool(
    tool_id: str,
    description: str,
    input_model: type[BaseModel],
    output_model: type[BaseModel],
    handler: ToolHandler,
    *,
    kind: ToolKind = ToolKind.READ,
    risk: RiskLevel = RiskLevel.LOW,
) -> ToolDefinition:
    return ToolDefinition(
        tool_id=tool_id,
        version="1.0.0",
        description=description,
        input_model=input_model,
        output_model=output_model,
        handler=handler,
        kind=kind,
        risk_level=risk,
        owner_id="cx-platform",
        tags=("customer-support",),
        idempotency_required=kind is not ToolKind.READ,
    )
