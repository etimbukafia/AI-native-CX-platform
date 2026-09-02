from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from .models import (
    Customer,
    CustomerSegment,
    Order,
    OrderStatus,
    Policy,
    Product,
    Shipment,
    ShipmentStatus,
)


@dataclass(frozen=True)
class ScenarioDefinition:
    scenario_id: str
    name: str
    description: str
    expected_outcomes: tuple[str, ...]
    customers: tuple[Customer, ...]
    products: tuple[Product, ...]
    orders: tuple[Order, ...]
    shipments: tuple[Shipment, ...]
    policies: tuple[Policy, ...]
    service_state: dict[str, str]


def _base(now: datetime) -> tuple[Customer, Product, list[Policy]]:
    customer = Customer(
        customer_id="cus_001",
        name="Ada Okafor",
        email="ada@example.test",
        segment=CustomerSegment.PREMIUM,
    )
    product = Product(product_id="prd_001", name="Wireless Headphones", price=Decimal("89.00"))
    policies = [
        Policy(
            policy_id="pol_delivery_1",
            topic="delivery",
            version="1.0",
            text="A replacement is allowed after five full days of delivery delay.",
        ),
        Policy(
            policy_id="pol_refund_1",
            topic="refund",
            version="1.0",
            text="A refund cannot exceed the paid order amount.",
        ),
        Policy(
            policy_id="pol_cancel_1",
            topic="cancellation",
            version="1.0",
            text="An order can be cancelled only while it is processing.",
        ),
    ]
    return customer, product, policies


def build_scenarios(now: datetime | None = None) -> dict[str, ScenarioDefinition]:
    now = now or datetime.now(UTC)
    customer, product, policies = _base(now)

    def order(status: OrderStatus, *, age_days: int = 6) -> Order:
        return Order(
            order_id="ord_001",
            customer_id=customer.customer_id,
            product_id=product.product_id,
            amount=product.price,
            status=status,
            created_at=now - timedelta(days=age_days),
        )

    def shipment(status: ShipmentStatus, *, due_days_ago: int) -> Shipment:
        return Shipment(
            shipment_id="shp_001",
            order_id="ord_001",
            tracking_number="TRK000001",
            status=status,
            expected_delivery_at=now - timedelta(days=due_days_ago),
            last_update_at=now - timedelta(hours=8),
        )

    scenarios = (
        ScenarioDefinition(
            scenario_id="delayed_delivery",
            name="Delayed delivery",
            description="The shipment is two days late. Replacement is not allowed yet.",
            expected_outcomes=("explain_delay", "do_not_replace_yet"),
            customers=(customer,),
            products=(product,),
            orders=(order(OrderStatus.SHIPPED),),
            shipments=(shipment(ShipmentStatus.DELAYED, due_days_ago=2),),
            policies=tuple(policies),
            service_state={"shipping": "available"},
        ),
        ScenarioDefinition(
            scenario_id="lost_package",
            name="Lost package",
            description="The carrier marked the shipment as lost after the replacement threshold.",
            expected_outcomes=("offer_replacement_or_refund",),
            customers=(customer,),
            products=(product,),
            orders=(order(OrderStatus.SHIPPED, age_days=10),),
            shipments=(shipment(ShipmentStatus.LOST, due_days_ago=6),),
            policies=tuple(policies),
            service_state={"shipping": "available"},
        ),
        ScenarioDefinition(
            scenario_id="refund_request",
            name="Refund request",
            description="A delivered order is eligible for a refund up to the order amount.",
            expected_outcomes=("refund_within_order_amount",),
            customers=(customer,),
            products=(product,),
            orders=(order(OrderStatus.DELIVERED, age_days=8),),
            shipments=(shipment(ShipmentStatus.DELIVERED, due_days_ago=3),),
            policies=tuple(policies),
            service_state={"shipping": "available"},
        ),
        ScenarioDefinition(
            scenario_id="cancellation",
            name="Cancellation before shipment",
            description="The order is still processing and can be cancelled.",
            expected_outcomes=("allow_cancellation",),
            customers=(customer,),
            products=(product,),
            orders=(order(OrderStatus.PROCESSING, age_days=1),),
            shipments=(),
            policies=tuple(policies),
            service_state={"shipping": "available"},
        ),
        ScenarioDefinition(
            scenario_id="shipping_service_outage",
            name="Shipping service outage",
            description="Shipping data is temporarily unavailable although the order exists.",
            expected_outcomes=("report_dependency_failure", "do_not_invent_tracking_state"),
            customers=(customer,),
            products=(product,),
            orders=(order(OrderStatus.SHIPPED),),
            shipments=(shipment(ShipmentStatus.IN_TRANSIT, due_days_ago=0),),
            policies=tuple(policies),
            service_state={"shipping": "unavailable"},
        ),
    )
    return {item.scenario_id: item for item in scenarios}
