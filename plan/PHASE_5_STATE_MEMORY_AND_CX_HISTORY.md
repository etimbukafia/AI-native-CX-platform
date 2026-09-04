# Phase 5 - Agent State, Memory, Learning, and CX History

Status: authoritative Phase 5 revision for `AI_NATIVE_CX_PLATFORM_BUILD_PLAN.md`

## Goal

Give the support agent useful continuity across turns and sessions without allowing memory to replace authoritative business data.

Use a hybrid design:

```text
current workflow state
  -> https://github.com/etimbukafia/enterprise-agent-harness StateStore

short-term conversation continuity
  -> bounded local/runtime memory

cross-session learned support memory
  -> SenseLab AMFS

customer-service history
  -> CX platform SQLite database

authoritative commerce truth
  -> mock-business HTTP API
```

SenseLab is an external memory and continual-learning dependency. The CX application must access it through a small application-owned adapter so that deterministic tests do not require a network service and the domain does not depend directly on SenseLab SDK types.

SenseLab documentation describes versioned memory entries, provenance, confidence scoring, causal read tracking, outcome commits, history, search, and explainability. These features fit the cross-session learning use case. They do not change the ownership of workflow state, CX history, or business truth.

## Design principles

1. State is not memory.
2. Conversation memory is not customer history.
3. Learned support knowledge is not business truth.
4. A memory can influence reasoning, but it cannot authorize an action.
5. Current commerce facts must be refreshed from the mock business when they matter to a decision.
6. Outcomes may reinforce learned support knowledge, but they must not rewrite the underlying CX outcome record.
7. Memory reads and writes must be attributable to the support-agent execution that caused them.
8. The implementation must have a deterministic local memory adapter for tests.
9. Do not store private chain-of-thought.
10. Do not store complete transcripts in SenseLab merely because storage is available.

---

## Phase 5A - Workflow state

### Purpose

Track the active support workflow for the current conversation or paused execution.

Use the state boundary from https://github.com/etimbukafia/enterprise-agent-harness.

Suggested state is intentionally small:

```text
active_intent
active_order_id
active_line_id
customer_requested_resolution
awaiting_approval
```

State answers questions such as:

- Which order are we currently discussing?
- Which order line is active?
- What resolution did the customer request?
- Is the current execution waiting for approval?

State must not become a copy of the entire conversation or customer record.

### Tasks

- [ ] Define a typed workflow-state schema.
- [ ] Bind state to trusted customer, session, and conversation identity.
- [ ] Use the state mechanism from https://github.com/etimbukafia/enterprise-agent-harness.
- [ ] Persist active entity references between turns.
- [ ] Preserve paused approval state through the governed runtime path.
- [ ] Clear case-specific state when the support journey reaches the correct terminal boundary.
- [ ] Test switching from one order to another in the same conversation.
- [ ] Test ambiguous references after the active order changes.
- [ ] Test that state from one customer cannot appear in another customer's session.

---

## Phase 5B - Short-term conversation memory

### Purpose

Preserve bounded conversational continuity inside the active support journey.

Use the memory boundary from https://github.com/etimbukafia/enterprise-agent-harness for the runtime-facing memory contract. Keep this memory deliberately small.

Good short-term memory examples:

- customer already supplied the order number;
- customer means the second item in the order;
- customer prefers refund rather than replacement for this issue;
- customer said the item is needed before Friday;
- an earlier ambiguity was resolved to `ord_001`.

Do not store current business facts as durable conversational memory when those facts can change independently.

Bad examples:

```text
shipment_status = delayed
payment_status = captured
refund_is_allowed = true
order_status = shipped
```

The agent must refresh those facts through governed business tools when they are required for a decision.

### Tasks

- [ ] Define allowed short-term memory item types.
- [ ] Keep memory bounded by item count or context budget.
- [ ] Prefer compact summaries over full transcript duplication.
- [ ] Store resolved conversational references.
- [ ] Store customer-stated preferences that are relevant to the active journey.
- [ ] Define retention for conversation memory after ticket resolution.
- [ ] Test follow-up language such as:
  - "What about the other one?";
  - "Actually, refund it instead.";
  - "I mean the headphones order.".
- [ ] Test that an old remembered business state does not override a new mock-business tool result.

---

## Phase 5C - SenseLab memory adapter

### Purpose

Use SenseLab for cross-session support-agent memory and outcome-informed learning, not as a replacement for the CX database or mock-business API.

SenseLab website: https://www.sense-lab.ai/

### Application boundary

Create an application-owned port such as:

```text
cx_platform/memory/
  port.py
  local.py
  senselab/
    __init__.py
    adapter.py
    http.py
    mapping.py
```

