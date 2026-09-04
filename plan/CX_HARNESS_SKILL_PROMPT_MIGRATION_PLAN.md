# CX Harness Skill and Prompt Migration Plan

Status: proposed implementation plan

## 1. Goal

Migrate the CX platform to the current Enterprise Agent Harness artifact model.

Harness repository:

https://github.com/etimbukafia/enterprise-agent-harness

The CX platform must use these current Harness concepts:

```text
Agent
Skill
Prompt
Tool
Policy
```

The migration is forward-only.

Do not keep the old Capability API in the CX application.

The target support-agent graph is:

```text
customer-support-agent
  -> customer-support-prompt
  -> support skills
       -> skill tool dependencies
  -> exact executable tools
  -> customer-support-policy
  -> provider profile
  -> runtime limits
  -> state strategy
  -> memory strategy
```

The CX platform remains the application owner.

Enterprise Agent Harness remains the governed runtime.

---

## 2. Current migration reason

The current CX agent assembly still uses the old Harness model.

It still depends on concepts such as:

```text
CapabilityDefinition
CapabilityRegistry
VersionReference
capabilities
allowed_tools
policies
```

The current Harness now uses:

```text
SkillDefinition
SkillRegistry
PromptDefinition
PromptRegistry
ComponentReference
ComponentType
prompt_ref
skill_refs
tool_refs
policy_refs
```

The CX platform must align with that contract before further agent-system work.

---

# Phase 0 - Baseline and compatibility check

## Goal

Confirm the exact Harness contract before changing CX code.

## Tasks

- [ ] Read `.agents/AGENTS.md`.
- [ ] Inspect the current CX agent assembly.
- [ ] Inspect the current CX support capability definitions.
- [ ] Inspect the current Harness public API.
- [ ] Inspect the current Harness skill, prompt, registry, factory, and manifest contracts.
- [ ] Confirm the installed or referenced Harness version used by the CX project.
- [ ] Confirm that current CX tests still target the old Capability API.
- [ ] Record all CX files that need migration.

## Required external source

Use the current code and documentation from:

https://github.com/etimbukafia/enterprise-agent-harness

Do not guess Harness contract names or field semantics.

## Exit criteria

The migration map is complete before CX code changes begin.

---

# Phase 1 - Rename CX capability code to skill code

## Goal

Use one consistent domain term in the CX application.

## Migration

Replace:

```text
cx_platform/agent/capabilities.py
CapabilityDefinition
CapabilityRegistry
CAPABILITY_VERSION
build_support_capabilities()
capability_id
capabilities
```

With:

```text
cx_platform/agent/skills.py
SkillDefinition
SkillRegistry
SKILL_VERSION
build_support_skills()
skill_id
skills
```

Do not keep compatibility aliases.

Do not keep both files after migration.

## Tasks

- [ ] Rename the CX capability module to `skills.py`.
- [ ] Replace `CapabilityDefinition` with `SkillDefinition`.
- [ ] Replace `CapabilityRegistry` with `SkillRegistry`.
- [ ] Rename capability constants and helper functions.
- [ ] Update imports in support-agent assembly and tests.
- [ ] Update current documentation that refers to Harness capabilities as active CX artifacts.

## Exit criteria

The CX application has no active Capability abstraction.

---

# Phase 2 - Migrate the seven support skills

## Goal

Represent the existing seven customer-service abilities as Harness skills.

## Required support skills

Keep these logical skills:

```text
delivery_resolution
payment_issue_resolution
refund_resolution
return_resolution
cancellation_resolution
damaged_item_resolution
missing_item_resolution
```

Do not change their business meaning during this migration.

Do not create scenario-specific skills.

## SkillDefinition mapping

Each skill should define only useful metadata such as:

```text
skill_id
version
name
description
supported_operations
supported_intents
supported_languages
required_tool_refs
optional_tool_refs
risk_level
owner_id
lifecycle
tags
```

Use exact `ComponentReference` values for tool dependencies.

Use `ComponentType.TOOL`.

## Required versus optional tool rule

Classify each tool reference deliberately.

