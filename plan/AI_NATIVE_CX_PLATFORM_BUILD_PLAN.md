# AI-native CX Platform Backend Build Plan

Status: active backend implementation plan

## 1. Product goal

Build a small AI-native customer service backend where a customer request can be handled by a governed AI support agent against a realistic commerce business.

The backend must preserve a complete support evidence chain:

```text
customer request
  -> CX conversation and ticket
  -> governed AI support agent
  -> governed tools
  -> mock business
  -> action, approval, or escalation
  -> CX outcome
  -> operational evidence
```

This repository is backend-only for v0.1.

Frontend work is outside this plan.

The most important quality is trustworthy operational data. The system must preserve clear ownership, correlation, evidence, and controlled business actions.

## 2. System boundaries

Three boundaries must stay separate.

### AI-native CX platform backend

Owns:

- customer bindings;
- conversations;
- tickets;
- messages;
- customer-service outcomes;
- escalation records;
- CX-side approval references and operator decision endpoints;
- CSAT;
- CX operational events;
- CX execution references;
- links between CX records, agent executions, memory evidence, and business activity;
- backend read/export APIs.

The CX backend does not own a general-purpose agent runtime.

### Reference mock business

Owns:

- customer account truth;
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

The CX platform must use the mock business through its HTTP API. It must not read the mock-business database directly.

### Enterprise agent runtime

Use https://github.com/etimbukafia/enterprise-agent-harness for the support-agent runtime.

That repository owns generic agent concerns such as:

- governed execution;
- provider boundaries;
- typed tools;
- tool registries;
- skill registries;
- permission and policy enforcement;
- approval gates;
- agent state;
- bounded memory;
- trace and audit evidence;
- agent factory and versioned configuration.

The CX platform must consume that runtime. It must not create a second general-purpose agent runtime.

## 3. Core data distinction

The implementation must preserve four different concepts.

### Workflow state

Temporary facts for the active support case.

Examples:

- active intent;
- active order ID;
- active order-line ID;
- customer requested resolution;
- waiting for approval.

Use the state boundary from https://github.com/etimbukafia/enterprise-agent-harness.

### Agent memory

Memory has two layers:

- bounded short-term conversation memory;
- cross-session learned support memory through SenseLab at https://www.sense-lab.ai/.

Memory is advisory. It is not authoritative business truth.

### Customer history

Durable CX records such as:

- previous tickets;
- previous escalations;
- previous resolutions;
- previous CSAT;
- previous conversation records.

The CX platform owns this history.

### Business truth

Authoritative values such as:

- shipment status;
- payment state;
- order status;
- refund eligibility;
- policy rules.

The mock business owns this truth. The agent must query it when current truth matters.

---

# Phase 0 - Architecture baseline

## Goal

Freeze the backend product boundary before implementation.

## Tasks

- [ ] Record ownership for CX data, business data, runtime data, and evaluation data.
- [ ] Define stable correlation IDs:
  - `customer_id`;
  - `ticket_id`;
  - `conversation_id`;
  - `message_id`;
  - `session_id`;
  - `execution_id`;
  - optional external business event IDs.
- [ ] Define the request path from customer message to final response.
- [ ] Define approval pause/resume.
- [ ] Define human escalation.
- [ ] Define the CX operational-event boundary.
- [ ] Record the distinction between workflow state, memory, customer history, and business truth.
- [ ] Record explicit backend non-goals.

## Exit criteria

Every important object has one clear owner, and no generic agent-runtime responsibility belongs to the CX application.

---

# Phase 1 - CX domain and SQLite persistence

## Goal

Create a working customer-service record system before model behavior.

## Core models

Keep these models small and typed:

```text
CustomerBinding
Conversation
Message
Ticket
Escalation
Outcome
CSAT
```

Ticket states:

```text
OPEN
IN_PROGRESS
WAITING_APPROVAL
ESCALATED
RESOLVED
CLOSED
```

## Tasks

- [ ] Use SQLite for CX persistence.
- [ ] Keep mock-business and CX persistence separate.
- [ ] Add a small schema-version mechanism.
- [ ] Add repositories for conversations, messages, tickets, escalations, outcomes, and CSAT.
- [ ] Add lifecycle services.
- [ ] Enforce valid ticket transitions.
- [ ] Add behavior tests for creation, messaging, resolution, escalation, and CSAT.

