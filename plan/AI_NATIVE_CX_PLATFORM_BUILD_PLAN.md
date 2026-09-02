# AI-native CX Platform Build Plan

Status: proposed implementation plan

## 1. Product goal

Build a small AI-native customer service platform where a human customer can talk to an AI support agent that can inspect and act on a realistic commerce business.

The platform must demonstrate a complete support journey:

```text
human customer
  -> customer chat
  -> CX conversation and ticket
  -> governed AI support agent
  -> business tools
  -> mock business
  -> action or escalation
  -> CX outcome
  -> operational evidence
```

The product is intentionally small. It is not a replacement for Zendesk, Genesys, Salesforce Service Cloud, or another production contact-center platform.

The most important quality is trustworthy operational data. The system must preserve a clear evidence chain from customer request to agent execution, business action, and final outcome.

## 2. System boundaries

Three boundaries must stay separate.

### AI-native CX platform

Owns:

- customer chat;
- conversations;
- tickets;
- messages;
- customer-service outcomes;
- human escalation records;
- approval presentation and operator actions;
- CSAT;
- CX operational events;
- links between CX records, agent executions, and business activity.

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

The CX platform must use the mock business through its HTTP API. It must not read the mock business database directly.

### Enterprise agent runtime

Use https://github.com/etimbukafia/enterprise-agent-harness for the support agent runtime.

That repository owns generic agent concerns such as:

- governed execution;
- provider boundaries;
- typed tools;
- tool registries;
- capability registries;
- permission and policy enforcement;
- approval gates;
- agent state;
- bounded memory;
- trace and audit evidence;
- agent factory and versioned configuration.

The CX platform must consume that runtime. It must not create a second general-purpose agent runtime.

## 3. Core data distinction

The implementation must preserve four different concepts.

### Conversation state

Temporary workflow facts for the active support case.

Examples:

- active intent;
- active order ID;
- active order-line ID;
- customer requested refund;
- waiting for approval.

Use the state boundary from https://github.com/etimbukafia/enterprise-agent-harness for agent workflow state.

### Agent memory

Bounded conversational continuity.

Good memory examples:

- customer prefers a refund instead of replacement;
- customer already supplied the order number;
- customer means the second item in the order;
- customer needs the order before Friday.

Do not treat memory as authoritative business truth.

### Customer history

Durable CX records such as:

- previous tickets;
- previous escalations;
- previous resolutions;
- previous CSAT.

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

Freeze the small product boundary before building the CX application.

## Tasks

- [ ] Write `docs/cx-platform-architecture.md`.
- [ ] Record ownership for CX data, business data, agent runtime data, and evaluation data.
- [ ] Define stable correlation IDs:
  - `customer_id`;
  - `ticket_id`;
  - `conversation_id`;
  - `message_id`;
  - `session_id`;
  - `execution_id`;
  - optional external business event IDs.
- [ ] Define the request path from customer message to final response.
- [ ] Define the approval pause/resume path.
- [ ] Define the human escalation path.
- [ ] Define the operational event model at a high level.
- [ ] Record the distinction between state, memory, customer history, and business truth.
- [ ] Record explicit non-goals.

## Exit criteria

Every important object has one clear owner, and no generic agent-runtime responsibility belongs to the CX application.

---

# Phase 1 - CX domain and SQLite persistence

## Goal

Create a working customer-service record system before introducing model behavior.

## Domain models

### CustomerBinding

Keep only the information needed to bind a CX user to a mock-business customer.

Suggested fields:

```text
customer_id
external_customer_id
display_name
created_at
```

Do not copy the full commerce customer record into the CX database.

### Conversation

Suggested fields:

```text
conversation_id
ticket_id
customer_id
status
started_at
ended_at
```

### Message

Suggested fields:

```text
message_id
conversation_id
actor_type
actor_id
content
created_at
```

Actor types:

```text
CUSTOMER
AI_AGENT
SYSTEM
HUMAN_AGENT
```

### Ticket

Suggested fields:

```text
ticket_id
customer_id
conversation_id
status
reason
priority
resolution_code
created_at
resolved_at
```

Keep the status set small:

```text
OPEN
IN_PROGRESS
WAITING_APPROVAL
ESCALATED
RESOLVED
CLOSED
```

### Escalation

Suggested fields:

```text
escalation_id
ticket_id
reason
summary
status
created_at
resolved_at
```

### Outcome

Suggested fields:

```text
outcome_id
ticket_id
outcome_type
metadata
created_at
```

### CSAT

Suggested fields:

```text
csat_id
ticket_id
score
comment
submitted_at
```

## Tasks

- [ ] Add the CX schema beside the existing mock-business schema but keep the modules separate.
- [ ] Use SQLite for CX persistence.
- [ ] Add a small schema-version mechanism.
- [ ] Add repositories for conversations, messages, tickets, escalations, outcomes, and CSAT.
- [ ] Add domain services for conversation and ticket lifecycle.
- [ ] Enforce valid ticket status transitions.
- [ ] Add tests for conversation creation, message append, resolution, escalation, and CSAT.

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

Make the CX platform a clean consumer of the reference commerce business.

## Tasks

- [ ] Create `cx_platform/integrations/mock_business.py`.
- [ ] Add a typed HTTP client.
- [ ] Make the mock-business base URL configurable.
- [ ] Add finite request timeouts.
- [ ] Map 404, business-rule errors, and service-unavailable responses into typed application errors.
- [ ] Preserve business IDs exactly.
- [ ] Do not duplicate business rules in the CX platform.
- [ ] Add integration tests against the real mock-business API.
- [ ] Test the shipping service outage explicitly.

## Initial operations

The adapter should cover the existing API operations required by support:

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

## Important rule

The CX application must not decide whether a commerce action is valid when the mock business already owns that rule.

For example, the CX platform should not locally infer that a shipped order cannot be cancelled. It should call the business action and preserve the authoritative result.

## Exit criteria

The CX backend can inspect and act on the mock business through HTTP only.

---

# Phase 3 - Governed support-tool catalog

## Goal

Expose business operations as typed tools managed by https://github.com/etimbukafia/enterprise-agent-harness.

Tools are atomic operations. They are not customer-service workflows.

## Read tools

Start with:

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

Start with:

```text
cancel_order
request_return
request_refund
escalate_to_human
```

`escalate_to_human` is a CX-platform action. The other actions delegate to the mock business.

## Tasks

- [ ] Define a typed input model for each tool.
- [ ] Define a typed output model for each tool.
- [ ] Give each tool a stable ID and version.
- [ ] Mark tools correctly as read, write, or action tools.
- [ ] Implement handlers through the integration adapter.
- [ ] Register tools with the tool registry from https://github.com/etimbukafia/enterprise-agent-harness.
- [ ] Add tests for every handler without a live model.
- [ ] Test error mapping.
- [ ] Ensure tool output cannot silently turn transport errors into business facts.

## Exit criteria

Every external operation needed by the support agent is available through a typed governed tool.

---

# Phase 4 - Customer-service capabilities

## Goal

Represent what the support agent can accomplish independently of individual tools.

Use the capability contracts and registry from https://github.com/etimbukafia/enterprise-agent-harness. Do not add a second local `Skill` abstraction.

## Initial capabilities

```text
delivery_resolution
payment_issue_resolution
refund_resolution
return_resolution
cancellation_resolution
damaged_item_resolution
missing_item_resolution
```

Only add a broad `general_order_support` capability if a concrete use case requires it.

## Design rule

Scenarios test capabilities. Scenarios are not capabilities.

For example:

```text
delivery_resolution
  -> normal delivery
  -> delayed delivery
  -> lost package
  -> shipping outage
```

Do not create separate capabilities such as `delayed_delivery_skill` and `lost_package_skill`.

## Tasks

- [ ] Define each capability and version.
- [ ] Describe the business job each capability owns.
- [ ] Associate relevant tools with each capability.
- [ ] Define supported intents where the runtime contract needs them.
- [ ] Register capabilities.
- [ ] Attach the capability references to the support-agent definition.
- [ ] Add registry tests.

## Exit criteria

A reviewer can inspect the agent definition and understand its customer-service abilities without reading prompt text.

---

# Phase 5 - Agent state, memory, and CX history

## Goal

Provide continuity without allowing stale memory to become business truth.

## Phase 5A - Workflow state

Use the state boundary from https://github.com/etimbukafia/enterprise-agent-harness.

Suggested state is intentionally small:

```text
active_intent
active_order_id
active_line_id
customer_requested_resolution
awaiting_approval
```

### Tasks

- [ ] Define the state schema.
- [ ] Bind state to trusted customer/session identity.
- [ ] Persist active references between turns.
- [ ] Clear case-specific state at the right lifecycle boundary.
- [ ] Test switching from one order to another in the same conversation.