A required tool means the skill cannot provide its base supported behavior without that tool.

An optional tool extends the skill but is not required for the skill to remain valid.

Do not copy the old flat capability tool list blindly into `required_tool_refs`.

Do not classify a tool as optional only to make activation easier.

## Suggested classification approach

Use these rules:

1. Evidence needed to understand the main case is normally required.
2. A write or remedy path can be optional when the skill still has valid non-write behavior.
3. Human escalation is usually optional to the skill itself.
4. A tool can be required by more than one skill.
5. The agent must still declare every executable tool directly in `tool_refs`.

## Examples

`delivery_resolution` will likely require current order and shipment evidence.

`request_refund` can remain an optional remedy dependency if delivery resolution can still explain the case without it.

`payment_issue_resolution` will likely require current payment evidence.

`request_refund` can remain optional when the skill can still investigate and explain a payment issue.

These examples are guidance only.

Inspect current scenario behavior before final classification.

## Tasks

- [ ] Define exact required and optional tool references for all seven skills.
- [ ] Preserve current intents and language support where still correct.
- [ ] Preserve CX ownership metadata.
- [ ] Preserve risk semantics.
- [ ] Register all seven skills as active when their required dependencies are valid.
- [ ] Add behavior tests for skill registration and required dependency failure.

## Exit criteria

All seven existing customer-service abilities are valid active Harness skills.

---

# Phase 3 - Add a first-class support prompt

## Goal

Separate agent purpose from behavioral instructions.

## New prompt artifact

Add one versioned CX-owned prompt.

Suggested identity:

```text
customer-support-prompt@1.0.0
```

Use `PromptDefinition`.

Use `PromptRegistry`.

## Split current support-agent text

Keep the agent goal short and outcome-focused.

Suggested goal:

```text
Resolve supported commerce customer-service requests safely and accurately.
```

Move operating instructions into the prompt artifact.

The prompt should preserve current support behavior, including rules equivalent to:

```text
Use business tools for current authoritative facts.
Treat memory as advisory.
Do not invent business facts.
Do not claim an action succeeded before a tool result confirms it.
Clarify material ambiguity.
Respect permissions, policy, and approval requirements.
Escalate when safe resolution is not available.
```

Do not move application authority into prompt text.

The prompt must not define permissions, approval authority, tenant identity, or policy authority.

## Tasks

- [ ] Add prompt identity and version constants.
- [ ] Add a support prompt builder or constant at the correct application boundary.
- [ ] Create a `PromptRegistry` for support-agent assembly.
- [ ] Register the exact active prompt.
- [ ] Keep prompt instructions small enough for the configured Harness context budget.
- [ ] Add behavior tests that prove the prompt is resolved through the Harness factory.

## Exit criteria

The support agent has one exact prompt artifact and no duplicate authoritative prompt source.

---

# Phase 4 - Migrate agent assembly to current Harness contracts

## Goal

Build the CX support agent through the current Harness API.

## Import migration

Remove old imports such as:

```text
CapabilityRegistry
VersionReference
```

Use current concepts such as:

```text
ComponentReference
ComponentType
PromptDefinition
PromptRegistry
SkillRegistry
```

## AgentRegistry construction

Build the registry with explicit current dependencies.

Target concept:

```text
AgentRegistry(
    prompts=prompt_registry,
    skills=skill_registry,
    tools=tool_registry,
    policies=[support_policy],
)
```

Use the exact current Harness constructor after inspection.

## AgentConfig migration

Replace old fields with exact current fields:

```text
prompt_ref
skill_refs
tool_refs
policy_refs
```

Use exact `ComponentReference` values.

Use the correct `ComponentType` for each reference.

The agent must directly declare each executable tool in `tool_refs`.

Skill dependencies do not grant executable authority.

## Tasks

- [ ] Build the prompt registry.
- [ ] Build the skill registry.
- [ ] Build exact prompt, skill, tool, and policy references.
- [ ] Update `AgentRegistry` construction.
- [ ] Update `AgentConfig` construction.
- [ ] Preserve provider selection.
- [ ] Preserve runtime limits.
- [ ] Preserve approval configuration.
- [ ] Preserve state-store wiring.
- [ ] Preserve memory-strategy wiring.
- [ ] Preserve permission-broker injection.
- [ ] Preserve deterministic and live provider modes.

