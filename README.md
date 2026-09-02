# AI-native CX Platform

This repository starts with a small reference commerce business for an AI-native customer service platform.

The mock business owns business truth. The CX platform will use its API like any external business system.

## Current scope

The backend includes customers, products, orders, shipments, refunds, policies, scenarios, and business events.

Scenarios create repeatable business situations. They do not script customer conversations.

Included scenarios:

- delayed delivery;
- lost package;
- refund request;
- cancellation before shipment;
- shipping service outage.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn mock_business.api:app --reload
```

Open `http://127.0.0.1:8000/docs` for the API.

## Useful endpoints

```text
GET  /scenarios
POST /scenarios/{scenario_id}/activate
GET  /customers/{customer_id}
GET  /customers/{customer_id}/orders
GET  /orders/{order_id}
GET  /orders/{order_id}/shipment
POST /orders/{order_id}/cancel
POST /refunds
GET  /policies/{topic}
GET  /events?after=0
```

The default scenario is `delayed_delivery`.

Reference identifiers are `cus_001` and `ord_001`.