## Exit criteria

Without an AI model, code can perform:

```text
start conversation
  -> create ticket
  -> append messages
  -> resolve or escalate
  -> record outcome
  -> submit CSAT
```

---

# Phase 2 - Mock-business HTTP integration

## Goal

Make the CX platform a clean HTTP consumer of the reference commerce business.

## Tasks

- [ ] Keep a typed `cx_platform/integrations/mock_business.py` adapter.
- [ ] Make the base URL configurable.
- [ ] Use finite request timeouts.
- [ ] Map transport, not-found, business-rule, and service-unavailable responses into typed application errors.
- [ ] Preserve business IDs exactly.
- [ ] Do not duplicate business rules in CX code.
- [ ] Test against the real mock-business API.
- [ ] Test the shipping-service outage.

## Initial operations

```text
get customer
list customer orders
get order
get order lines
get order payments
get shipment
get fulfillment issues
get returns
get policy
get knowledge
cancel order
request return
request refund
```

## Exit criteria

The CX backend can inspect and act on the mock business through HTTP only.

---

# Phase 3 - Governed support-tool catalog

## Goal

Expose business operations as typed tools managed by https://github.com/etimbukafia/enterprise-agent-harness.

## Read tools

```text
get_customer
get_customer_orders
get_order
get_order_lines
get_order_payments
get_shipment
get_fulfillment_issues
get_returns
get_policy
search_knowledge
```

## Write/action tools

```text
cancel_order
request_return
request_refund
escalate_to_human
```

## Tasks

- [ ] Define typed input and output models.
- [ ] Give each tool a stable ID and version.
- [ ] Mark read, write, and action tools correctly.
- [ ] Implement handlers through application adapters.
- [ ] Register tools with https://github.com/etimbukafia/enterprise-agent-harness.
- [ ] Add behavior tests without a live model.
- [ ] Test safe error mapping.

## Exit criteria

Every external operation needed by the support agent is available through a typed governed tool.

---

# Phase 4 - Customer-service skills

## Goal

Represent customer-service jobs separately from tools and scenarios.

Use skill contracts from https://github.com/etimbukafia/enterprise-agent-harness.

Do not add a second local skill abstraction.

## Initial skills

```text
delivery_resolution
payment_issue_resolution
refund_resolution
return_resolution
cancellation_resolution
damaged_item_resolution
missing_item_resolution
```

Scenarios test skills. Scenarios are not skills.

## Tasks

- [ ] Define each skill and version.
- [ ] Associate relevant tools.
- [ ] Register skills.
- [ ] Attach skill references to the support-agent definition.
- [ ] Add registry tests.

## Exit criteria

A reviewer can inspect the agent definition and understand its supported customer-service jobs without reading prompt text.

---

# Phase 5 - Agent state, memory, learning, and CX history

## Goal

Provide continuity without allowing memory to replace business truth.

Use this architecture:

```text
current workflow state
  -> https://github.com/etimbukafia/enterprise-agent-harness StateStore

short-term conversation continuity
  -> bounded local/runtime memory

cross-session learned support memory
  -> SenseLab

customer-service history
  -> CX platform SQLite

authoritative commerce truth
  -> mock-business HTTP API
```

Use `plan/PHASE_5_STATE_MEMORY_AND_CX_HISTORY.md` as the detailed Phase 5 specification.

## Required rules

- [ ] Workflow state uses the real support-agent identity.
- [ ] Short-term memory stays bounded.
- [ ] SenseLab stays behind a CX-owned adapter.
- [ ] Deterministic tests require no SenseLab account or network access.
- [ ] Cross-session customer memory stays customer-scoped.
- [ ] Shared support learning remains advisory.
- [ ] CX outcomes remain authoritative in CX persistence.
- [ ] Memory provenance links to execution evidence.
- [ ] Fresh business truth overrides stale memory.
- [ ] SenseLab failure does not block normal support execution.

## Exit criteria

The agent can maintain useful continuity while current business tools and policy remain authoritative.

---

# Phase 6 - Governed customer-support agent

## Goal

Create one real customer-support agent through https://github.com/etimbukafia/enterprise-agent-harness.

