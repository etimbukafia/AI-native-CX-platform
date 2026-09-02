# AI-native CX Platform

This repository starts with a reference commerce business for an AI-native customer service platform.

The mock business owns business truth. The CX platform must use its API like an external business system.

## Reference business

The business model includes:

- customer accounts;
- products and order lines;
- orders;
- payments;
- shipments;
- fulfillment issues;
- returns;
- refunds;
- cancellation rules;
- policies;
- knowledge articles;
- business events.

The data is linked. A support flow can inspect a customer, order history, order lines, payments, shipment state, policy, and knowledge before it acts.

## Scenario design

A scenario changes business state. It does not script a customer conversation.

The reference scenarios are:

- normal delivery;
- delayed delivery;
- lost package;
- duplicate charge;
- refund requires approval;
- refund denied by policy;
- damaged item;
- missing item;
- cancellation before shipment;
- cancellation after shipment;
- shipping service outage.

Some scenarios include unrelated historical orders. This gives customer-service agents useful account history and prevents each test case from looking like an isolated fixture.

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn mock_business.api:app --reload
```

Open `http://127.0.0.1:8000/docs` for the API.

## Main endpoints

```text
GET  /scenarios
POST /scenarios/{scenario_id}/activate

GET  /customers/{customer_id}
GET  /customers/{customer_id}/orders

GET  /orders/{order_id}
GET  /orders/{order_id}/lines
GET  /orders/{order_id}/payments
GET  /orders/{order_id}/shipment
GET  /orders/{order_id}/issues
GET  /orders/{order_id}/returns
POST /orders/{order_id}/cancel

POST /returns
POST /refunds

GET  /policies/{topic}
GET  /knowledge?topic={topic}

GET  /events?after=0
```

The default scenario is `delayed_delivery`.

Reference identifiers are usually `cus_001` and `ord_001`.

## Event feed

Important reads and writes create append-only events.

Examples:

```text
customer.read
customer.orders_read
order.read
order.lines_read
order.payments_read
shipment.read
shipping.lookup_failed
order.fulfillment_issues_read
policy.read
knowledge.read
order.cancelled
order.cancellation_rejected
return.approved
refund.approved
refund.approval_required
refund.rejected
```

The event feed gives the future CX platform and CX Autopilot observable business activity without direct database access.
