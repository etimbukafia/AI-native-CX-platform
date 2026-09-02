"""Typed HTTP boundary for the reference mock-business API."""

from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class MockBusinessError(RuntimeError):
    pass


class ResourceNotFound(MockBusinessError):
    pass


class BusinessRuleRejected(MockBusinessError):
    pass


class ServiceUnavailable(MockBusinessError):
    pass


class TransportFailure(MockBusinessError):
    pass


class BusinessModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Customer(BusinessModel):
    customer_id: str
    name: str
    email: str
    segment: str
    country: str
    account_status: str
    lifetime_value: Decimal
    created_at: datetime


class Order(BusinessModel):
    order_id: str
    customer_id: str
    amount: Decimal
    status: str
    created_at: datetime


class OrderLine(BusinessModel):
    line_id: str
    order_id: str
    product_id: str
    quantity: int
    unit_price: Decimal


class Payment(BusinessModel):
    payment_id: str
    order_id: str
    amount: Decimal
    currency: str
    status: str
    provider_reference: str
    captured_at: datetime | None = None


class Shipment(BusinessModel):
    shipment_id: str
    order_id: str
    tracking_number: str
    carrier: str
    status: str
    expected_delivery_at: datetime
    last_update_at: datetime


class FulfillmentIssue(BusinessModel):
    issue_id: str
    order_id: str
    line_id: str
    issue_type: str
    quantity_affected: int
    reported_at: datetime


class Return(BusinessModel):
    return_id: str
    order_id: str
    line_id: str
    quantity: int
    reason: str
    status: str
    requested_at: datetime


class Policy(BusinessModel):
    policy_id: str
    topic: str
    version: str
    text: str
    effective_at: datetime


class KnowledgeArticle(BusinessModel):
    article_id: str
    topic: str
    title: str
    body: str
    version: str
    effective_at: datetime


class CancellationResult(BusinessModel):
    order: Order
    allowed: bool
    reason: str


class Refund(BusinessModel):
    refund_id: str
    order_id: str
    payment_id: str
    amount: Decimal
    status: str
    reason: str
    created_at: datetime
    requires_approval: bool
    decision_reason: str | None = None


class ReturnRequest(BusinessModel):
    order_id: str
    line_id: str
    quantity: int = Field(gt=0)
    reason: str = Field(min_length=1)


class RefundRequest(BusinessModel):
    order_id: str
    payment_id: str
    amount: Decimal = Field(gt=0)
    reason: str = Field(min_length=1)


class MockBusinessClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 5.0,
        client: httpx.Client | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.client = client or httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds),
        )

    @classmethod
    def from_environment(cls) -> "MockBusinessClient":
        base_url = os.getenv("MOCK_BUSINESS_BASE_URL", "http://127.0.0.1:8000")
        timeout = float(os.getenv("MOCK_BUSINESS_TIMEOUT_SECONDS", "5"))
        return cls(base_url, timeout_seconds=timeout)

    def get_customer(self, customer_id: str) -> Customer:
        return self._get(f"/customers/{customer_id}", Customer)

    def get_customer_orders(self, customer_id: str) -> list[Order]:
        return self._get_list(f"/customers/{customer_id}/orders", Order)

    def get_order(self, order_id: str) -> Order:
        return self._get(f"/orders/{order_id}", Order)

    def get_order_lines(self, order_id: str) -> list[OrderLine]:
        return self._get_list(f"/orders/{order_id}/lines", OrderLine)

    def get_order_payments(self, order_id: str) -> list[Payment]:
        return self._get_list(f"/orders/{order_id}/payments", Payment)

    def get_shipment(self, order_id: str) -> Shipment:
        return self._get(f"/orders/{order_id}/shipment", Shipment)

    def get_fulfillment_issues(self, order_id: str) -> list[FulfillmentIssue]:
        return self._get_list(f"/orders/{order_id}/issues", FulfillmentIssue)

    def get_returns(self, order_id: str) -> list[Return]:
        return self._get_list(f"/orders/{order_id}/returns", Return)

    def get_policy(self, topic: str) -> Policy:
        return self._get(f"/policies/{topic}", Policy)

    def search_knowledge(self, topic: str) -> list[KnowledgeArticle]:
        return self._get_list("/knowledge", KnowledgeArticle, params={"topic": topic})

    def cancel_order(self, order_id: str) -> CancellationResult:
        return self._request("POST", f"/orders/{order_id}/cancel", CancellationResult)

    def request_return(self, request: ReturnRequest) -> Return:
        return self._request(
            "POST",
            "/returns",
            Return,
            json=request.model_dump(mode="json"),
        )

    def request_refund(self, request: RefundRequest) -> Refund:
        return self._request(
            "POST",
            "/refunds",
            Refund,
            json=request.model_dump(mode="json"),
        )

    def _get(self, path: str, model: type[BusinessModel]) -> Any:
        return self._request("GET", path, model)

    def _get_list(self, path: str, model: type[BusinessModel], **kwargs: object) -> Any:
        return self._request("GET", path, list[model], **kwargs)

    def _request(self, method: str, path: str, model: object, **kwargs: object) -> Any:
        try:
            response = self.client.request(method, path, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TransportFailure("Mock-business transport failed") from exc

        if response.status_code == 404:
            raise ResourceNotFound(self._detail(response))
        if response.status_code == 422:
            raise BusinessRuleRejected(self._detail(response))
        if response.status_code == 503:
            raise ServiceUnavailable(self._detail(response))

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise MockBusinessError(self._detail(response)) from exc

        return TypeAdapter(model).validate_python(response.json())

    @staticmethod
    def _detail(response: httpx.Response) -> str:
        try:
            return str(response.json().get("detail", "Mock-business request failed"))
        except ValueError:
            return "Mock-business request failed"