## Phase 5B - Bounded agent memory

Use the memory boundary from https://github.com/etimbukafia/enterprise-agent-harness.

Memory may retain:

- resolved references from earlier turns;
- customer-stated preferences relevant to the current support journey;
- compact turn summaries;
- unresolved customer goals.

Memory must not become the source of truth for current order, payment, shipment, refund, or policy state.

### Tasks

- [ ] Define allowed memory item types.
- [ ] Keep memory bounded.
- [ ] Prefer summaries over full transcript duplication.
- [ ] Store resolved conversational references.
- [ ] Store useful customer-stated preferences.
- [ ] Test follow-up language such as:
  - "What about the other one?";
  - "Actually, refund it instead.";
  - "I mean the headphones order.".

## Phase 5C - Customer history

Keep previous ticket, escalation, resolution, and CSAT records in the CX database.

Do not write these records into free-form agent memory.

## Exit criteria

State, memory, CX history, and business truth remain separate in both code and tests.

---

# Phase 6 - Build the customer-support agent

## Goal

Create one real customer-support agent through https://github.com/etimbukafia/enterprise-agent-harness.

Do not build a custom reasoning/tool loop in the CX application.

## Agent definition

Conceptually:

```text
customer-support-agent@1.0.0

Goal:
Resolve supported commerce customer-service issues safely and accurately.

Capabilities:
- delivery_resolution
- payment_issue_resolution
- refund_resolution
- return_resolution
- cancellation_resolution
- damaged_item_resolution
- missing_item_resolution
```

## Provider modes

### Deterministic mode

Use the deterministic provider from https://github.com/etimbukafia/enterprise-agent-harness for tests and offline development.

### Live-model mode

Use a provider adapter supported by https://github.com/etimbukafia/enterprise-agent-harness for the interactive demo.

Keep provider SDK calls out of the CX application service.

## Agent instruction rules

The instructions should be short and operational. The agent should know:

- what customer-service job it performs;
- that business tools are authoritative for current business state;
- to inspect evidence before claiming a business fact;
- not to claim an action happened until a successful tool result confirms it;
- to ask for clarification when the account, order, or item is ambiguous;
- not to invent data during dependency outages;
- to respect approval and policy boundaries;
- to escalate when a safe resolution is not available.

## Tasks

- [ ] Define the support-agent configuration.
- [ ] Register exact tool versions.
- [ ] Register exact capability versions.
- [ ] Register the small policy set.
- [ ] Configure state and bounded memory.
- [ ] Build the agent with the factory from https://github.com/etimbukafia/enterprise-agent-harness.
- [ ] Map CX session/customer identity into trusted runtime principal context.
- [ ] Execute the support agent from the CX conversation service.
- [ ] Store `execution_id` with the customer message and resulting agent message.
- [ ] Support deterministic and live-model configurations.

## Exit criteria

A customer message follows one governed path:

```text
CX API
  -> support service
  -> https://github.com/etimbukafia/enterprise-agent-harness runtime
  -> provider
  -> governed tool
  -> mock-business HTTP API
  -> governed result
  -> customer response
```

---

# Phase 7 - Policy, approval, and escalation

## Goal

Add the minimum human-control mechanisms needed by the reference business scenarios.

## Policy

Use a small deny-by-default policy for the support agent.

Only allow the exact tools and actions required by the support capabilities.

## Approval

Do not add approval to every write.

Use approval where the business scenario requires it, especially refund approval.

Use the approval mechanisms from https://github.com/etimbukafia/enterprise-agent-harness so that a reviewed action can pause and resume through the governed runtime.

Expected flow:

```text
agent proposes action
  -> runtime requires approval
  -> ticket becomes WAITING_APPROVAL
  -> operator reviews exact action
  -> approve or reject
  -> runtime resumes exact paused action
```

## Human escalation

Start with structured reasons:

```text
CUSTOMER_REQUESTED_HUMAN
ACTION_REQUIRES_HUMAN
BUSINESS_SYSTEM_UNAVAILABLE
UNSUPPORTED_REQUEST
AMBIGUOUS_ACCOUNT
AGENT_UNCERTAIN
POLICY_CONFLICT
```

An escalation record should include only useful operational context:

```text
reason
short summary
customer goal
active order or item
important actions attempted
important tool results or references
conversation_id
execution_id
```

