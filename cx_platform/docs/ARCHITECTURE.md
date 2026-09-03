# CX Platform Architecture Baseline

Status: accepted Phase 0 baseline

## 1. Purpose

The AI-native CX platform is a small customer-service application where a human customer talks to one AI support agent. The agent can inspect and act on the reference commerce business through governed tools. The application records enough operational evidence to explain what happened and to support later analysis.

The platform is intentionally not a production contact-center suite.

## 2. Canonical package boundary

The top-level `cx_platform/` directory is the canonical CX application package.

Do not create `src/cx_platform` in parallel.

Current repository ownership is:

```text
AI-native-CX-platform/
├── cx_platform/          # AI-native CX application
├── src/mock_business/    # reference commerce business
├── tests/                # repository tests
├── plan/                 # build plans
└── docs/                 # mock-business-level documentation
```

The two application domains remain separate even though they are in one repository.

The CX platform must interact with the mock business through its HTTP API. It must not import mock-business repositories, services, or database objects as an application shortcut.

## 3. External dependencies

### Governed agent runtime

Use https://github.com/etimbukafia/enterprise-agent-harness as an in-process Python library.

The CX platform owns the customer-service application and supplies application-specific agents, capabilities, tools, identity context, and adapters.

https://github.com/etimbukafia/enterprise-agent-harness owns generic agent execution concerns such as:

- provider boundaries;
- governed runtime execution;
- typed tool registration and invocation;
- capability and agent registries;
- permission and policy enforcement;
- approval pause/resume mechanics;
- workflow state;
- bounded runtime memory;
- audit and execution traces.

The CX platform must not implement an alternate generic tool loop, permission engine, capability registry, approval engine, or trace model.

### Cross-session memory

SenseLab at https://www.sense-lab.ai/ is an optional external memory and learning dependency.

The CX platform accesses SenseLab through a CX-owned memory adapter. Application/domain code must not depend directly on SenseLab SDK types.

SenseLab is not authoritative for business state, ticket history, policy, identity, or action authorization.

### Reference mock business

The reference commerce business is deployed locally as a separate HTTP application process for the demo.

Its API is the authoritative interface for current commerce state and commerce actions.

## 4. Runtime topology

The smallest useful local topology is:

```text
Customer web UI
      |
      v
CX Platform API
      |
      +--> CX SQLite database
      |
      +--> https://github.com/etimbukafia/enterprise-agent-harness
      |       |
      |       +--> model provider adapter
      |       +--> governed CX/business tools
      |
      +--> SenseLab adapter (optional)
      |
      +--> Mock Business HTTP API
              |
              +--> mock-business SQLite database
```

The CX API and mock-business API are separate processes for the demo because this preserves the external-system boundary without introducing microservices beyond what the domain already requires.

No message broker, cache, service mesh, or distributed workflow engine is required.

## 5. Ownership matrix

| Data or behavior | Owner | Notes |
| --- | --- | --- |
| Customer chat UX | CX platform | Customer-facing experience |
| Conversation | CX platform | Durable support interaction |
| Message | CX platform | Customer, AI, system, or future human message |
| Ticket | CX platform | Support case lifecycle |
| Escalation | CX platform | Human handoff record |
| Operator approval view | CX platform | Presentation and operator decision capture |
| Governed approval mechanics | https://github.com/etimbukafia/enterprise-agent-harness | Exact action pause/resume boundary |
| CX outcome | CX platform | Authoritative support result |
| CSAT | CX platform | Customer feedback record |
| CX operational event | CX platform | Operational journey evidence |
| Agent execution trace | https://github.com/etimbukafia/enterprise-agent-harness | Detailed governed execution evidence |
| Workflow state | https://github.com/etimbukafia/enterprise-agent-harness | Active execution/session state |
| Short-term runtime memory | https://github.com/etimbukafia/enterprise-agent-harness | Bounded continuity |
| Cross-session learned memory | SenseLab through CX adapter | Advisory memory only |
| Previous CX tickets/outcomes | CX platform | Durable service history |
| Customer account truth | Mock business | Read through HTTP |
| Orders/order lines | Mock business | Read through HTTP |
| Payments | Mock business | Read through HTTP |
| Shipments | Mock business | Read through HTTP |
| Fulfillment issues | Mock business | Read through HTTP |
| Returns/refunds | Mock business | Read/write through HTTP |
| Commerce policy | Mock business | Authoritative business rule data |
| Commerce knowledge | Mock business | Operational guidance |
| Business events | Mock business | Observable commerce activity |

## 6. Identifier contract

IDs must be opaque strings outside the component that creates them.

### CX-owned identifiers

```text
customer_id
conversation_id
ticket_id
message_id
escalation_id
outcome_id
csat_id
```

`customer_id` is the CX-local customer binding ID. It maps to an external mock-business customer ID.

### Runtime-owned identifiers

