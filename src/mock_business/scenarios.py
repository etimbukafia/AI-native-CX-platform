from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from .models import (
    Customer,
    CustomerSegment,
    FulfillmentIssue,
    FulfillmentIssueType,
    KnowledgeArticle,
    Order,
    OrderLine,
    OrderStatus,
    Payment,
    PaymentStatus,
    Policy,
    Product,
    Return,
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
    order_lines: tuple[OrderLine, ...]
    payments: tuple[Payment, ...]
    shipments: tuple[Shipment, ...]
    fulfillment_issues: tuple[FulfillmentIssue, ...]
    returns: tuple[Return, ...]
    policies: tuple[Policy, ...]
    knowledge_articles: tuple[KnowledgeArticle, ...]
    service_state: dict[str, str]


def build_scenarios(now: datetime | None = None) -> dict[str, ScenarioDefinition]:
    now = now or datetime.now(UTC)

    ada = Customer(
        customer_id="cus_001",
        name="Ada Okafor",
        email="ada@example.test",
        segment=CustomerSegment.PREMIUM,
        country="NG",
        lifetime_value=Decimal("1280.40"),
        created_at=now - timedelta(days=640),
    )
    david = Customer(
        customer_id="cus_002",
        name="David Mensah",
        email="david@example.test",
        segment=CustomerSegment.STANDARD,
        country="GH",
        lifetime_value=Decimal("246.50"),
        created_at=now - timedelta(days=190),
    )

    headphones = Product(
        product_id="prd_001",
        sku="AUD-WH-100",
        name="Wireless Headphones",
        price=Decimal("89.00"),
    )
    charger = Product(
        product_id="prd_002",
        sku="PWR-USBC-65",
        name="65W USB-C Charger",
        price=Decimal("39.00"),
    )
    case = Product(
        product_id="prd_003",
        sku="ACC-CASE-01",
        name="Travel Case",
        price=Decimal("19.00"),
    )

    policies = (
        Policy(
            policy_id="pol_delivery_2",
            topic="delivery",
            version="2.0",
            text="A lost shipment can be replaced or refunded. A delayed shipment is eligible for replacement after five full days.",
            effective_at=now - timedelta(days=120),
        ),
        Policy(
            policy_id="pol_refund_3",
            topic="refund",
            version="3.0",
            text="Delivered orders can be refunded within 30 days. Refunds above 150 USD require approval.",
            effective_at=now - timedelta(days=90),
        ),
        Policy(
            policy_id="pol_return_2",
            topic="return",
            version="2.0",
            text="Delivered items can be returned within 30 days. Damaged items can be returned without return shipping cost.",
            effective_at=now - timedelta(days=75),
        ),
        Policy(
            policy_id="pol_cancel_1",
            topic="cancellation",
            version="1.0",
            text="An order can be cancelled only while it is processing.",
            effective_at=now - timedelta(days=180),
        ),
        Policy(
            policy_id="pol_payment_1",
            topic="payment",
            version="1.0",
            text="A confirmed duplicate charge must be refunded to the duplicated payment method.",
            effective_at=now - timedelta(days=140),
        ),
        Policy(
            policy_id="pol_missing_1",
            topic="missing_item",
            version="1.0",
            text="A confirmed missing line can be reshipped or refunded for the missing line amount.",
            effective_at=now - timedelta(days=60),
        ),
    )

    knowledge = (
        KnowledgeArticle(
            article_id="kb_delivery_1",
            topic="delivery",
            title="Delivery delay and lost shipment guide",
            body="Check the carrier state first. Do not promise a replacement before the five-day delay threshold unless the carrier marks the shipment lost.",
            version="1.2",
            effective_at=now - timedelta(days=45),
        ),
        KnowledgeArticle(
            article_id="kb_refund_1",
            topic="refund",
            title="Refund handling guide",
            body="Check delivery date, payment, requested amount, and approval threshold before a refund decision.",
            version="1.1",
            effective_at=now - timedelta(days=45),
        ),
        KnowledgeArticle(
            article_id="kb_damage_1",
            topic="damaged_item",
            title="Damaged item guide",
            body="Confirm the affected order line and quantity. Create a return when the item is within the return window.",
            version="1.0",
            effective_at=now - timedelta(days=30),
        ),
        KnowledgeArticle(
            article_id="kb_missing_1",
            topic="missing_item",
            title="Missing item guide",
            body="Confirm the missing line. Offer reshipment or a line-level refund when the fulfillment issue is confirmed.",
            version="1.0",
            effective_at=now - timedelta(days=30),
        ),
        KnowledgeArticle(
            article_id="kb_cancel_1",
            topic="cancellation",
            title="Order cancellation guide",
            body="Cancel only processing orders. Shipped orders must use return or delivery resolution flows.",
            version="1.0",
            effective_at=now - timedelta(days=30),
        ),
    )

    def order(order_id: str, customer_id: str, amount: Decimal, status: OrderStatus, age_days: int) -> Order:
        return Order(order_id=order_id, customer_id=customer_id, amount=amount, status=status, created_at=now - timedelta(days=age_days))

    def line(line_id: str, order_id: str, product: Product, quantity: int = 1) -> OrderLine:
        return OrderLine(line_id=line_id, order_id=order_id, product_id=product.product_id, quantity=quantity, unit_price=product.price)

    def payment(payment_id: str, order_id: str, amount: Decimal, ref: str, age_days: int) -> Payment:
        return Payment(payment_id=payment_id, order_id=order_id, amount=amount, status=PaymentStatus.CAPTURED, provider_reference=ref, captured_at=now - timedelta(days=age_days))

    def shipment(shipment_id: str, order_id: str, status: ShipmentStatus, due_days: int, update_hours: int = 8) -> Shipment:
        return Shipment(shipment_id=shipment_id, order_id=order_id, tracking_number=f"TRK-{shipment_id.upper()}", carrier="ParcelBridge", status=status, expected_delivery_at=now + timedelta(days=due_days), last_update_at=now - timedelta(hours=update_hours))

    history_order = order("ord_hist_001", ada.customer_id, Decimal("39.00"), OrderStatus.DELIVERED, 70)
    history_line = line("line_hist_001", history_order.order_id, charger)
    history_payment = payment("pay_hist_001", history_order.order_id, Decimal("39.00"), "PAY-HIST-001", 70)
    history_shipment = shipment("shp_hist_001", history_order.order_id, ShipmentStatus.DELIVERED, -67, 24)

    common = {
        "customers": (ada, david),
        "products": (headphones, charger, case),
        "policies": policies,
        "knowledge_articles": knowledge,
        "returns": (),
    }

    scenarios: list[ScenarioDefinition] = []

    normal_order = order("ord_001", ada.customer_id, Decimal("89.00"), OrderStatus.SHIPPED, 3)
    scenarios.append(ScenarioDefinition(scenario_id="normal_delivery", name="Normal delivery", description="The order is in transit and remains inside the promised delivery window.", expected_outcomes=("report_in_transit", "do_not_escalate", "do_not_refund"), orders=(normal_order, history_order), order_lines=(line("line_001", "ord_001", headphones), history_line), payments=(payment("pay_001", "ord_001", Decimal("89.00"), "PAY-001", 3), history_payment), shipments=(shipment("shp_001", "ord_001", ShipmentStatus.IN_TRANSIT, 2), history_shipment), fulfillment_issues=(), service_state={"shipping": "available", "refund_window_days": "30", "refund_approval_threshold": "150"}, **common))

    delayed_order = order("ord_001", ada.customer_id, Decimal("89.00"), OrderStatus.SHIPPED, 7)
    scenarios.append(ScenarioDefinition(scenario_id="delayed_delivery", name="Delayed delivery", description="The shipment is two days late. The five-day replacement threshold has not been reached.", expected_outcomes=("explain_delay", "do_not_replace_yet", "do_not_invent_eta"), orders=(delayed_order, history_order), order_lines=(line("line_001", "ord_001", headphones), history_line), payments=(payment("pay_001", "ord_001", Decimal("89.00"), "PAY-001", 7), history_payment), shipments=(shipment("shp_001", "ord_001", ShipmentStatus.DELAYED, -2), history_shipment), fulfillment_issues=(), service_state={"shipping": "available", "refund_window_days": "30", "refund_approval_threshold": "150"}, **common))

    lost_order = order("ord_001", ada.customer_id, Decimal("89.00"), OrderStatus.SHIPPED, 11)
    scenarios.append(ScenarioDefinition(scenario_id="lost_package", name="Lost package", description="The carrier marked the shipment lost after the expected delivery date.", expected_outcomes=("offer_replacement_or_refund", "do_not_claim_delivery"), orders=(lost_order, history_order), order_lines=(line("line_001", "ord_001", headphones), history_line), payments=(payment("pay_001", "ord_001", Decimal("89.00"), "PAY-001", 11), history_payment), shipments=(shipment("shp_001", "ord_001", ShipmentStatus.LOST, -6), history_shipment), fulfillment_issues=(), service_state={"shipping": "available", "refund_window_days": "30", "refund_approval_threshold": "150"}, **common))

    duplicate_order = order("ord_001", david.customer_id, Decimal("89.00"), OrderStatus.SHIPPED, 4)
    scenarios.append(ScenarioDefinition(scenario_id="duplicate_charge", name="Duplicate charge", description="The same order has two captured payments for the full order amount.", expected_outcomes=("identify_duplicate_payment", "refund_duplicate_payment_only"), orders=(duplicate_order,), order_lines=(line("line_001", "ord_001", headphones),), payments=(payment("pay_001", "ord_001", Decimal("89.00"), "PAY-ORIGINAL-001", 4), payment("pay_002", "ord_001", Decimal("89.00"), "PAY-DUPLICATE-001", 4)), shipments=(shipment("shp_001", "ord_001", ShipmentStatus.IN_TRANSIT, 1),), fulfillment_issues=(), service_state={"shipping": "available", "refund_window_days": "30", "refund_approval_threshold": "150"}, **common))

    approval_order = order("ord_001", ada.customer_id, Decimal("197.00"), OrderStatus.DELIVERED, 9)
    scenarios.append(ScenarioDefinition(scenario_id="refund_requires_approval", name="Refund requires approval", description="A delivered order is inside the refund window, but the refund amount exceeds the approval threshold.", expected_outcomes=("request_refund_approval", "do_not_mark_refund_complete"), orders=(approval_order, history_order), order_lines=(OrderLine(line_id="line_001", order_id="ord_001", product_id=headphones.product_id, quantity=2, unit_price=headphones.price), line("line_002", "ord_001", case), history_line), payments=(payment("pay_001", "ord_001", Decimal("197.00"), "PAY-001", 9), history_payment), shipments=(shipment("shp_001", "ord_001", ShipmentStatus.DELIVERED, -5), history_shipment), fulfillment_issues=(), service_state={"shipping": "available", "refund_window_days": "30", "refund_approval_threshold": "150"}, **common))

    denied_order = order("ord_001", david.customer_id, Decimal("89.00"), OrderStatus.DELIVERED, 52)
    scenarios.append(ScenarioDefinition(scenario_id="refund_denied_policy", name="Refund denied by policy", description="The order was delivered more than 30 days ago and is outside the refund window.", expected_outcomes=("deny_refund_by_policy", "explain_refund_window"), orders=(denied_order,), order_lines=(line("line_001", "ord_001", headphones),), payments=(payment("pay_001", "ord_001", Decimal("89.00"), "PAY-001", 52),), shipments=(shipment("shp_001", "ord_001", ShipmentStatus.DELIVERED, -48),), fulfillment_issues=(), service_state={"shipping": "available", "refund_window_days": "30", "refund_approval_threshold": "150"}, **common))

    damaged_order = order("ord_001", ada.customer_id, Decimal("108.00"), OrderStatus.DELIVERED, 6)
    scenarios.append(ScenarioDefinition(scenario_id="damaged_item", name="Damaged item", description="One delivered headphone unit is confirmed damaged. A travel case in the same order is unaffected.", expected_outcomes=("identify_damaged_line", "allow_return_for_damaged_line", "do_not_return_unaffected_line"), orders=(damaged_order, history_order), order_lines=(line("line_001", "ord_001", headphones), line("line_002", "ord_001", case), history_line), payments=(payment("pay_001", "ord_001", Decimal("108.00"), "PAY-001", 6), history_payment), shipments=(shipment("shp_001", "ord_001", ShipmentStatus.DELIVERED, -2), history_shipment), fulfillment_issues=(FulfillmentIssue(issue_id="issue_001", order_id="ord_001", line_id="line_001", issue_type=FulfillmentIssueType.DAMAGED, quantity_affected=1, reported_at=now - timedelta(hours=6)),), service_state={"shipping": "available", "refund_window_days": "30", "refund_approval_threshold": "150"}, **common))

    missing_order = order("ord_001", david.customer_id, Decimal("147.00"), OrderStatus.DELIVERED, 5)
    scenarios.append(ScenarioDefinition(scenario_id="missing_item", name="Missing item", description="The parcel was delivered, but the charger line is confirmed missing while the headphones arrived.", expected_outcomes=("identify_missing_line", "offer_reshipment_or_line_refund", "do_not_refund_received_line"), orders=(missing_order,), order_lines=(line("line_001", "ord_001", headphones), OrderLine(line_id="line_002", order_id="ord_001", product_id=charger.product_id, quantity=1, unit_price=charger.price), line("line_003", "ord_001", case)), payments=(payment("pay_001", "ord_001", Decimal("147.00"), "PAY-001", 5),), shipments=(shipment("shp_001", "ord_001", ShipmentStatus.DELIVERED, -1),), fulfillment_issues=(FulfillmentIssue(issue_id="issue_001", order_id="ord_001", line_id="line_002", issue_type=FulfillmentIssueType.MISSING_ITEM, quantity_affected=1, reported_at=now - timedelta(hours=3)),), service_state={"shipping": "available", "refund_window_days": "30", "refund_approval_threshold": "150"}, **common))

    cancel_order = order("ord_001", ada.customer_id, Decimal("89.00"), OrderStatus.PROCESSING, 1)
    scenarios.append(ScenarioDefinition(scenario_id="cancellation_before_shipment", name="Cancellation before shipment", description="The order is still processing and can be cancelled.", expected_outcomes=("allow_cancellation", "set_order_cancelled"), orders=(cancel_order, history_order), order_lines=(line("line_001", "ord_001", headphones), history_line), payments=(payment("pay_001", "ord_001", Decimal("89.00"), "PAY-001", 1), history_payment), shipments=(history_shipment,), fulfillment_issues=(), service_state={"shipping": "available", "refund_window_days": "30", "refund_approval_threshold": "150"}, **common))

    shipped_cancel_order = order("ord_001", ada.customer_id, Decimal("89.00"), OrderStatus.SHIPPED, 3)
    scenarios.append(ScenarioDefinition(scenario_id="cancellation_after_shipment", name="Cancellation after shipment", description="The order has already shipped, so cancellation is no longer allowed.", expected_outcomes=("reject_cancellation", "direct_to_delivery_or_return_flow"), orders=(shipped_cancel_order, history_order), order_lines=(line("line_001", "ord_001", headphones), history_line), payments=(payment("pay_001", "ord_001", Decimal("89.00"), "PAY-001", 3), history_payment), shipments=(shipment("shp_001", "ord_001", ShipmentStatus.IN_TRANSIT, 2), history_shipment), fulfillment_issues=(), service_state={"shipping": "available", "refund_window_days": "30", "refund_approval_threshold": "150"}, **common))

    outage_order = order("ord_001", ada.customer_id, Decimal("89.00"), OrderStatus.SHIPPED, 4)
    scenarios.append(ScenarioDefinition(scenario_id="shipping_service_outage", name="Shipping service outage", description="Order data is available, but the shipping dependency is unavailable.", expected_outcomes=("report_dependency_failure", "do_not_invent_tracking_state"), orders=(outage_order, history_order), order_lines=(line("line_001", "ord_001", headphones), history_line), payments=(payment("pay_001", "ord_001", Decimal("89.00"), "PAY-001", 4), history_payment), shipments=(shipment("shp_001", "ord_001", ShipmentStatus.IN_TRANSIT, 1), history_shipment), fulfillment_issues=(), service_state={"shipping": "unavailable", "refund_window_days": "30", "refund_approval_threshold": "150"}, **common))

    return {scenario.scenario_id: scenario for scenario in scenarios}