## Exit criteria

`AgentFactory.build()` constructs the customer-support agent with the current Harness artifact graph.

---

# Phase 5 - Update SupportAgentAssembly

## Goal

Expose the new governed dependencies with correct names.

## Migration

Replace:

```text
SupportAgentAssembly.capabilities
```

With:

```text
SupportAgentAssembly.skills
```

Preserve:

```text
agent
factory
tools
policy
approval_policy
approval_broker
runtime_state_store
memory_strategy
```

Add prompt exposure only if the CX application has a real use for it.

Do not expose extra registry internals without a current consumer.

## Tasks

- [ ] Rename the assembly field.
- [ ] Update services and tests that access it.
- [ ] Remove old capability-specific typing.
- [ ] Keep the assembly small.

## Exit criteria

The assembly uses current terminology and no obsolete Capability types.

---

# Phase 6 - Preserve governance and approval behavior

## Goal

Make this migration behavior-neutral for authority and approval.

## Required invariants

Preserve these behaviors:

1. The CX support policy remains deny-by-default.
2. Only the intended support tools are allowed.
3. `request_refund` remains approval-gated where current policy requires it.
4. Permission denial still fails closed.
5. Approval pause and resume use the same execution correlation.
6. The exact reviewed action remains fixed during resume.
7. Business actions still execute only through governed tools.
8. Prompt and skill metadata do not grant authority.
9. Memory remains advisory.
10. Current business APIs remain authoritative for business truth.

## Tasks

- [ ] Run existing approval tests after migration.
- [ ] Run existing permission-denial tests.
- [ ] Run existing escalation tests.
- [ ] Run exact approval pause/resume tests.
- [ ] Verify no business write bypasses Harness tool execution.

## Exit criteria

The migration does not weaken runtime governance.

---

# Phase 7 - Update trace and execution expectations

## Goal

Use the new Harness provenance without changing CX evidence ownership.

## Harness evidence

The current Harness now preserves exact prompt and skill references in build and trace provenance.

The CX platform should continue to store or expose only safe references.

Do not copy full prompt instructions into CX events.

Do not copy Harness private runtime data.

Do not create a second skill-selection event unless Harness reports a real explicit selection signal.

## CX evidence ownership remains

```text
CX Platform
  -> conversations
  -> tickets
  -> CX operational events
  -> outcomes
  -> approval references
  -> escalation records
  -> execution references

Enterprise Agent Harness
  -> agent execution trace
  -> prompt provenance
  -> skill provenance
  -> tool execution evidence
  -> policy and approval runtime evidence
```

## Tasks

- [ ] Verify existing execution-reference linkage still works.
- [ ] Verify `BuiltAgent.trace_for(execution_id)` still works.
- [ ] Verify CX events do not duplicate prompt text.
- [ ] Verify CX events do not claim inferred skill selection.
- [ ] Update tests only where public Harness evidence contracts changed.

## Exit criteria

CX evidence remains source-owned and linked by stable references.

---

# Phase 8 - Update tests and scenario acceptance coverage

## Goal

Prove the migration through behavior, not implementation structure.

## Required tests

Update or add behavior tests for:

- support agent builds with exact prompt, skill, tool, and policy references;
- all seven skills register successfully;
- a missing required skill tool blocks valid assembly;
- an optional skill tool does not grant agent tool authority;
- support prompt resolves through the Harness factory;
- permission denial still blocks a registered tool;
- refund approval still pauses before action execution;
- resume preserves the same execution and reviewed action;
- traces retain prompt and skill provenance;
- CX execution references still link to Harness traces;
- the existing scenario suite still produces the same allowed and forbidden business outcomes.

## Do not over-test

Do not test:

- file names as behavior;
- import text;
- private registry dictionaries;
- private factory helpers;
- arbitrary counts that do not protect a user or safety outcome.