```text
session_id
execution_id
trace identifiers exposed by the runtime
approval request identifiers exposed by the runtime
```

The CX platform stores runtime IDs as references. It does not regenerate or reinterpret them.

### Business-owned identifiers

Examples:

```text
external_customer_id
order_id
line_id
payment_id
shipment_id
return_id
refund_id
business_event_id
policy_id
article_id
```

The CX platform preserves these values exactly as returned by the mock-business API.

### Required correlation chain

At minimum, every support execution must allow navigation through:

```text
customer_id
  -> ticket_id
  -> conversation_id
  -> customer message_id
  -> execution_id
  -> AI message_id
```

When tools act on business records, execution evidence must retain the relevant business IDs.

## 7. Core data distinction

Four data classes must stay separate.

### Workflow state

Temporary active execution facts, for example:

```text
active_intent
active_order_id
active_line_id
customer_requested_resolution
awaiting_approval
```

Owned through https://github.com/etimbukafia/enterprise-agent-harness.

### Memory

Useful conversational or learned context.

Short-term memory is bounded runtime continuity. Cross-session memory is advisory context through the SenseLab adapter.

Memory must not authorize actions or replace current business reads.

### CX history

Durable service records:

- conversations;
- messages;
- tickets;
- escalations;
- outcomes;
- CSAT.

Owned by the CX platform.

### Business truth

Current commerce facts and rules.

Examples:

- current order status;
- current shipment status;
- payment state;
- refund/return result;
- cancellation result;
- applicable business policy.

Owned by the mock business.

When memory and a fresh business-tool result conflict, the fresh business result wins.

## 8. Customer-message request flow

The normal synchronous request path is:

```text
1. Customer sends message.
2. CX API authenticates only the demo/customer binding available to v0.1.
3. CX service loads conversation and ticket.
4. CX service stores the customer message.
5. CX service emits `message.customer_received`.
6. CX service creates an `execution_id` and trusted runtime context.
7. CX service invokes the agent built with
   https://github.com/etimbukafia/enterprise-agent-harness.
8. Runtime/provider may request governed tools.
9. Tool handlers call CX-owned services or the mock-business HTTP adapter.
10. Runtime applies tool, policy, permission, and approval controls.
11. Runtime returns a final, paused, escalated, or failed outcome.
12. CX service records the application-visible result.
13. CX service stores the AI/system message when applicable.
14. CX service updates ticket state when required.
15. CX service emits CX operational events.
16. API returns the customer-visible response/state.
```

The CX service does not execute a proposed business action outside the governed runtime path.

## 9. Approval pause/resume flow

Approval is used only when an exact action requires it.

```text
1. Agent proposes a governed write/action.
2. https://github.com/etimbukafia/enterprise-agent-harness determines that approval is required.
3. Runtime creates an exact approval request and pauses execution.
4. CX platform stores an approval reference for operator presentation.
5. Ticket moves to `WAITING_APPROVAL`.
6. CX platform emits `approval.requested`.
7. Operator approves or rejects the exact request.
8. CX platform records the operator decision.
9. CX platform submits the decision to the runtime approval boundary.
10. If approved, CX platform resumes the same `execution_id`.
11. Runtime validates approval identity/digest/expiry and resumes from the paused step.
12. CX platform records the final result and ticket transition.
```

The model cannot replace the approved action during resume.

The CX platform must not implement a parallel approval engine.

## 10. Human escalation flow

Escalation is a CX outcome and handoff record.

Initial structured reasons:

```text
CUSTOMER_REQUESTED_HUMAN
ACTION_REQUIRES_HUMAN
BUSINESS_SYSTEM_UNAVAILABLE
UNSUPPORTED_REQUEST
AMBIGUOUS_ACCOUNT
AGENT_UNCERTAIN
POLICY_CONFLICT
```

Flow:

```text
1. Runtime or CX application reaches an escalation condition.
2. CX service creates an Escalation record.
3. Record includes reason, concise handoff summary, relevant entity IDs,
   actions already attempted, and execution reference.
4. Ticket moves to `ESCALATED`.
5. CX service emits `ticket.escalated`.
6. Customer receives a clear handoff response.
```

The handoff summary may contain concise operational context. It must not contain private chain-of-thought.

For v0.1, escalation can be terminal from the customer chat. A full human-agent desktop is not required.

## 11. CX operational event baseline

CX events are append-only application evidence.

Minimum fields:

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

Fields that do not apply can be null/absent according to the final typed contract.

Initial event vocabulary:

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

