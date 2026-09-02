# Mock business architecture

The mock business is an external system from the point of view of the CX platform.

It owns business truth for customers, products, orders, shipments, refunds, and policies.

The CX platform must use the HTTP API. It must not read the mock business database directly.

## Scenarios

A scenario defines a controlled business state. It does not define a conversation script.

Scenario activation replaces the current reference data with one known state. This makes demonstrations and tests repeatable.

The first scenarios are:

- delayed delivery;
- lost package;
- refund request;
- cancellation before shipment;
- shipping service outage.

## Events

Business reads and writes create append-only events. These events show what external business actions occurred.

The event feed is intentionally simple. A later system can replace polling with webhooks or a message broker without changing business behavior.
