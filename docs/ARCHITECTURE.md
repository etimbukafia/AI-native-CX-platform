# Mock business architecture

The mock business is an external system from the point of view of the CX platform.

It owns business truth for customer accounts, products, orders, order lines, payments, shipments, fulfillment issues, returns, refunds, policies, and knowledge.

The CX platform must use the HTTP API. It must not read the mock business database directly.

## Data quality rules

Reference data must keep valid relationships between customers, orders, lines, payments, shipments, issues, returns, and refunds.

A scenario must represent a possible business state. It must not rely on conversation text to make its state understandable.

Expected outcomes describe the correct business result. They do not prescribe customer wording or agent wording.

Historical records can be present when they help the support flow reason about account context.

## Scenarios

Scenario activation replaces the current reference business state with one known state.

This makes demonstrations and evaluation repeatable.

The initial scenario catalog covers normal delivery, delayed delivery, lost packages, duplicate charges, refund approval, refund denial, damaged items, missing items, cancellation boundaries, and a shipping dependency outage.

## Policies and knowledge

Policies define business constraints.

Knowledge articles explain operational handling.

They are separate because a support agent can have correct policy data but poor operational guidance, or the reverse.

## Events

Business reads and writes create append-only events.

Events record observable business activity. They do not contain hidden CX Autopilot logic.

The current event feed uses polling. A later adapter can replace polling with a webhook or message broker without changing the business domain.
