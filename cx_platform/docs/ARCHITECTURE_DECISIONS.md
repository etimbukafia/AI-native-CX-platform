# CX Platform Architecture Decisions

Status: accepted Phase 0 decisions

These decisions keep the small AI-native CX platform coherent and prevent later phases from creating parallel ownership or infrastructure.

## AD-001 - Canonical CX package is `cx_platform/`

Decision:

Use the top-level `cx_platform/` directory as the canonical CX application package.

Do not create `src/cx_platform`.

Reason:

The repository already has a dedicated `cx_platform/` package. Keeping one canonical location avoids duplicate application trees and import ambiguity.

Consequence:

All new CX application code is added under `cx_platform/`.

The existing `src/mock_business/` package remains separate.

---

## AD-002 - Mock business is external from the CX application's point of view

Decision:

The CX platform talks to the reference mock business through HTTP.

It does not import mock-business repositories, service classes, or database objects to perform customer-service work.

Reason:

The mock business owns commerce truth and intentionally represents an external enterprise system.

Consequence:

Tests can use real HTTP integration or a typed fake adapter, but production-path CX code never reaches into mock-business persistence.

---

## AD-003 - Use https://github.com/etimbukafia/enterprise-agent-harness in process

Decision:

Consume https://github.com/etimbukafia/enterprise-agent-harness as a Python library inside the CX backend for v0.1.

Do not deploy it as a separate agent-runtime service.

Reason:

A separate service would add network contracts, deployment coordination, and failure modes without improving the portfolio goal. The repository already exposes a reusable library/runtime boundary.

Consequence:

The CX application composes the runtime, agent definition, capabilities, tools, policy, state, and provider adapters in its composition root.

The architecture can later move the runtime behind a service adapter if a real deployment requires it, but v0.1 has one implementation path.

---

## AD-004 - One support agent for v0.1

Decision:

Build one customer-support agent with multiple registered capabilities.

Do not build supervisor/specialist multi-agent orchestration.

Reason:

The business scenarios test customer-service capability breadth, not multi-agent topology.

Consequence:

Capability boundaries remain visible in the registry without introducing delegation complexity.

---

## AD-005 - Capabilities, not local skills

Decision:

Use capability contracts from https://github.com/etimbukafia/enterprise-agent-harness.

Do not add a separate `Skill` framework inside the CX platform.

Reason:

Capabilities already provide the correct enterprise-level abstraction for what the agent can accomplish.

Consequence:

Tools remain atomic operations. Capabilities group the business jobs that the support agent can perform.

---

## AD-006 - Separate CX and mock-business persistence

Decision:

Use a CX-owned SQLite database for CX records and keep the mock-business SQLite database separate.

Reason:

The two systems own different truth and lifecycle boundaries.

Consequence:

No cross-database joins or shared tables are part of application behavior.

---

## AD-007 - SQLite is enough for v0.1

Decision:

Use SQLite for durable CX records.

Do not add PostgreSQL, Redis, or a message broker.

Reason:

The application is a small local/demo platform. SQLite supports the required persistence without infrastructure that does not improve the demonstration.

Consequence:

Repository interfaces should keep persistence replaceable, but implementation remains simple.

---

## AD-008 - Hybrid memory with clear authority boundaries

Decision:

Use:

```text
workflow state
  -> https://github.com/etimbukafia/enterprise-agent-harness

short-term conversation memory
  -> bounded runtime/local memory

cross-session learned memory
  -> SenseLab through a CX-owned adapter

CX history
  -> CX SQLite

business truth
  -> mock-business HTTP API
```

Reason:

These data classes have different update, authority, and retention semantics.

Consequence:

A memory value never overrides a fresh business-tool result or a policy decision.

---

## AD-009 - SenseLab is optional at runtime

Decision:

SenseLab must improve continuity/learning but must not be required for basic customer support.

Reason:

An external memory dependency should not make the reference support journey unavailable.

Consequence:

The CX memory port has a deterministic local implementation and a safe empty-memory fallback.

