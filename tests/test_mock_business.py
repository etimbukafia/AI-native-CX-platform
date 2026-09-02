from __future__ import annotations

from fastapi.testclient import TestClient

from mock_business.api import create_app


def client() -> TestClient:
    return TestClient(create_app(":memory:"))


def activate(test_client: TestClient, scenario_id: str) -> None:
    response = test_client.post(f"/scenarios/{scenario_id}/activate")
    assert response.status_code == 200


def test_scenario_catalog_has_complete_reference_cases() -> None:
    test_client = client()
    response = test_client.get("/scenarios")
    assert response.status_code == 200
    scenario_ids = {item["scenario_id"] for item in response.json()}
    assert scenario_ids == {
        "normal_delivery", "delayed_delivery", "lost_package", "duplicate_charge",
        "refund_requires_approval", "refund_denied_policy", "damaged_item", "missing_item",
        "cancellation_before_shipment", "cancellation_after_shipment", "shipping_service_outage",
    }


def test_duplicate_charge_exposes_two_captured_payments() -> None:
    test_client = client()
    activate(test_client, "duplicate_charge")
    response = test_client.get("/orders/ord_001/payments")
    assert response.status_code == 200
    payments = response.json()
    assert len(payments) == 2
    assert {item["provider_reference"] for item in payments} == {"PAY-ORIGINAL-001", "PAY-DUPLICATE-001"}


def test_refund_above_threshold_requires_approval() -> None:
    test_client = client()
    activate(test_client, "refund_requires_approval")
    response = test_client.post("/refunds", json={
        "order_id": "ord_001", "payment_id": "pay_001", "amount": "197.00",
        "reason": "Customer requested a full refund",
    })
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending_approval"
    assert body["requires_approval"] is True


def test_refund_outside_window_is_recorded_as_rejected() -> None:
    test_client = client()
    activate(test_client, "refund_denied_policy")
    response = test_client.post("/refunds", json={
        "order_id": "ord_001", "payment_id": "pay_001", "amount": "89.00",
        "reason": "Customer requested a refund",
    })
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "rejected"
    assert body["decision_reason"] == "outside_refund_window"


def test_damaged_item_identifies_only_the_affected_line() -> None:
    test_client = client()
    activate(test_client, "damaged_item")
    response = test_client.get("/orders/ord_001/issues")
    assert response.status_code == 200
    issues = response.json()
    assert len(issues) == 1
    assert issues[0]["issue_type"] == "damaged"
    assert issues[0]["line_id"] == "line_001"


def test_missing_item_identifies_the_missing_order_line() -> None:
    test_client = client()
    activate(test_client, "missing_item")
    response = test_client.get("/orders/ord_001/issues")
    assert response.status_code == 200
    issues = response.json()
    assert len(issues) == 1
    assert issues[0]["issue_type"] == "missing_item"
    assert issues[0]["line_id"] == "line_002"


def test_delivered_damaged_item_can_create_line_level_return() -> None:
    test_client = client()
    activate(test_client, "damaged_item")
    response = test_client.post("/returns", json={
        "order_id": "ord_001", "line_id": "line_001", "quantity": 1, "reason": "Item arrived damaged",
    })
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "approved"
    assert body["line_id"] == "line_001"


def test_cancellation_after_shipment_is_rejected_without_mutating_order() -> None:
    test_client = client()
    activate(test_client, "cancellation_after_shipment")
    response = test_client.post("/orders/ord_001/cancel")
    assert response.status_code == 200
    body = response.json()
    assert body["allowed"] is False
    assert body["order"]["status"] == "shipped"


def test_shipping_outage_returns_dependency_error_and_records_event() -> None:
    test_client = client()
    activate(test_client, "shipping_service_outage")
    response = test_client.get("/orders/ord_001/shipment")
    assert response.status_code == 503
    events = test_client.get("/events").json()
    assert any(item["event_type"] == "shipping.lookup_failed" for item in events)


def test_customer_history_contains_scenario_order_and_historical_order() -> None:
    test_client = client()
    activate(test_client, "delayed_delivery")
    response = test_client.get("/customers/cus_001/orders")
    assert response.status_code == 200
    order_ids = {item["order_id"] for item in response.json()}
    assert order_ids == {"ord_001", "ord_hist_001"}
