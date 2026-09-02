from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from .database import Database
from .models import ActiveScenario, CancellationResult, Customer, Order, OrderStatus, Policy, Refund, RefundRequest, RefundStatus, ScenarioSummary, Shipment
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
        return [ScenarioSummary(scenario_id=item.scenario_id, name=item.name, description=item.description, expected_outcomes=item.expected_outcomes) for item in self.scenarios.values()]

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

    def shipment(self, order_id: str) -> Shipment:
        if self.database.state("shipping") == "unavailable":
            self.database.emit("shipping.lookup_failed", self.active_scenario_id, entity_type="order", entity_id=order_id, data={"reason": "service_unavailable"})
            raise DependencyUnavailable("Shipping service is unavailable")
        shipment = self.database.shipment_for_order(order_id)
        if shipment is None:
            raise KeyError(order_id)
        self._emit_read("shipment.read", "shipment", shipment.shipment_id, {"order_id": order_id})
        return shipment

    def policy(self, topic: str) -> Policy:
        policy = self.database.policy(topic)
        if policy is None:
            raise KeyError(topic)
        self._emit_read("policy.read", "policy", policy.policy_id, {"topic": topic, "version": policy.version})
        return policy

    def cancel_order(self, order_id: str) -> CancellationResult:
        order = self.order(order_id)
        if order.status is not OrderStatus.PROCESSING:
            self.database.emit("order.cancellation_rejected", self.active_scenario_id, entity_type="order", entity_id=order_id, data={"status": order.status.value})
            return CancellationResult(order=order, allowed=False, reason="Only processing orders can be cancelled")
        cancelled = order.model_copy(update={"status": OrderStatus.CANCELLED})
        self.database.save_order(cancelled)
        self.database.emit("order.cancelled", self.active_scenario_id, entity_type="order", entity_id=order_id)
        return CancellationResult(order=cancelled, allowed=True, reason="Order cancelled")

    def request_refund(self, request: RefundRequest) -> Refund:
        order = self.order(request.order_id)
        if request.amount > order.amount:
            self.database.emit("refund.rejected", self.active_scenario_id, entity_type="order", entity_id=order.order_id, data={"reason": "amount_exceeds_order", "requested_amount": str(request.amount)})
            raise BusinessRuleError("Refund amount cannot exceed order amount")
        refund = Refund(refund_id=f"ref_{uuid4().hex[:10]}", order_id=order.order_id, amount=Decimal(request.amount), status=RefundStatus.APPROVED, reason=request.reason, created_at=datetime.now(UTC))
        self.database.save_refund(refund)
        self.database.emit("refund.approved", self.active_scenario_id, entity_type="refund", entity_id=refund.refund_id, data={"order_id": order.order_id, "amount": str(refund.amount)})
        return refund

    def _emit_read(self, event_type: str, entity_type: str, entity_id: str, data: dict[str, object] | None = None) -> None:
        self.database.emit(event_type, self.active_scenario_id, entity_type=entity_type, entity_id=entity_id, data=data)
