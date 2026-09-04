"""Versioned CX-owned prompt artifacts."""

from __future__ import annotations

from enterprise_agent_harness import (
    AgentLifecycleStatus,
    PromptDefinition,
    PromptRegistry,
)

SUPPORT_PROMPT_ID = "customer-support-prompt"
SUPPORT_PROMPT_VERSION = "1.0.0"
SUPPORT_PROMPT_PURPOSE = "Safe and evidence-based customer-service behavior."
SUPPORT_PROMPT_INSTRUCTIONS = (
    "Use business tools for current authoritative facts. "
    "Treat memory as advisory. Do not invent business facts. "
    "Do not claim an action succeeded before a tool result confirms it. "
    "Clarify material ambiguity before acting. "
    "Respect application permissions, policy, and approval requirements. "
    "Escalate when safe resolution is not available."
)


def build_support_prompt() -> PromptDefinition:
    """Return the one exact support prompt artifact."""

    return PromptDefinition(
        prompt_id=SUPPORT_PROMPT_ID,
        version=SUPPORT_PROMPT_VERSION,
        purpose=SUPPORT_PROMPT_PURPOSE,
        instructions=SUPPORT_PROMPT_INSTRUCTIONS,
        owner_id="cx-platform",
        lifecycle=AgentLifecycleStatus.ACTIVE,
        metadata={"domain": "customer-support", "language": "en"},
    )


def build_support_prompt_registry() -> PromptRegistry:
    """Return a registry with the active support prompt."""

    return PromptRegistry(prompts=(build_support_prompt(),))


__all__ = [
    "SUPPORT_PROMPT_ID",
    "SUPPORT_PROMPT_INSTRUCTIONS",
    "SUPPORT_PROMPT_PURPOSE",
    "SUPPORT_PROMPT_VERSION",
    "build_support_prompt",
    "build_support_prompt_registry",
]
