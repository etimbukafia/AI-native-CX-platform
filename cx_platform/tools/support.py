"""Phase 3 support tools registered through enterprise-agent-harness."""
from __future__ import annotations

from typing import Any

from enterprise_agent_harness import RiskLevel, ToolDefinition, ToolKind, ToolRegistry
from pydantic import BaseModel, ConfigDict, Field

from cx_platform.domain.models import EscalationReason
from cx_platform.integrations.mock_business import MockBusinessClient, RefundRequest, ReturnRequest
from cx_platform.services.lifecycle import ConversationService


class Contract(BaseModel): model_config = ConfigDict(extra="forbid", frozen=True)
class CustomerIdInput(Contract): customer_id: str = Field(min_length=1)
class OrderIdInput(Contract): order_id: str = Field(min_length=1)
class PolicyInput(Contract): topic: str = Field(min_length=1)
class KnowledgeInput(Contract): topic: str = Field(min_length=1)
class ReturnInput(Contract): order_id: str; line_id: str; quantity: int = Field(gt=0); reason: str = Field(min_length=1)
class RefundInput(Contract): order_id: str; payment_id: str; amount: str = Field(min_length=1); reason: str = Field(min_length=1)
class EscalationInput(Contract): ticket_id: str; reason: EscalationReason; summary: str = Field(min_length=1)
class DataOutput(Contract): data: dict[str, Any]
class ItemsOutput(Contract): items: list[dict[str, Any]]
class EscalationOutput(Contract): escalation_id: str; ticket_id: str; status: str


def build_support_tools(client: MockBusinessClient, conversations: ConversationService) -> ToolRegistry:
    def one(method: str):
        return lambda _context, arguments: DataOutput(data=getattr(client, method)(**arguments.model_dump()).model_dump(mode="json"))
    def many(method: str):
        return lambda _context, arguments: ItemsOutput(items=[x.model_dump(mode="json") for x in getattr(client, method)(**arguments.model_dump())])
    def request_return(_context: object, arguments: ReturnInput) -> DataOutput:
        result = client.request_return(ReturnRequest(**arguments.model_dump()))
        return DataOutput(data=result.model_dump(mode="json"))
    def request_refund(_context: object, arguments: RefundInput) -> DataOutput:
        result = client.request_refund(RefundRequest(**arguments.model_dump()))
        return DataOutput(data=result.model_dump(mode="json"))
    def escalate(_context: object, arguments: EscalationInput) -> EscalationOutput:
        result = conversations.escalate(arguments.ticket_id, reason=arguments.reason, summary=arguments.summary)
        return EscalationOutput(escalation_id=result.escalation_id, ticket_id=result.ticket_id, status=result.status)
    tools = [
        _tool("get_customer", "Get one business customer.", CustomerIdInput, DataOutput, one("get_customer")),
        _tool("get_customer_orders", "Get all orders for one business customer.", CustomerIdInput, ItemsOutput, many("get_customer_orders")),
        _tool("get_order", "Get one business order.", OrderIdInput, DataOutput, one("get_order")),
        _tool("get_order_lines", "Get all lines for one business order.", OrderIdInput, ItemsOutput, many("get_order_lines")),
        _tool("get_order_payments", "Get all payments for one business order.", OrderIdInput, ItemsOutput, many("get_order_payments")),
        _tool("get_shipment", "Get the shipment for one business order.", OrderIdInput, DataOutput, one("get_shipment")),
        _tool("get_fulfillment_issues", "Get fulfillment issues for one business order.", OrderIdInput, ItemsOutput, many("get_fulfillment_issues")),
        _tool("get_returns", "Get return records for one business order.", OrderIdInput, ItemsOutput, many("get_returns")),
        _tool("get_policy", "Get one current business policy.", PolicyInput, DataOutput, one("get_policy")),
        _tool("search_knowledge", "Search current business knowledge.", KnowledgeInput, ItemsOutput, many("search_knowledge")),
        _tool("cancel_order", "Request an authoritative order cancellation.", OrderIdInput, DataOutput, one("cancel_order"), kind=ToolKind.ACTION, risk=RiskLevel.HIGH),
        _tool("request_return", "Request an authoritative line-level return.", ReturnInput, DataOutput, request_return, kind=ToolKind.WRITE, risk=RiskLevel.MEDIUM),
        _tool("request_refund", "Request an authoritative refund.", RefundInput, DataOutput, request_refund, kind=ToolKind.ACTION, risk=RiskLevel.HIGH),
        _tool("escalate_to_human", "Create a CX human handoff.", EscalationInput, EscalationOutput, escalate, kind=ToolKind.ACTION, risk=RiskLevel.MEDIUM),
    ]
    return ToolRegistry(tools)


def _tool(tool_id: str, description: str, input_model: type[BaseModel], output_model: type[BaseModel], handler: Any, *, kind: ToolKind = ToolKind.READ, risk: RiskLevel = RiskLevel.LOW) -> ToolDefinition:
    return ToolDefinition(tool_id=tool_id, version="1.0.0", description=description, input_model=input_model, output_model=output_model, handler=handler, kind=kind, risk_level=risk, owner_id="cx-platform", tags=("customer-support",), idempotency_required=kind is not ToolKind.READ)