Do not store hidden model reasoning.

## Tasks

- [ ] Define the support-agent allow policy.
- [ ] Connect the CX application to the approval broker/runtime path.
- [ ] Persist the CX-side representation of pending approvals if needed by the operator UI.
- [ ] Add approve and reject endpoints.
- [ ] Resume the exact paused execution after approval.
- [ ] Implement `escalate_to_human`.
- [ ] Persist escalation reason and handoff summary.
- [ ] Test denial, approval, rejection, and unavailable-dependency paths.

## Exit criteria

The model cannot bypass policy or approval, and a human can understand and act on the resulting approval or escalation.

---

# Phase 8 - CX operational event model

## Goal

Create a durable operational record that is useful to a future CX analysis system without duplicating the full agent trace.

## Event contract

Suggested fields:

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

Only populate fields that apply to the event.

## Initial event catalog

### Conversation

```text
conversation.started
conversation.ended
message.customer_received
message.agent_sent
```

### Ticket

```text
ticket.created
ticket.status_changed
ticket.resolved
ticket.escalated
```

### Agent execution

```text
agent.execution_started
agent.execution_completed
agent.execution_failed
```

Only emit `agent.capability_selected` if the runtime provides trustworthy capability-selection evidence.

### Tool activity

```text
agent.tool_called
agent.tool_succeeded
agent.tool_failed
```

### Approval

```text
approval.requested
approval.approved
approval.rejected
```

### Outcome

```text
outcome.recorded
csat.received
```

## Rules

- The CX event stream records operational activity.
- The mock-business event stream records business activity.
- The runtime trace from https://github.com/etimbukafia/enterprise-agent-harness records detailed agent execution evidence.
- Do not copy every business event into CX events.
- Do not reproduce every runtime trace record as a CX event.
- Link evidence using stable IDs instead.

## Tasks

- [ ] Define typed `CXEvent` models.
- [ ] Add an append-only CX event table.
- [ ] Emit events from the CX service layer.
- [ ] Add `GET /events?after=<event_id>`.
- [ ] Preserve correlation IDs.
- [ ] Add timeline reconstruction tests.
- [ ] Keep raw provider prompts and private reasoning out of CX events.

## Exit criteria

Given a conversation ID, the platform can reconstruct the operational customer-service journey.

---

# Phase 9 - Agent trace linkage

## Goal

Make detailed agent evidence inspectable without copying runtime internals into CX persistence.

https://github.com/etimbukafia/enterprise-agent-harness remains the owner of detailed execution traces.

The CX platform should persist a small execution-link record such as:

```text
execution_id
conversation_id
ticket_id
agent_id
agent_version
started_at
completed_at
outcome_status
trace_reference or retrieval key
```

## Tasks

- [ ] Persist execution correlation records.
- [ ] Link customer and AI messages to execution IDs.
- [ ] Link approval records to execution IDs.
- [ ] Link relevant tool events to execution IDs.
- [ ] Add a safe trace-inspection endpoint or application service.
- [ ] Preserve enough information for later external evaluation.
- [ ] Do not persist private chain-of-thought.

## Exit criteria

A reviewer can navigate this chain:

```text
ticket
  -> conversation
  -> agent execution
  -> runtime trace
  -> business action
```

---

# Phase 10 - Customer chat frontend

## Goal

Give a human a simple way to use the AI support agent.

This phase needs one customer-facing web chat, not a general channel framework.

## Minimum interface

- customer selection or simple demo identity;
- start conversation;
- message history;
- message composer;
- waiting state;
- AI responses;
- escalation status;
- resolved state;
- CSAT form after resolution.

## Demo identity

Do not build real authentication.

Use a clear demo mechanism such as selecting one seeded customer account or entering a known test email that resolves to a mock-business customer.

## Streaming

Streaming is optional.

First implement a correct request/complete-response flow. Add streaming only if it materially improves the demo and does not complicate the architecture.

## Tasks

- [ ] Add the customer entry/account selection view.
- [ ] Start or resume a conversation.
- [ ] Render messages in order.
- [ ] Send a customer message.
- [ ] Display request progress.
- [ ] Display agent response.
- [ ] Show escalation and resolution states.
- [ ] Submit CSAT.
- [ ] Handle API and model failures clearly.

## Exit criteria

A person who has not read the source code can complete a customer-support conversation.

---

# Phase 11 - Operator and review frontend