The support application depends on the port. The `senselab/` package contains the external integration, with transport and payload mapping kept separate from adapter orchestration.

A small contract is enough. Conceptually:

```text
search_relevant(...)
write_memory(...)
record_context(...)
commit_outcome(...)
explain_usage(...)
```

Do not mirror the entire SenseLab API.

### Test adapter

`local.py` must provide a deterministic implementation for unit tests and CI.

CI must not require:

- a SenseLab account;
- an API key;
- internet access.

### Tasks

- [ ] Define a small `MemoryPort` owned by the CX application.
- [ ] Implement deterministic `LocalMemory`.
- [ ] Implement `SenseLabMemory` behind the port.
- [ ] Load SenseLab credentials from environment configuration only.
- [ ] Add finite network timeouts and safe failure behavior.
- [ ] Ensure SenseLab unavailability does not make basic customer support unusable.
- [ ] Add integration tests using a fake/injected SenseLab client where possible.
- [ ] Add one opt-in live integration smoke test outside normal CI.

---

## Phase 5D - Customer-specific cross-session memory

### Purpose

Retain a small set of durable customer preferences or interaction facts that are useful in future support conversations.

Examples that can be appropriate:

```text
customer generally prefers refunds over replacements
customer prefers concise support explanations
customer asked support to avoid a particular contact method
```

These are not commerce facts and are not substitutes for the current ticket or customer record.

### Scope

Use a customer-scoped entity path or equivalent external-memory namespace.

The application must preserve customer separation. A support session for one customer must not retrieve another customer's private memory.

For v0.1, keep this feature narrow. Do not attempt to infer a rich customer profile from every conversation.

### Write policy

Only promote information to cross-session customer memory when it is:

- explicitly stated or clearly confirmed by the customer;
- useful beyond the current turn;
- safe to reuse;
- not authoritative commerce state;
- not unnecessary sensitive data.

### Tasks

- [ ] Define the allowed customer-memory categories.
- [ ] Define customer-scoped memory keys/entity paths.
- [ ] Require trusted `customer_id` when reading or writing customer memory.
- [ ] Record provenance that links the memory write to conversation/execution evidence.
- [ ] Avoid automatic promotion of every conversation summary.
- [ ] Add tests for cross-session recall.
- [ ] Add tests for customer isolation.
- [ ] Add tests for conflicting or superseded preferences.

---

## Phase 5E - Shared support-agent learning

### Purpose

Allow the customer-support agent to accumulate useful operational knowledge across many support interactions.

This is the part of SenseLab that matters most to the broader project.

Examples:

```text
customers frequently misunderstand split-shipment wording
shipping-outage explanations that include a clear next check reduce repeated questions
customers with damaged-item cases often need the affected order line confirmed first
```

These are learned support patterns. They are not policy and they cannot grant authority.

### Memory types

Keep the first implementation simple and distinguish at least:

- `experience`: what happened in a support interaction;
- `belief`: a learned hypothesis or pattern that may change;
- `fact`: only stable non-business knowledge that is actually appropriate to treat as a fact.

Do not store current order, payment, shipment, refund, or customer-account state as shared support facts.

### Retrieval

Retrieve only a small number of relevant memories for a support execution.

Apply simple constraints such as:

- relevant skill or issue type;
- minimum confidence where supported;
- bounded result count;
- current support context.

Do not dump the whole memory space into the model context.

### Tasks

- [ ] Define shared support-memory namespaces/entity paths.
- [ ] Define typed memory payloads used by the CX application.
- [ ] Map support skills to relevant memory searches.
- [ ] Bound retrieved results.
- [ ] Preserve memory IDs/version/provenance in execution evidence where possible.
- [ ] Treat retrieved memory as advisory context, not policy.
- [ ] Add tests where a learned pattern helps but cannot override a business tool result.

---

## Phase 5F - Outcome-informed learning

### Purpose

Connect real CX outcomes to the learned memories that influenced a support execution.

SenseLab supports causal read tracking and outcome commits. Use this carefully.

The CX platform remains the owner of the outcome record. SenseLab receives a reference to that outcome so it can adjust or annotate the memories that were used.

Example flow:

```text
support execution
  -> reads relevant SenseLab memories
  -> uses governed business tools
  -> customer receives resolution
  -> CX platform records structured outcome
  -> optional CSAT arrives
  -> application commits outcome reference to SenseLab
```

### Outcome mapping

Do not directly equate every CX result with "good" or "bad" memory.

Start with a small explicit mapping based on outcomes we truly observe.

Possible signals:

```text
resolved without escalation
resolved after escalation
unresolved
customer abandoned
positive CSAT
negative CSAT
action rejected by policy
tool/dependency failure
```

