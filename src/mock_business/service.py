from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from .database import Database
from .models import (
    ActiveScenario,
    CancellationResult,
    Customer,
    FulfillmentIssue,
    KnowledgeArticle,
    Order,
    OrderLine,
    OrderStatus,
    Payment,
    Policy,
    Refund,
    RefundRequest,
    RefundStatus,
    Return,
    ReturnRequest,
    ReturnStatus,
    ScenarioSummary,
    Shipment,
    ShipmentStatus,
)
from .scenarios import ScenarioDefinition, build_scenarios


class BusinessRuleError(ValueError):
    pass


class DependencyUnavailable(RuntimeError):
    pass


class BusinessService:
    def __init__(self, database: Database, scenarios: dict[str, ScenarioDefinition] | None = None) -> None:
        self.database = database
        self.scenarios = scenarios or build_scenarios()
        if self.database.state("active_scenario") is None:
            self.activate_scenario("delayed_delivery")

    @property
    def active_scenario_id(self) -> str:
        scenario_id = self.database.state("active_scenario")
        if scenario_id is None:
            raise RuntimeError("No active scenario")
        return scenario_id

    def list_scenarios(self) -> list[ScenarioSummary]:
        return [ScenarioSummary(scenario_id=x.scenario_id, name=x.name, description=x.description, expected_outcomes=x.expected_outcomes) for x in self.scenarios.values()]

    def activate_scenario(self, scenario_id: str) -> ActiveScenario:
        scenario = self.scenarios.get(scenario_id)
        if scenario is None:
            raise KeyError(scenario_id)
        self.database.activate(scenario)
        return ActiveScenario(scenario_id=scenario_id, activated_at=datetime.now(UTC))

    def customer(self, customer_id: str) -> Customer:
        customer = self.database.customer(customer_id)
        if customer is None:
            raise KeyError(customer_id)
        self._emit_read("customer.read", "customer", customer_id)
        return customer

    def customer_orders(self, customer_id: str) -> list[Order]:
        if self.database.customer(customer_id) is None:
            raise KeyError(customer_id)
        orders = self.database.orders_for_customer(customer_id)
        self._emit_read("customer.orders_read", "customer", customer_id, {"count": len(orders)})
        return orders

    def order(self, order_id: str) -> Order:
        order = self.database.order(order_id)
        if order is None:
            raise KeyError(order_id)
        self._emit_read("order.read", "order", order_id)
        return order

    def order_lines(self, order_id: str) -> list[OrderLine]:
        if self.database.order(order_id) is None:
            raise KeyError(order_id)
        lines = self.database.order_lines(order_id)
        self._emit_read("order.lines_read", "order", order_id, {"count": len(lines)})
        return lines

    def payments(self, order_id: str) -> list[Payment]:
        if self.database.order(order_id) is None:
            raise KeyError(order_id)
        payments = self.database.payments_for_order(order_id)
        self._emit_read("order.payments_read", "order", order_id, {"count": len(payments)})
        return payments

    def shipment(self, order_id: str) -> Shipment:
        if self.database.state("shipping") == "unavailable":
            self.database.emit("shipping.lookup_failed", self.active_scenario_id, entity_type="order", entity_id=order_id, data={"reason": "service_unavailable"})
            raise DependencyUnavailable("Shipping service is unavailable")
        shipment = self.database.shipment_for_order(order_id)
        if shipment is None:
            raise KeyError(order_id)
        self._emit_read("shipment.read", "shipment", shipment.shipment_id, {"order_id": order_id})
        return shipment

    def fulfillment_issues(self, order_id: str) -> list[FulfillmentIssue]:
        if self.database.order(order_id) is None:
            raise KeyError(order_id)
        issues = self.database.fulfillment_issues_for_order(order_id)
        self._emit_read("order.fulfillment_issues_read", "order", order_id, {"count": len(issues)})
        return issues

    def returns(self, order_id: str) -> list[Return]:
        if self.database.order(order_id) is None:
            raise KeyError(order_id)
        returns = self.database.returns_for_order(order_id)
        self._emit_read("order.returns_read", "order", order_id, {"count": len(returns)})
        return returns

    def policy(self, topic: str) -> Policy:
        policy = self.database.policy(topic)
        if policy is None:
            raise KeyError(topic)
        self._emit_read("policy.read", "policy", policy.policy_id, {"topic": topic, "version": policy.version})
        return policy

    def knowledge(self, topic: str) -> list[KnowledgeArticle]:
        articles = self.database.knowledge_for_topic(topic)
        if not articles:
            raise KeyError(topic)
        self._emit_read("knowledge.read", "knowledge_topic", topic, {"count": len(articles)})
        return articles

    def cancel_order(self, order_id: str) -> CancellationResult:
        order = self.order(order_id)
        if order.status is not OrderStatus.PROCESSING:
            self.database.emit("order.cancellation_rejected", self.active_scenario_id, entity_type="order", entity_id=order_id, data={"status": order.status.value})
            return CancellationResult(order=order, allowed=False, reason="Only processing orders can be cancelled")
        cancelled = order.model_copy(update={"status": OrderStatus.CANCELLED})
        self.database.save_order(cancelled)
        self.database.emit("order.cancelled", self.active_scenario_id, entity_type="order", entity_id=order_id)
        return CancellationResult(order=cancelled, allowed=True, reason="Order cancelled")

    def request_return(self, request: ReturnRequest) -> Return:
        order = self.order(request.order_id)
        if order.status is not OrderStatus.DELIVERED:
            raise BusinessRuleError("Only delivered orders can be returned")
        line = next((x for x in self.database.order_lines(order.order_id) if x.line_id == request.line_id), None)
        if line is None:
            raise KeyError(request.line_id)
        if request.quantity > line.quantity:
            raise BusinessRuleError("Return quantity cannot exceed purchased quantity")
        return_window = int(self.database.state("refund_window_days") or "30")
        age_days = (datetime.now(UTC) - order.created_at).days
        if age_days > return_window:
            self.database.emit("return.rejected", self.active_scenario_id, entity_type="order", entity_id=order.order_id, data={"reason": "outside_return_window", "age_days": age_days})
            raise BusinessRuleError("Order is outside the return window")
        item = Return(return_id=f"ret_{uuid4().hex[:10]}", order_id=order.order_id, line_id=line.line_id,
                      quantity=request.quantity, reason=request.reason, status=ReturnStatus.APPROVED,
                      requested_at=datetime.now(UTC))
        self.database.save_return(item)
        self.database.emit("return.approved", self.active_scenario_id, entity_type="return", entity_id=item.return_id,
                           data={"order_id": order.order_id, "line_id": line.line_id, "quantity": item.quantity})
        return item

    def request_refund(self, request: RefundRequest) -> Refund:
        order = self.order(request.order_id)
        payment = self.database.payment(request.payment_id)
        if payment is None or payment.order_id != order.order_id:
            raise KeyError(request.payment_id)
        if request.amount > payment.amount:
            self.database.emit("refund.rejected", self.active_scenario_id, entity_type="payment", entity_id=payment.payment_id,
                               data={"reason": "amount_exceeds_payment", "requested_amount": str(request.amount)})
            raise BusinessRuleError("Refund amount cannot exceed payment amount")

        is_duplicate_payment = len(self.database.payments_for_order(order.order_id)) > 1
        if not is_duplicate_payment:
            if order.status is not OrderStatus.DELIVERED:
                raise BusinessRuleError("Only delivered orders can be refunded")
            refund_window = int(self.database.state("refund_window_days") or "30")
            shipment = self.database.shipment_for_order(order.order_id)
            if shipment is None or shipment.status is not ShipmentStatus.DELIVERED:
                raise BusinessRuleError("Delivered shipment data is required for this refund")
            delivered_age_days = max(0, (datetime.now(UTC) - shipment.expected_delivery_at).days)
            if delivered_age_days > refund_window:
                refund = Refund(refund_id=f"ref_{uuid4().hex[:10]}", order_id=order.order_id, payment_id=payment.payment_id,
                                amount=Decimal(request.amount), status=RefundStatus.REJECTED, reason=request.reason,
                                created_at=datetime.now(UTC), requires_approval=False, decision_reason="outside_refund_window")
                self.database.save_refund(refund)
                self.database.emit("refund.rejected", self.active_scenario_id, entity_type="refund", entity_id=refund.refund_id,
                                   data={"order_id": order.order_id, "reason": "outside_refund_window", "delivered_age_days": delivered_age_days})
                return refund

        approval_threshold = Decimal(self.database.state("refund_approval_threshold") or "150")
        requires_approval = request.amount > approval_threshold
        status = (
            RefundStatus.PENDING_APPROVAL
            if requires_approval and not request.approval_confirmed
            else RefundStatus.APPROVED
        )
        decision_reason = (
            "harness_approval_confirmed" if request.approval_confirmed else None
        )
        refund = Refund(
            refund_id=f"ref_{uuid4().hex[:10]}",
            order_id=order.order_id,
            payment_id=payment.payment_id,
            amount=Decimal(request.amount),
            status=status,
            reason=request.reason,
            created_at=datetime.now(UTC),
            requires_approval=requires_approval,
            decision_reason=decision_reason,
        )
        self.database.save_refund(refund)
        event_type = (
            "refund.approval_required"
            if requires_approval and not request.approval_confirmed
            else "refund.approved"
        )
        self.database.emit(
            event_type,
            self.active_scenario_id,
            entity_type="refund",
            entity_id=refund.refund_id,
            data={
                "order_id": order.order_id,
                "payment_id": payment.payment_id,
                "amount": str(refund.amount),
            },
        )
        return refund

    def _emit_read(self, event_type: str, entity_type: str, entity_id: str,
                   data: dict[str, object] | None = None) -> None:
        self.database.emit(event_type, self.active_scenario_id, entity_type=entity_type, entity_id=entity_id, data=data)