## Goal

Make agent operation explainable during a demo without building a contact-center desktop.

## Dashboard

Show only useful counts and queues:

```text
open tickets
resolved tickets
escalated tickets
waiting approvals
recent conversations
recent failures
```

## Ticket detail

This is the most important operator screen.

Show a chronological timeline of:

```text
customer message
AI response
tool activity
business result
approval request
approval decision
escalation or resolution
CSAT
```

Also show:

- customer reference;
- ticket state;
- resolution code;
- agent ID/version;
- execution IDs.

## Approval queue

Keep it small:

```text
ticket
reason
proposed action
important parameters
approve
reject
```

## Scenario control

For demo/admin use only, allow the operator to activate one reference scenario and reset the mock business.

The support agent must never receive the scenario ID as hidden knowledge.

## Tasks

- [ ] Add ticket list.
- [ ] Add ticket-detail timeline.
- [ ] Add escalation queue.
- [ ] Add approval queue.
- [ ] Add scenario selector/reset.
- [ ] Add safe execution/trace inspection.
- [ ] Add clear error and status states.

## Exit criteria

An interviewer can understand what the support agent did without reading terminal logs.

---

# Phase 12 - Reference scenario acceptance suite

## Goal

Use the mock-business scenarios as repeatable system acceptance cases for the support platform.

Each case should define:

```text
initial business state
customer request or conversation turns
allowed outcomes
forbidden outcomes
required evidence or tool activity
expected final ticket state
```

## Scenario 1 - Normal delivery

Expected:

- report current delivery truth;
- no unnecessary refund;
- no unnecessary escalation.

## Scenario 2 - Delayed delivery

Expected:

- recognize the delay;
- report current shipment evidence;
- follow the replacement/refund policy boundary.

Forbidden:

- invent eligibility that the business state does not support.

## Scenario 3 - Lost package

Expected:

- detect the lost shipment;
- offer or perform an allowed remedy.

## Scenario 4 - Duplicate charge

Expected:

- inspect payment records;
- identify the duplicate-payment evidence;
- follow the correct resolution path.

## Scenario 5 - Refund requires approval

Expected:

- propose the correct refund;
- pause for approval;
- perform no refund before approval;
- resume the exact reviewed action after approval.

## Scenario 6 - Refund denied by policy

Expected:

- inspect the relevant policy;
- do not issue the disallowed refund;
- explain the result accurately.

## Scenario 7 - Damaged item

Expected:

- identify the correct order line;
- inspect the fulfillment issue;
- follow the valid return/refund path.

## Scenario 8 - Missing item

Expected:

- distinguish a missing line item from a fully lost shipment;
- identify the affected item;
- follow the valid resolution path.

## Scenario 9 - Cancellation before shipment

Expected:

- cancel the eligible order successfully;
- record the correct outcome.

## Scenario 10 - Cancellation after shipment

Expected:

- call or validate through the business action;
- preserve the authoritative denial;
- never claim that cancellation succeeded.

## Scenario 11 - Shipping service outage

Expected:

- recognize that shipping data is unavailable;
- do not invent shipment status;
- communicate the limitation;
- escalate only when appropriate.

## Cross-scenario tests

- [ ] multi-turn conversational reference resolution;
- [ ] customer/account isolation;
- [ ] stale memory does not override new business truth;
- [ ] denied write/action behavior;
- [ ] tool failure behavior;
- [ ] approval pause/resume;
- [ ] CX event correlation;
- [ ] runtime trace linkage;
- [ ] correct outcome recording.

## Test modes

Use deterministic runtime/provider cases for repeatable automated acceptance.

Use a smaller live-model smoke suite for the interactive path. Do not make CI depend on a live model key.

## Exit criteria

All eleven business scenarios can be exercised through the same support agent and normal CX interfaces.

---

# Phase 13 - Outcomes and small CX metrics

## Goal

Produce useful customer-service evidence without building a BI platform.

## Ticket outcome fields

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

## Small aggregate metrics

Calculate only metrics supported by stored data:

- conversation count;
- resolution rate;
- escalation rate;
- average turns;
- tool failure rate;
- approval rate;
- average submitted CSAT;
- outcome distribution.

Do not claim ROI, labor savings, first-contact resolution, or other business metrics unless the required evidence is actually collected and the calculation is defined.

## Tasks

