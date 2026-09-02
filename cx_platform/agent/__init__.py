"""CX-specific agent assembly boundaries."""

from .capabilities import build_support_capabilities
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
    "SUPPORT_AGENT_GOAL",
    "SUPPORT_AGENT_ID",
    "SUPPORT_AGENT_VERSION",
    "SUPPORT_APPROVAL_POLICY_ID",
    "SUPPORT_APPROVAL_POLICY_VERSION",
    "SUPPORT_MEMORY_STRATEGY_ID",
    "SUPPORT_POLICY_ID",
    "SUPPORT_POLICY_VERSION",
    "SupportAgentAssembly",
    "SupportMemoryStrategy",
    "SupportProviderMode",
    "assemble_support_agent",
    "build_support_agent",
    "build_support_approval_policy",
    "build_support_capabilities",
    "build_support_policy",
]