Do not build a custom reasoning or tool loop in CX code.

## Agent

```text
customer-support-agent@1.0.0
```

Use the seven Phase 4 skills.

Reference the one versioned `customer-support-prompt@1.0.0` from the Harness `PromptRegistry`. Keep behavioral instructions in that prompt artifact and keep authority in policy, permission, and approval boundaries.

## Provider modes

### Deterministic mode

Use the deterministic provider for tests and offline development.

### Live mode

Use a provider adapter supplied through https://github.com/etimbukafia/enterprise-agent-harness.

Keep provider SDK calls out of the CX support service.

## Agent rules

The support agent must:

- use current business tools for authoritative facts;
- treat memory as advisory;
- avoid invented business facts;
- avoid claiming an action succeeded before the tool confirms it;
- clarify material ambiguity;
- respect permission, policy, and approval boundaries;
- escalate when safe resolution is not available.

## Tasks

- [ ] Define the support-agent configuration.
- [ ] Register exact tool and skill versions.
- [ ] Configure state and memory boundaries.
- [ ] Build with the Harness factory/runtime path.
- [ ] Map CX identity to trusted runtime principal context.
- [ ] Execute the agent from the CX support service.
- [ ] Preserve `execution_id` across CX records.
- [ ] Support deterministic and live modes.

## Exit criteria

A customer request follows one governed execution path from CX API to business result.

---

# Phase 7 - Policy, approval, and escalation

## Goal

Add the minimum human-control mechanisms required by the support scenarios.

## Policy

Use a small deny-by-default policy.

Only allow exact tools and actions required by the support agent.

## Approval

Use the exact approval pause/resume path from https://github.com/etimbukafia/enterprise-agent-harness.

Expected flow:

```text
agent proposes restricted action
  -> runtime requires approval
  -> ticket becomes WAITING_APPROVAL
  -> operator calls approve or reject backend endpoint
  -> runtime resumes the exact paused action when approved
```

Do not create a second independent approval system.

## Escalation reasons

```text
CUSTOMER_REQUESTED_HUMAN
ACTION_REQUIRES_HUMAN
BUSINESS_SYSTEM_UNAVAILABLE
UNSUPPORTED_REQUEST
AMBIGUOUS_ACCOUNT
AGENT_UNCERTAIN
POLICY_CONFLICT
```

Do not store hidden reasoning.

## Tasks

- [ ] Define the support-agent allow policy.
- [ ] Connect CX to the Harness approval broker/runtime path.
- [ ] Persist only the CX approval reference data needed for review and correlation.
- [ ] Add approve and reject backend endpoints.
- [ ] Resume the exact paused execution.
- [ ] Implement structured human escalation.
- [ ] Test denial, approval, rejection, expiry, and dependency failure.

## Exit criteria

The model cannot bypass policy or approval, and human intervention is represented through explicit backend records and endpoints.

---

# Phase 8 - CX operational event model

## Goal

Create a durable CX operational record without duplicating the full Harness trace.

## Event contract

```text
event_id
event_type
occurred_at
customer_id
ticket_id
conversation_id
message_id
execution_id
actor_type
actor_id
data
```

## Initial event catalog

```text
conversation.started
conversation.ended
message.customer_received
message.agent_sent
ticket.created
ticket.status_changed
ticket.resolved
ticket.escalated
agent.execution_started
agent.execution_completed
agent.execution_failed
agent.tool_called
agent.tool_succeeded
agent.tool_failed
approval.requested
approval.approved
approval.rejected
outcome.recorded
csat.received
```

CX events do not emit an inferred skill-selection event. Use Harness trace provenance for exact skill references.

## Rules

- CX events represent CX operational facts.
- Mock-business events represent business-domain facts.
- Harness traces represent runtime execution evidence.
- Do not copy one evidence stream into another.
- Link evidence through stable IDs.
- Keep raw prompts and private reasoning out of CX events.

## Tasks

- [ ] Define typed `CXEvent` models.
- [ ] Add append-only SQLite persistence.
- [ ] Add useful correlation indexes.
- [ ] Emit events from service boundaries.
- [ ] Add `GET /events?after=<cursor>`.
- [ ] Add timeline reconstruction tests.

## Exit criteria

The CX backend can reconstruct the operational support journey from stored CX events.