- [ ] Finalize the resolution-code set.
- [ ] Record structured outcome data on resolution/escalation.
- [ ] Add a small aggregate endpoint.
- [ ] Show a minimal metric summary in the operator UI.
- [ ] Keep every metric reproducible from underlying records.

## Exit criteria

The platform produces structured, defensible outcome evidence.

---

# Phase 14 - External evidence/export boundary

## Goal

Prepare the CX platform for later analysis without implementing CX Autopilot inside it.

## Initial read interfaces

Expose stable application-level reads for:

```text
GET /events
GET /tickets
GET /tickets/{ticket_id}
GET /conversations/{conversation_id}
GET /executions/{execution_id}
GET /outcomes
```

The exact HTTP surface can remain small, but another system must not need direct database access.

## Evidence chain

The platform should preserve this chain:

```text
customer message
  -> conversation
  -> ticket
  -> agent execution
  -> governed tool call
  -> business operation
  -> business event
  -> agent response
  -> ticket outcome
  -> CSAT
```

## Tasks

- [ ] Define typed export/read models.
- [ ] Preserve correlation IDs across CX, runtime, and business boundaries.
- [ ] Add simple pagination or `after` polling where needed.
- [ ] Add a combined interaction-timeline read only if it genuinely simplifies external consumption.
- [ ] Document which evidence belongs to the CX platform, mock business, and https://github.com/etimbukafia/enterprise-agent-harness.

## Exit criteria

A future analysis system can consume CX evidence without importing CX internals or reading SQLite directly.

---

# Phase 15 - Demo hardening and documentation

## Goal

Make the repository straightforward to run, inspect, and evaluate.

## Desired local flow

```text
start mock business
start CX backend
start customer/operator frontend
activate scenario
chat with support agent
inspect ticket timeline
```

## Tasks

- [ ] Add `.env.example`.
- [ ] Add clear local startup commands.
- [ ] Add health endpoints.
- [ ] Add deterministic/offline agent mode.
- [ ] Add live-model demo mode.
- [ ] Add CX database reset command.
- [ ] Keep mock-business scenario reset available.
- [ ] Add an end-to-end demo walkthrough.
- [ ] Add an architecture diagram.
- [ ] Add CI for tests, type checks, linting, and compile/import checks.
- [ ] Review README claims against measured system behavior.
- [ ] Remove unused abstractions created during implementation.

## Exit criteria

A reviewer can clone the required repositories, follow documented steps, and reproduce the reference support journey.

---

# Recommended repository shape

Keep the application modular but not layered for its own sake.

```text
AI-native-CX-platform/
├── src/
│   ├── mock_business/
│   │   └── ... existing reference business
│   │
│   └── cx_platform/
│       ├── api/
│       ├── domain/
│       ├── agent/
│       ├── tools/
│       ├── integrations/
│       ├── services/
│       ├── persistence/
│       └── main.py
│
├── frontend/
│   ├── customer/
│   └── operations/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── scenarios/
│
├── docs/
└── plan/
```

Do not split these layers into separate repositories.

The reusable agent runtime remains at https://github.com/etimbukafia/enterprise-agent-harness.

---

# Explicit non-goals for v0.1

Do not build:

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

If a feature does not improve the reference customer journey, business evidence, agent governance, or future analyzability, it should probably stay out of v0.1.

---

# v0.1 acceptance journey

A strong final demonstration should look like this:

```text
1. Operator activates the damaged-item scenario.

2. Customer selects the seeded customer account.

3. Customer says:
   "The headphones arrived broken. I want my money back."

4. The CX platform creates a conversation and ticket.

5. The customer-support agent runs through
   https://github.com/etimbukafia/enterprise-agent-harness.

6. The agent uses governed tools to inspect:
   customer account,
   order history,
   order lines,
   fulfillment issue,
   payment,
   policy,
   knowledge.

7. The agent selects a valid resolution path.

8. The agent requests the allowed return/refund action.

9. If approval is required, the governed execution pauses.

10. The operator reviews and approves or rejects the exact action.

11. The governed execution resumes when appropriate.

12. The customer receives the business-backed result.

13. The ticket receives a structured outcome.

14. The customer can submit CSAT.

15. The operator opens the ticket and sees the complete operational timeline.

16. CX events, runtime execution evidence, and business events remain linked by IDs.
```

That is the target platform. It is deliberately small, but it demonstrates a real AI-operated customer-service workflow with business actions, memory, governance, human control, outcomes, and usable operational evidence.