# Instructions

These instructions capture the project decisions and constraints that matter when working in this repository.

## Writing

Always talk in ASD-STE100 Issue 9 Simplified Technical English.

### Key rules

- Use approved words only. Use one word for one idea.
- Write short sentences. Use 20 words or less for instructions.
- Use active voice.
- Write short paragraphs. Keep one topic in each paragraph.
- Prefer concrete product and architecture terms over buzzwords.

The goal of writing is easy reading and clear communication.

## Repository Structure

- `cx_platform/` is the canonical package for the CX application.
- Do not create `src/cx_platform`.
- `src/mock_business/` is the reference commerce business.
- Treat `src/mock_business/` as an external business system from the CX application's point of view.
- The CX platform must use the mock-business HTTP API. It must not read the mock-business database directly.
- Keep the mock business and CX platform as separate modules with clear ownership.
- Do not create empty package trees for future phases before code needs them.

## Architecture Sources of Truth

Read these files before making architecture changes:

- `plan/AI_NATIVE_CX_PLATFORM_BUILD_PLAN.md`
- `cx_platform/docs/ARCHITECTURE.md`
- `cx_platform/docs/ARCHITECTURE_DECISIONS.md`
- `cx_platform/docs/PHASE_0_COMPLETION.md`

For memory work, also read:

- `plan/PHASE_5_STATE_MEMORY_AND_CX_HISTORY.md`

If implementation and documentation conflict, do not silently choose one. Stop and report the conflict.

## External Systems

Use https://github.com/etimbukafia/enterprise-agent-harness for governed agent execution.

The CX platform must consume the harness. It must not create another general-purpose agent runtime.

The harness owns generic concerns such as:

- agent execution;
- typed tool contracts;
- tool and capability registries;
- provider boundaries;
- permissions and policies;
- approval pause and resume;
- workflow state;
- runtime memory boundaries;
- audit and trace evidence.

Use the mock-business HTTP API for commerce truth.

Use SenseLab only through the CX-owned memory adapter defined in Phase 5.

Do not let CX domain code depend directly on SenseLab SDK types.

## Data Ownership Rules

Keep these concepts separate.

### Workflow state

Use workflow state for the active support task.

Examples:

- active intent;
- active order;
- active order line;
- requested resolution;
- approval wait state.

Use the state boundary from https://github.com/etimbukafia/enterprise-agent-harness.

### Short-term memory

Use bounded memory for conversation continuity.

Examples:

- resolved references;
- confirmed customer preferences;
- compact turn summaries;
- unresolved customer goals.

Do not use memory as current business truth.

### Cross-session memory

Use SenseLab only for approved customer memory and shared support learning.

Treat learned memory as advisory context.

Memory must not grant authority or override business policy.

### CX history

The CX platform owns durable service history.

Examples:

- tickets;
- conversations;
- messages;
- escalations;
- outcomes;
- CSAT.

### Business truth

The mock business owns current commerce truth.

Examples:

- order state;
- payment state;
- shipment state;
- refund eligibility;
- return eligibility;
- policies.

When business truth matters, read it through a governed tool.

Fresh business data must override stale memory.

## Architecture Rules

- Do not blindly write code.
- Research current documentation when an external contract is unclear.
- Use modular architecture with clear separation of concerns.
- Keep data flow explicit.
- Prefer clear names, small functions, and straightforward control flow.
- Add an abstraction only when it represents a real boundary or reduces meaningful complexity.
- Prefer efficient implementation over quick hacks.
- Keep code easy to test and explain.
- An engineer should follow behavior from API to service, adapter, external call, and persistence without hidden magic.
- Do not preserve backward compatibility during this build.
- Prefer one current forward-only design.
- Avoid technical debt, temporary compatibility layers, duplicate architectures, and stopgap solutions.
- Prefer the simplest implementation that fully meets the current phase.
- Avoid speculative configuration and indirection.
- Keep external dependencies behind adapters.
- Use typed models at system boundaries.
- Preserve stable IDs and evidence links across systems.
- Do not duplicate business rules that belong to the mock business.
- Do not duplicate runtime rules that belong to https://github.com/etimbukafia/enterprise-agent-harness.
- Do not implement later phases without an explicit request.
- When there is a meaningful implementation choice that the accepted architecture does not resolve, stop and ask first.