---

# Phase 9 - Agent trace linkage

## Goal

Make detailed runtime evidence referenceable without copying Harness trace internals into CX persistence.

https://github.com/etimbukafia/enterprise-agent-harness remains the owner of detailed execution traces.

## CX execution reference

Store only the fields needed for correlation:

```text
execution_id
conversation_id
ticket_id
agent_id
agent_version
started_at
completed_at
outcome_status
trace_reference
```

## Tasks

- [ ] Persist execution references.
- [ ] Link messages, approvals, tool events, escalation, and outcomes to `execution_id` where applicable.
- [ ] Preserve the same execution correlation through approval pause/resume.
- [ ] Add a safe `GET /executions/{execution_id}` backend read.
- [ ] Do not persist private chain-of-thought.

## Exit criteria

A reviewer or external system can navigate:

```text
ticket
  -> conversation
  -> execution reference
  -> Harness trace reference
  -> governed business action
```

---

# Phase 10 - Reference scenario acceptance suite

## Goal

Use the mock-business scenarios as repeatable backend system acceptance cases.

Each case should define:

```text
initial business state
customer request or conversation turns
allowed outcomes
forbidden outcomes
required evidence or tool activity
expected final ticket state
```

## Scenario coverage

### 1. Normal delivery

- report current delivery truth;
- no unnecessary refund;
- no unnecessary escalation.

### 2. Delayed delivery

- recognize the delay;
- report current shipment evidence;
- respect the policy threshold;
- do not invent replacement eligibility.

### 3. Lost package

- detect the lost shipment;
- offer or execute an allowed remedy.

### 4. Duplicate charge

- inspect payment records;
- identify the duplicate-payment evidence;
- use the correct resolution path.

### 5. Refund requires approval

- propose the correct refund;
- pause for Harness approval;
- execute nothing before approval;
- resume the exact reviewed action.

### 6. Refund denied by policy

- inspect the relevant policy;
- do not issue the disallowed refund;
- explain the result accurately.

### 7. Damaged item

- identify the correct order line;
- inspect the fulfillment issue;
- follow the valid return/refund path.

### 8. Missing item

- distinguish a missing line from a lost shipment;
- identify the affected item;
- follow the valid resolution path.

### 9. Cancellation before shipment

- cancel the eligible order;
- record the correct outcome.

### 10. Cancellation after shipment

- preserve the authoritative business denial;
- never claim cancellation succeeded.

### 11. Shipping-service outage

- recognize unavailable shipment data;
- do not invent shipment state;
- preserve the dependency failure;
- escalate only when appropriate.

## Cross-scenario tests

- [ ] multi-turn reference resolution;
- [ ] customer/account isolation;
- [ ] stale memory does not override fresh business truth;
- [ ] denied action behavior;
- [ ] tool failure behavior;
- [ ] approval pause/resume;
- [ ] CX event correlation;
- [ ] runtime trace linkage;
- [ ] correct outcome recording.

Use deterministic provider cases for automated acceptance.

Keep any live-model smoke tests small and opt-in.

## Exit criteria

All eleven scenarios can be exercised through the same backend support-agent path.

---

# Phase 11 - Outcomes and small CX metrics

## Goal

Produce useful customer-service evidence without building a BI system.

## Per-ticket outcome data

Capture values such as:

```text
resolved
escalated
resolution_code
turn_count
tool_call_count
tool_failure_count
approval_required
approval_result
duration
csat_score
```

## Initial resolution codes

```text
INFORMATION_PROVIDED
DELIVERY_EXPLAINED
ORDER_CANCELLED
RETURN_CREATED
REFUND_REQUESTED
REFUND_DENIED
PAYMENT_ISSUE_RESOLVED
ESCALATED_TO_HUMAN
DEPENDENCY_UNAVAILABLE
UNRESOLVED
```

Only add codes that correspond to real observed outcomes.

## Aggregate metrics

Calculate only metrics supported by stored backend data:

- conversation count;
- resolution rate;
- escalation rate;
- average turns;
- tool failure rate;
- approval rate;
- average submitted CSAT;
- outcome distribution.

Do not claim ROI, labor savings, first-contact resolution, or other unsupported business metrics.

## Tasks

