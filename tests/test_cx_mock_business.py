import httpx
import pytest
from fastapi.testclient import TestClient

from cx_platform.integrations.mock_business import BusinessRuleRejected, MockBusinessClient, ResourceNotFound, ServiceUnavailable, TransportFailure
from mock_business.api import create_app


def test_adapter_preserves_business_ids_and_maps_authoritative_errors() -> None:
    api = TestClient(create_app(":memory:"))
    client = MockBusinessClient("http://testserver", client=api)
    assert client.get_order("ord_001").order_id == "ord_001"
    with pytest.raises(ResourceNotFound): client.get_order("missing")
    api.post("/scenarios/shipping_service_outage/activate")
    with pytest.raises(ServiceUnavailable): client.get_shipment("ord_001")


def test_adapter_maps_business_rule_and_transport_failures() -> None:
    api = TestClient(create_app(":memory:"))
    client = MockBusinessClient("http://testserver", client=api)
    api.post("/scenarios/damaged_item/activate")
    from cx_platform.integrations.mock_business import ReturnRequest
    with pytest.raises(BusinessRuleRejected): client.request_return(ReturnRequest(order_id="ord_001", line_id="line_001", quantity=9, reason="Damaged"))
    unavailable = MockBusinessClient("http://testserver", client=httpx.Client(transport=httpx.MockTransport(lambda _: (_ for _ in ()).throw(httpx.ConnectError("down")))))
    with pytest.raises(TransportFailure): unavailable.get_order("ord_001")
