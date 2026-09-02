from fastapi.testclient import TestClient

from mock_business.api import create_app


def client() -> TestClient:
    return TestClient(create_app(":memory:"))


def test_delayed_delivery_exposes_business_truth_and_events() -> None:
    api = client()
    shipment = api.get("/orders/ord_001/shipment")
    policy = api.get("/policies/delivery")
    events = api.get("/events")
    assert shipment.status_code == 200
    assert shipment.json()["status"] == "delayed"
    assert "five full days" in policy.json()["text"]
    event_types = [event["event_type"] for event in events.json()]
    assert "shipment.read" in event_types
    assert "policy.read" in event_types


def test_scenario_activation_replaces_business_state() -> None:
    api = client()
    response = api.post("/scenarios/cancellation_before_shipment/activate")
    order = api.get("/orders/ord_001")
    cancellation = api.post("/orders/ord_001/cancel")
    assert response.status_code == 200
    assert order.json()["status"] == "processing"
    assert cancellation.json()["allowed"] is True
    assert cancellation.json()["order"]["status"] == "cancelled"


def test_shipping_outage_returns_dependency_failure_without_fake_state() -> None:
    api = client()
    api.post("/scenarios/shipping_service_outage/activate")
    response = api.get("/orders/ord_001/shipment")
    events = api.get("/events")
    assert response.status_code == 503
    assert response.json()["detail"] == "Shipping service is unavailable"
    assert any(event["event_type"] == "shipping.lookup_failed" for event in events.json())


def test_refund_cannot_exceed_paid_amount() -> None:
    api = client()
    api.post("/scenarios/refund_requires_approval/activate")
    rejected = api.post("/refunds", json={"order_id": "ord_001", "payment_id": "pay_001", "amount": "200.00", "reason": "Damaged item"})
    approved = api.post("/refunds", json={"order_id": "ord_001", "payment_id": "pay_001", "amount": "50.00", "reason": "Damaged item"})
    assert rejected.status_code == 422
    assert approved.status_code == 201
    assert approved.json()["status"] == "approved"