Normal CI does not require SenseLab credentials or network access.

---

## AD-010 - Synchronous request/response first

Decision:

Implement the initial customer message flow as a normal synchronous HTTP request that returns a completed response or explicit paused/escalated state.

Streaming is optional later.

Reason:

Streaming is UX transport complexity, not a core architecture requirement.

Consequence:

The first implementation optimizes correctness and evidence correlation before token streaming.

---

## AD-011 - CX events, runtime traces, and business events remain distinct

Decision:

Keep three evidence streams:

```text
CX operational events
runtime execution trace
mock-business events
```

Link them through identifiers.

Do not copy one stream wholesale into another.

Reason:

Each stream describes a different level of the system.

Consequence:

CX Autopilot or another external consumer can reconstruct the journey without semantic duplication.

---

## AD-012 - Application owns CX outcomes

Decision:

The CX platform records the authoritative support outcome and CSAT.

SenseLab can receive outcome references/signals for learning after the CX outcome exists.

Reason:

Learning systems should not own or mutate the operational system of record.

Consequence:

Outcome propagation to external memory is a secondary operation and failure cannot corrupt the CX record.

---

## AD-013 - Business actions execute only through governed tools

Decision:

Customer-support writes such as cancellation, return, and refund are invoked through tools governed by https://github.com/etimbukafia/enterprise-agent-harness.

Reason:

The runtime must apply typed validation, permissions, policy, approval, and trace behavior consistently.

Consequence:

The CX service does not directly call a mock-business write endpoint as a shortcut after a model suggests an action.

---

## AD-014 - Approval uses runtime pause/resume

Decision:

Use the exact approval pause/resume semantics from https://github.com/etimbukafia/enterprise-agent-harness.

The CX platform only stores the application-facing approval reference and operator decision needed to present the workflow.

Reason:

A second approval engine would create inconsistent authorization semantics.

Consequence:

The reviewed action remains the exact action that resumes.

---

## AD-015 - Human escalation is small and terminal in v0.1

Decision:

Represent escalation as a structured CX record and ticket state. A full human-agent workspace is not required.

Reason:

The demo needs a credible safe handoff boundary, not a contact-center desktop.

Consequence:

The operator UI can inspect escalations and approvals without implementing live human chat takeover.

---

## AD-016 - Customer identity is a demo binding, not authentication

Decision:

Use a seeded customer selector or similarly explicit demo identity mechanism.

Reason:

Real authentication and SSO do not improve the target agent/CX architecture demonstration.

Consequence:

The system must still enforce customer/session isolation in application and runtime state, but it does not claim production identity security.

---

## AD-017 - No ORM unless implementation proves it is useful

Decision:

Start CX persistence with the standard SQLite boundary and explicit typed repository mapping.

Reason:

The domain is small and the existing mock business already demonstrates that direct SQLite can stay understandable.

Consequence:

An ORM is not forbidden forever, but adding it requires a concrete implementation problem that it solves.

---

## AD-018 - No empty architecture scaffolding

Decision:

Create package subdirectories when their implementation phase begins.

Do not create empty `api/`, `domain/`, `services/`, `memory/`, or similar trees during Phase 0.

Reason:

The architecture baseline should guide real code, not create speculative structure.

Consequence:

Phase 0 contains documentation and accepted decisions only, plus the already-existing package marker.

---

## AD-019 - No private model reasoning in durable evidence

Decision:

Store customer-visible messages, typed state, tool records/references, runtime trace evidence, structured handoff summaries, memory references, and outcomes.

Do not store hidden chain-of-thought.

Reason:

Operational explainability comes from observable actions and evidence, not private reasoning text.

Consequence:

Operator/debug views use structured trace/event data.

---

## AD-020 - External analysis remains external

Decision:

Do not implement CX Autopilot inside the AI-native CX platform.

Reason:

The CX platform is the operational evidence-producing system. CX Autopilot is a later consumer that analyzes those operations and proposes improvements.

Consequence:

Phase 14 provides stable read/export boundaries rather than embedding analysis/optimization logic in this package.