A policy rejection is not automatically evidence that a remembered support pattern was wrong. A dependency outage is not automatically a negative learning signal either.

### Tasks

- [ ] Define which CX outcomes are eligible for SenseLab outcome commits.
- [ ] Map CX outcome IDs to external outcome references.
- [ ] Keep the raw CX outcome immutable in the CX database.
- [ ] Commit SenseLab outcomes only after the corresponding CX outcome exists.
- [ ] Add CSAT as a separate signal rather than rewriting the initial resolution result.
- [ ] Record whether outcome propagation succeeded or failed.
- [ ] Test that memory/outcome integration failures do not corrupt CX outcomes.

---

## Phase 5G - Memory provenance and explainability

### Purpose

Make it possible to answer:

- Which memories did this execution read?
- Which memory versions were used?
- Which CX outcome later reinforced or weakened them?
- Was a memory customer-specific or shared support knowledge?

SenseLab exposes history and causal/explainability concepts. Preserve useful references without copying SenseLab's entire internal model into CX persistence.

### Suggested CX-side evidence

Store small reference records such as:

```text
execution_id
memory_provider
memory_entry_id_or_key
memory_version
memory_scope
operation
occurred_at
```

Do not duplicate complete memory payloads unless there is a concrete audit need.

### Tasks

- [ ] Add memory-read/write references to CX execution evidence.
- [ ] Link outcome commits to CX outcome IDs.
- [ ] Make memory provider visible in operator/debug inspection.
- [ ] Add a safe memory-explain view for the demo if inexpensive.
- [ ] Do not expose private chain-of-thought.

---

## Phase 5H - CX customer history remains separate

### Purpose

Keep durable service records in the CX platform even when SenseLab is enabled.

The CX database remains authoritative for:

- previous tickets;
- previous escalations;
- previous resolutions;
- prior CSAT;
- conversation/message history;
- structured outcomes.

If the support agent needs this history, expose it through a typed CX-owned read service/tool rather than copying the whole history into SenseLab.

### Tasks

- [ ] Keep CX history in SQLite.
- [ ] Add a small typed history query only if a support scenario needs it.
- [ ] Do not mirror every ticket/message into SenseLab.
- [ ] Link memories to source CX records through IDs/provenance when applicable.

---

## Phase 5I - Failure and fallback behavior

### Goal

SenseLab improves the agent but must not become a single point of failure for v0.1 customer support.

Expected fallback:

```text
SenseLab available
  -> retrieve bounded cross-session memory
  -> continue normal governed execution

SenseLab unavailable
  -> record memory dependency failure
  -> continue with workflow state + current conversation + business tools
```

Do not invent remembered information when memory retrieval fails.

### Tasks

- [ ] Define timeout behavior.
- [ ] Define safe empty-memory fallback.
- [ ] Emit a CX operational event for memory dependency failures if useful.
- [ ] Ensure memory failure does not bypass policy or approval.
- [ ] Test support behavior with SenseLab disabled.
- [ ] Test support behavior with SenseLab timeout/failure.

---

## Phase 5J - Acceptance tests

The Phase 5 implementation is complete when the following behaviors pass.

### Same-session continuity

```text
Customer: My headphones are damaged.
Agent identifies ord_001 / line_002.
Customer: Actually, refund it instead.
```

The agent retains the active item reference without asking the customer to start over.

### Cross-session customer preference

A confirmed durable preference can be recalled in a later support session for the same customer, but never for another customer.

### Fresh business truth beats memory

A prior memory says a shipment was delayed. The mock business now reports delivered. The agent uses the current business tool result.

### Shared support learning

A relevant high-confidence support pattern can be supplied as advisory context to a later execution.

### Policy remains authoritative

A memory suggests that refunds usually resolve a case. The current refund policy denies the action. The agent follows policy.

### Outcome linkage

A support execution reads a SenseLab memory, produces a CX outcome, and the application can link the later outcome commit back to the memory/execution evidence.

### Graceful degradation

SenseLab is unavailable. The customer can still complete a normal support journey using current conversation context and business tools.

---

## Exit criteria

Phase 5 is complete when:

- workflow state is owned through https://github.com/etimbukafia/enterprise-agent-harness;
- short-term conversational continuity is bounded;
- SenseLab is integrated behind an application-owned adapter;
- deterministic tests work without SenseLab or network access;
- customer-specific cross-session memory is isolated;
- shared support learning is advisory rather than authoritative;
- CX outcomes can be referenced as learning signals;
- CX history remains authoritative in the CX database;
- current business truth always overrides stale memory;
- memory failure does not prevent the basic customer-support workflow.