## Phase Discipline

Work only within the requested phase or phase batch.

Do not add future features because they might be useful later.

For each phase:

1. Read the phase plan and architecture files.
2. Inspect the current repository before coding.
3. Inspect external contracts when the phase depends on them.
4. Implement the smallest complete design.
5. Run the full relevant test suite.
6. Report unresolved issues before starting the next phase.

## Tool and Business Action Rules

- Tools must have typed input and output contracts.
- Use stable tool IDs and versions.
- Classify read, write, and action tools correctly.
- Business tool handlers must call the mock-business adapter.
- Do not let tools access mock-business persistence directly.
- Do not infer successful side effects before the business call confirms success.
- Do not convert transport failures into business facts.
- Do not let a model grant itself a tool, permission, policy exception, or approval.

## Approval and Escalation Rules

- Use the approval mechanisms from https://github.com/etimbukafia/enterprise-agent-harness.
- Resume the exact approved action. Do not create a replacement action after approval.
- Keep CX approval records as operator-facing records, not as a second approval engine.
- Use structured escalation reasons.
- Keep escalation summaries operational and concise.
- Do not store private chain-of-thought.

## Evidence and Events

Keep three evidence streams separate:

- CX operational events;
- runtime traces from https://github.com/etimbukafia/enterprise-agent-harness;
- mock-business events.

Link them with stable IDs.

Do not copy all runtime trace records into CX events.

Do not copy all business events into CX events.

Do not store raw provider prompts or private reasoning in CX event records.

## Testing

- Do not over-test.
- Each test must protect a user outcome, security boundary, data-integrity rule, external contract, or cost rule.
- Test behavior through a public boundary.
- Prefer API, database, adapter, provider, and UI behavior over private helper tests.
- Do not read source files from tests.
- Do not assert module inventories, import text, private attributes, object wiring, or arbitrary constants.
- Assert a provider or tool call count only when deduplication, reliability, or cost makes the count important.
- Remove a test when a stronger user-facing or integration test covers the same behavior.
- A source refactor should not require test changes when behavior stays the same.
- Use small test data and deterministic control flow.
- Do not add stress tests unless they protect a measured limit or safety boundary.
- Every test name must state the behavior it protects.
- Delete tests that cannot justify their presence.
- A passing test count does not justify a test.
- Prefer one current forward-only schema baseline over a long migration chain.
- CI must not require a live model, SenseLab account, or external network service.
- Use deterministic adapters or fake clients for automated tests.
- Live integration tests must be opt-in.

## v0.1 Non-Goals

Do not add these unless the plan changes explicitly:

- voice support;
- email support;
- WhatsApp support;
- omnichannel routing;
- workforce management;
- real authentication or SSO;
- production multi-tenancy;
- complex RBAC;
- microservices;
- Kafka;
- Redis;
- Kubernetes;
- a generic workflow builder;
- a generic prompt-management platform;
- multiple support agents;
- supervisor-agent orchestration;
- custom business builders;
- custom scenario-builder UI;
- real payment processing;
- production CRM integrations;
- production-scale observability infrastructure;
- CX Autopilot itself.

## Completion Standard

Before declaring work complete:

- run the full relevant test suite;
- run compile or import checks;
- verify no parallel package or architecture was introduced;
- verify business rules remain in the mock business;
- verify runtime rules remain in https://github.com/etimbukafia/enterprise-agent-harness;
- verify new external dependencies are behind adapters;
- verify documentation still matches the implementation;
- report exact test results and any unresolved issue.