- [ ] Finalize the resolution-code set.
- [ ] Record structured outcome data on resolution or escalation.
- [ ] Compute metrics from persisted records and events.
- [ ] Add a small typed backend metrics endpoint if useful.
- [ ] Keep every metric reproducible from underlying records.

## Exit criteria

The backend produces structured, defensible outcome evidence and simple reproducible metrics.

---

# Phase 12 - External evidence and export boundary

## Goal

Prepare the backend for later analysis without implementing CX Autopilot inside it.

## Stable read interfaces

Expose application-level reads for:

```text
GET /events
GET /tickets
GET /tickets/{ticket_id}
GET /conversations/{conversation_id}
GET /executions/{execution_id}
GET /outcomes
```

Add only the smallest extra reads needed to make the evidence chain consumable without direct database access.

## Evidence chain

Preserve:

```text
customer message
  -> conversation
  -> ticket
  -> agent execution
  -> governed tool call
  -> business operation
  -> business event reference
  -> agent response
  -> ticket outcome
  -> CSAT
```

## Tasks

- [ ] Define typed export/read models.
- [ ] Preserve correlation IDs across CX, Harness, memory, and business boundaries.
- [ ] Add pagination or `after` polling where needed.
- [ ] Add a combined interaction-timeline read only if it clearly simplifies external consumption.
- [ ] Document evidence ownership between CX, mock business, SenseLab references, and https://github.com/etimbukafia/enterprise-agent-harness.
- [ ] Add backend contract tests for external reads.

## Exit criteria

A future analysis system can consume the required CX evidence without importing CX internals or reading SQLite directly.

---

# Recommended repository shape

Keep the application modular but not layered for its own sake.

```text
AI-native-CX-platform/
├── src/
│   └── mock_business/
│       └── ... reference business
│
├── cx_platform/
│   ├── api/
│   ├── domain/
│   ├── agent/
│   ├── memory/
│   ├── tools/
│   ├── integrations/
│   ├── services/
│   ├── persistence/
│   ├── docs/
│   └── main.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── scenarios/
│
├── docs/
└── plan/
```

`cx_platform/` is the canonical CX application package.

Do not create a second `src/cx_platform` package.

The reusable agent runtime remains at https://github.com/etimbukafia/enterprise-agent-harness.

---

# Explicit non-goals for v0.1

Do not build:

- customer frontend;
- operator frontend;
- voice support;
- email support;
- WhatsApp support;
- omnichannel routing;
- workforce management;
- call recording;
- real authentication or SSO;
- production multi-tenancy;
- sophisticated RBAC;
- Kubernetes;
- Kafka;
- Redis;
- microservices;
- a vector database without a concrete retrieval need;
- a generic workflow builder;
- a generic prompt-management system;
- multiple support agents;
- supervisor-agent orchestration;
- agent-to-agent delegation;
- a custom-business builder;
- a custom-scenario-builder UI;
- real payment processing;
- real CRM integrations;
- production secrets infrastructure;
- production-scale observability infrastructure;
- CX Autopilot itself.

If a feature does not improve the backend support journey, evidence quality, agent governance, or future analyzability, keep it out of v0.1.

---

# v0.1 backend acceptance journey

A strong backend demonstration should support this sequence through API calls and persisted evidence:

```text
1. Activate a reference business scenario.

2. Create or select a seeded CX customer binding.

3. Start a conversation and ticket.

4. Submit a customer support message.

5. Run customer-support-agent@1.0.0 through
   https://github.com/etimbukafia/enterprise-agent-harness.

6. Use governed tools to inspect current business truth.

7. Use bounded conversation memory and relevant SenseLab memory only as advisory context.

8. Select a valid resolution path from current evidence.

9. Request an allowed business action when needed.

10. If approval is required, pause the governed execution.

11. Approve or reject through the CX backend endpoint.

12. Resume the exact execution when approved.

13. Persist the customer-facing result as a CX message.

14. Record the structured ticket outcome.

15. Accept CSAT where lifecycle rules permit it.

16. Preserve CX events, execution references, memory evidence, Harness trace references, and business event references.

17. Export the evidence through typed backend read interfaces.
```

That is the target backend. It is deliberately small, but it demonstrates real AI-operated customer support with business actions, hybrid memory, governance, human control, outcomes, and usable operational evidence.