## Exit criteria

The migration is protected by public-boundary tests and the existing scenario suite.

---

# Phase 9 - Documentation cleanup

## Goal

Use current terminology in active CX documentation.

## Tasks

- [ ] Replace active Harness `capability` terminology with `skill` where it refers to the migrated artifact.
- [ ] Preserve historical references where they describe completed historical work.
- [ ] Update current architecture documentation.
- [ ] Update the main backend build plan where the active architecture still says capability.
- [ ] Update examples or comments that show obsolete Harness contracts.
- [ ] Keep product-level wording clear where `capability` is used in its generic English meaning.

## Important distinction

Do not mechanically replace every English use of the word `capability`.

Only replace it when it names the old Harness artifact.

## Exit criteria

Current documentation describes the actual agent, skill, prompt, tool, and policy architecture.

---

# Phase 10 - Remove migration residue

## Goal

Finish with one architecture.

## Remove

Remove active CX uses of:

```text
CapabilityDefinition
CapabilityRegistry
VersionReference
capability_refs
capabilities=
allowed_tools=
policies=
CAPABILITY_VERSION
build_support_capabilities
```

Remove the old capability module after the skill module is in use.

Do not add aliases for old names.

Do not preserve backward compatibility for this internal development migration.

## Exit criteria

The CX codebase uses only the current Harness artifact model.

---

# Final target support-agent assembly

The final construction should be equivalent to this graph:

```text
ToolRegistry
  -> exact CX support tools

SkillRegistry
  -> delivery_resolution@1.0.0
  -> payment_issue_resolution@1.0.0
  -> refund_resolution@1.0.0
  -> return_resolution@1.0.0
  -> cancellation_resolution@1.0.0
  -> damaged_item_resolution@1.0.0
  -> missing_item_resolution@1.0.0

PromptRegistry
  -> customer-support-prompt@1.0.0

AgentRegistry
  -> prompts
  -> skills
  -> tools
  -> policies

AgentConfig
  -> customer-support-agent@1.0.0
  -> exact prompt_ref
  -> exact skill_refs
  -> exact tool_refs
  -> exact policy_refs
  -> provider profile
  -> runtime limits
  -> state strategy
  -> memory strategy

AgentFactory
  -> BuiltAgent
```

---

# Quality gate

Before completion, run the repository quality checks that exist in the project.

At minimum:

- [ ] full test suite;
- [ ] scenario acceptance suite;
- [ ] compile/import checks;
- [ ] type checks if configured;
- [ ] lint checks if configured;
- [ ] formatting checks if configured;
- [ ] `git diff --check`.

Do not finish with known failures.

---

# Final acceptance criteria

The migration is complete when all statements are true:

- The CX platform uses `SkillDefinition` and `SkillRegistry`.
- The seven support abilities are represented as skills.
- Required and optional skill tool dependencies are explicit.
- The support agent has one exact `PromptDefinition`.
- The agent goal is separate from behavioral prompt instructions.
- `AgentRegistry` receives prompt, skill, tool, and policy registries or records through the current Harness API.
- `AgentConfig` uses exact `prompt_ref`, `skill_refs`, `tool_refs`, and `policy_refs`.
- Every executable tool is directly present in agent `tool_refs`.
- Skill tool dependencies do not grant execution authority.
- Approval and permission behavior remains unchanged.
- Existing CX trace linkage remains valid.
- Current CX events do not duplicate prompt text or invent skill-selection evidence.
- The existing business scenarios still behave correctly.
- Active Capability API usage is removed from CX code.
- Current documentation matches the implemented model.
- The full quality gate passes.

---

# Non-goals

Do not add:

- CX Autopilot logic;
- gap diagnosis;
- opportunity discovery;
- agent improvement planning;
- new support skills unrelated to the migration;
- new business scenarios;
- new tool behavior;
- new policy behavior;
- prompt optimization;
- autonomous deployment;
- another agent runtime;
- another evaluation framework.

This plan only migrates the AI-native CX platform to the current Enterprise Agent Harness artifact model.
