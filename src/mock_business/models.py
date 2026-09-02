from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CustomerSegment(StrEnum):
    STANDARD = "standard"
    PREMIUM = "premium"


class AccountStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class OrderStatus(StrEnum):
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class PaymentStatus(StrEnum):
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    REFUNDED = "refunded"
    FAILED = "failed"


class ShipmentStatus(StrEnum):
    PENDING = "pending"
    IN_TRANSIT = "in_transit"
    DELAYED = "delayed"
    LOST = "lost"
    DELIVERED = "delivered"


class FulfillmentIssueType(StrEnum):
    DAMAGED = "damaged"
    MISSING_ITEM = "missing_item"


class ReturnStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    RECEIVED = "received"
    REJECTED = "rejected"


class RefundStatus(StrEnum):
    REQUESTED = "requested"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"


class Customer(BaseModel):
    model_config = ConfigDict(frozen=True)

    customer_id: str
    name: str
    email: str
    segment: CustomerSegment = CustomerSegment.STANDARD
    country: str = "NG"
    account_status: AccountStatus = AccountStatus.ACTIVE
    lifetime_value: Decimal = Field(default=Decimal("0"), ge=0)
    created_at: datetime


class Product(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: str
    sku: str
    name: str
    price: Decimal = Field(ge=0)


class OrderLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    line_id: str
    order_id: str
    product_id: str
    quantity: int = Field(gt=0)
    unit_price: Decimal = Field(ge=0)


class Order(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_id: str
    customer_id: str
    amount: Decimal = Field(ge=0)
    status: OrderStatus
    created_at: datetime


class Payment(BaseModel):
    model_config = ConfigDict(frozen=True)

    payment_id: str
    order_id: str
    amount: Decimal = Field(gt=0)
    currency: str = "USD"
    status: PaymentStatus
    provider_reference: str
    captured_at: datetime | None = None


class Shipment(BaseModel):
    model_config = ConfigDict(frozen=True)

    shipment_id: str
    order_id: str
    tracking_number: str
    carrier: str
    status: ShipmentStatus
    expected_delivery_at: datetime
    last_update_at: datetime


class FulfillmentIssue(BaseModel):
    model_config = ConfigDict(frozen=True)

    issue_id: str
    order_id: str
    line_id: str
    issue_type: FulfillmentIssueType
    quantity_affected: int = Field(gt=0)
    reported_at: datetime


class Return(BaseModel):
    model_config = ConfigDict(frozen=True)

    return_id: str
    order_id: str
    line_id: str
    quantity: int = Field(gt=0)
    reason: str
    status: ReturnStatus
    requested_at: datetime


class Refund(BaseModel):
    model_config = ConfigDict(frozen=True)

    refund_id: str
    order_id: str
    payment_id: str
    amount: Decimal = Field(gt=0)
    status: RefundStatus
    reason: str
    created_at: datetime
    requires_approval: bool = False
    decision_reason: str | None = None


class Policy(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_id: str
    topic: str
    version: str
    text: str
    effective_at: datetime


class KnowledgeArticle(BaseModel):
    model_config = ConfigDict(frozen=True)

    article_id: str
    topic: str
    title: str
    body: str
    version: str
    effective_at: datetime


class BusinessEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: int
    event_type: str
    occurred_at: datetime
    scenario_id: str
    entity_type: str | None = None
    entity_id: str | None = None
    data: dict[str, object] = Field(default_factory=dict)


class ScenarioSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_id: str
    name: str
    description: str
    expected_outcomes: tuple[str, ...]


class ActiveScenario(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_id: str
    activated_at: datetime


class RefundRequest(BaseModel):
    order_id: str
    amount: Decimal = Field(gt=0)
    reason: str = Field(min_length=1)


class ReturnRequest(BaseModel):
    order_id: str
    line_id: str
    quantity: int = Field(gt=0)
    reason: str = Field(min_length=1)


class CancellationResult(BaseModel):
    order: Order
    allowed: bool
    reason: str
