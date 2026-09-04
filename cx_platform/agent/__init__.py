"""CX-specific agent assembly boundaries."""

from .prompts import (
    SUPPORT_PROMPT_ID,
    SUPPORT_PROMPT_INSTRUCTIONS,
    SUPPORT_PROMPT_PURPOSE,
    SUPPORT_PROMPT_VERSION,
    build_support_prompt,
    build_support_prompt_registry,
)
from .skills import SKILL_VERSION, build_support_skills
from .support import (
    SUPPORT_AGENT_GOAL,
    SUPPORT_AGENT_ID,
    SUPPORT_AGENT_VERSION,
    SUPPORT_APPROVAL_POLICY_ID,
    SUPPORT_APPROVAL_POLICY_VERSION,
    SUPPORT_MEMORY_STRATEGY_ID,
    SUPPORT_POLICY_ID,
    SUPPORT_POLICY_VERSION,
    SupportAgentAssembly,
    SupportMemoryStrategy,
    SupportProviderMode,
    assemble_support_agent,
    build_support_agent,
    build_support_approval_policy,
    build_support_policy,
)

__all__ = [
    "SKILL_VERSION",
    "SUPPORT_AGENT_GOAL",
    "SUPPORT_AGENT_ID",
    "SUPPORT_AGENT_VERSION",
    "SUPPORT_APPROVAL_POLICY_ID",
    "SUPPORT_APPROVAL_POLICY_VERSION",
    "SUPPORT_MEMORY_STRATEGY_ID",
    "SUPPORT_POLICY_ID",
    "SUPPORT_POLICY_VERSION",
    "SUPPORT_PROMPT_ID",
    "SUPPORT_PROMPT_INSTRUCTIONS",
    "SUPPORT_PROMPT_PURPOSE",
    "SUPPORT_PROMPT_VERSION",
    "SupportAgentAssembly",
    "SupportMemoryStrategy",
    "SupportProviderMode",
    "assemble_support_agent",
    "build_support_agent",
    "build_support_approval_policy",
    "build_support_policy",
    "build_support_prompt",
    "build_support_prompt_registry",
    "build_support_skills",
]