memory.read
memory.write
memory.dependency_failed
```

Only emit `agent.capability_selected` if reliable runtime evidence exists for that fact.

### Event boundary

CX events do not replace:

- detailed execution traces from https://github.com/etimbukafia/enterprise-agent-harness;
- mock-business events.

Do not duplicate either stream wholesale. Use correlation IDs and evidence references.

### External evidence read boundary

The CX API exposes typed reads for CX-owned records:

```text
GET /events
GET /tickets
GET /tickets/{ticket_id}
GET /conversations/{conversation_id}
GET /executions/{execution_id}
GET /outcomes
GET /metrics
```

These reads support evidence consumers without direct SQLite access. Ticket,
conversation, message, escalation, outcome, CSAT, and CX event records remain
CX-owned. Execution reads return only the CX reference to a Harness execution.

The evidence chain uses IDs, not copied streams:

```text
customer message -> conversation -> ticket -> execution reference
  -> CX tool event -> mock-business record/event -> agent message
  -> outcome -> CSAT
```

The Harness owns detailed traces, approval execution, and workflow state. The
mock business owns commerce truth and business events. SenseLab owns external
memory payloads; CX may store safe provenance references. CX does not copy full
Harness traces, business-event streams, or memory payloads into its database.

The small metrics read is reproducible from CX conversations, terminal outcomes,
tool events, approval records, and submitted CSAT records. A turn is one stored
customer message. A tool failure is only an `agent.tool_failed` event. Approval
rate uses decided approval records. Resolution and escalation rates use terminal
outcomes as their denominator.

Metric definitions are:

- conversation count: all persisted CX conversations;
- resolution rate: resolved terminal outcomes divided by terminal outcomes;
- escalation rate: escalated terminal outcomes divided by terminal outcomes;
- average turns: customer messages divided by persisted conversations;
- tool failure rate: failed tool events divided by tool-call events;
- approval rate: approved records divided by decided approval records;
- average submitted CSAT: the mean of submitted scores only;
- outcome distribution: terminal outcomes grouped by resolution code.

## 12. Persistence baseline

Use one SQLite database for CX-owned durable application records.

Use a separate SQLite database for the mock business.

Do not combine them into one schema or use cross-database joins as application behavior.

The CX database will initially store:

- customer bindings;
- conversations;
- messages;
- tickets;
- escalations;
- application-facing approval references;
- execution-link records;
- outcomes;
- CSAT;
- CX operational events;
- memory reference records where required for provenance.

Use a small explicit schema-version mechanism.

No ORM is required unless implementation pressure demonstrates a concrete need.

## 13. Package direction

The intended CX package direction is:

```text
cx_platform/
├── api/            # HTTP routes and request/response mapping
├── domain/         # typed CX entities and lifecycle rules
├── services/       # application use cases
├── persistence/    # CX SQLite repositories
├── integrations/   # mock-business and other external adapters
├── tools/          # https://github.com/etimbukafia/enterprise-agent-harness tool definitions/handlers
├── agent/          # CX-specific agent configuration/capability assembly
├── memory/         # LocalMemory + SenseLab adapter behind CX port
└── main.py         # application composition root
```

These directories should be created only when their phase begins. Phase 0 does not add empty architecture scaffolding.

Dependency direction:

```text
api -> services -> domain
              -> persistence ports/adapters
              -> integration ports/adapters
              -> governed agent boundary
```

Domain models must not import FastAPI, HTTPX, SenseLab SDKs, or mock-business internals.

## 14. Error boundary

External dependency failures must become explicit application results.

Examples:

- mock-business 404 -> requested business entity is unavailable/not found;
- mock-business 422 -> authoritative business-rule rejection;
- mock-business 503/timeout -> business dependency unavailable;
- model/provider failure -> agent execution failure;
- SenseLab failure -> memory dependency failure with empty-memory fallback;
- approval rejection -> reviewed action did not execute.

Do not convert dependency failures into invented customer/business facts.

## 15. Evidence and observability rule

Every meaningful application claim should be attributable to one of:

- customer message;
- CX durable record;
- runtime trace/evidence;
- governed tool result;
- mock-business record/event;
- external memory reference;
- operator approval decision;
- CX outcome/CSAT.

The application does not store hidden model reasoning.

## 16. v0.1 non-goals

Do not build:

- voice, email, or WhatsApp channels;
- omnichannel routing;
- workforce management;
- human-agent desktop beyond small review/approval views;
- real authentication/SSO;
- production multi-tenancy;
- production-grade RBAC;
- Kafka, Redis, Kubernetes, or microservices;
- a generic workflow engine;
- a second agent runtime;
- multiple support agents or supervisor orchestration;
- real payment/CRM integrations;
- a vector database without a demonstrated retrieval need;
- custom business/scenario builder UI;
- CX Autopilot itself.

## 17. Phase 0 completion test

Phase 0 is complete when all later implementation can follow these rules without unresolved ownership questions:

```text
CX operations        -> cx_platform/
commerce truth       -> mock-business HTTP API
agent execution      -> https://github.com/etimbukafia/enterprise-agent-harness
cross-session memory -> SenseLab through CX adapter
CX durable history   -> CX SQLite
agent trace           -> https://github.com/etimbukafia/enterprise-agent-harness
business events       -> mock business
CX events             -> CX platform
```
