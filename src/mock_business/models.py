from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class CustomerSegment(StrEnum):
    STANDARD = "standard"
    PREMIUM = "premium"


class OrderStatus(StrEnum):
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class ShipmentStatus(StrEnum):
    PENDING = "pending"
    IN_TRANSIT = "in_transit"
    DELAYED = "delayed"
    LOST = "lost"
    DELIVERED = "delivered"


class RefundStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"


class Customer(BaseModel):
    model_config = ConfigDict(frozen=True)

    customer_id: str
    name: str
    email: str
    segment: CustomerSegment = CustomerSegment.STANDARD
    country: str = "NG"


class Product(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: str
    name: str
    price: Decimal = Field(ge=0)


class Order(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_id: str
    customer_id: str
    product_id: str
    amount: Decimal = Field(ge=0)
    status: OrderStatus
    created_at: datetime


class Shipment(BaseModel):
    model_config = ConfigDict(frozen=True)

    shipment_id: str
    order_id: str
    tracking_number: str
    status: ShipmentStatus
    expected_delivery_at: datetime
    last_update_at: datetime


class Refund(BaseModel):
    model_config = ConfigDict(frozen=True)

    refund_id: str
    order_id: str
    amount: Decimal = Field(gt=0)
    status: RefundStatus
    reason: str
    created_at: datetime


class Policy(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_id: str
    topic: str
    version: str
    text: str


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


class CancellationResult(BaseModel):
    order: Order
    allowed: bool
    reason: str
