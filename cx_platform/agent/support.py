"""Declarative assembly for the customer-support Harness agent."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from threading import RLock
from typing import TYPE_CHECKING, Any

from enterprise_agent_harness import (
    AgentConfig,
    AgentFactory,
    AgentLifecycleStatus,
    AgentRegistry,
    AgentTemplate,
    AgentVersion,
    ApprovalBroker,
    ApprovalPolicy,
    ApprovalPolicyRule,
    BuiltAgent,
    ComponentReference,
    ComponentType,
    DeterministicProvider,
    InMemoryApprovalBroker,
    InMemoryStateStore,
    MemoryItem,
    OpenAIProviderAdapter,
    PermissionBroker,
    PolicyDefinition,
    PolicyEffect,
    PolicyRule,
    PrincipalContext,
    ProviderAdapter,
    ProviderProfile,
    RiskLevel,
    RuntimeConfig,
    SkillRegistry,
    StateStore,
    ToolDescriptor,
    ToolKind,
    ToolRegistry,
)
from enterprise_agent_harness import (
    MemoryScope as HarnessMemoryScope,
)

from cx_platform.integrations.mock_business import MockBusinessClient
from cx_platform.memory.models import MemoryEntry
from cx_platform.memory.short_term import ConversationMemory

if TYPE_CHECKING:
    from cx_platform.services.lifecycle import ConversationService

from .prompts import (
    SUPPORT_PROMPT_ID,
    SUPPORT_PROMPT_VERSION,
    build_support_prompt_registry,
)
from .skills import build_support_skills

SUPPORT_AGENT_ID = "customer-support-agent"
SUPPORT_AGENT_VERSION = "1.0.0"
SUPPORT_POLICY_ID = "customer-support-policy"
SUPPORT_POLICY_VERSION = "1.0.0"
SUPPORT_APPROVAL_POLICY_ID = "customer-support-approval"
SUPPORT_APPROVAL_POLICY_VERSION = "1.0.0"
SUPPORT_MEMORY_STRATEGY_ID = "support-memory"
SUPPORT_STATE_STRATEGY_ID = "support-runtime"

SUPPORT_AGENT_GOAL = (
    "Resolve supported commerce customer-service requests safely and accurately."
)


class SupportProviderMode(StrEnum):
    """Provider choices supported by local and deployed CX runs."""

    DETERMINISTIC = "deterministic"
    LIVE = "live"


@dataclass
class SupportMemoryBinding:
    """One principal-bound memory view used by a support execution."""

    principal: PrincipalContext
    customer_id: str
    conversation_id: str
    advisory_items: tuple[MemoryItem, ...]


class SupportMemoryStrategy:
    """Combine bounded conversation memory with advisory cross-session entries."""

    def __init__(
        self, conversation_memory: ConversationMemory, *, max_items: int = 8
    ) -> None:
        if max_items < 1:
            raise ValueError("max_items must be positive")
        self.conversation_memory = conversation_memory
        self.max_items = max_items
        self._bindings: dict[tuple[str, str, str], SupportMemoryBinding] = {}
        self._lock = RLock()

    def bind(
        self,
        principal: PrincipalContext,
        *,
        customer_id: str,
        conversation_id: str,
        entries: tuple[MemoryEntry, ...] = (),
    ) -> None:
        advisory_items = tuple(
            self._memory_item(principal, entry)
            for entry in entries
            if entry.customer_id in {None, customer_id}
        )
        key = self._key(principal)
        with self._lock:
            self._bindings[key] = SupportMemoryBinding(
                principal=principal,
                customer_id=customer_id,
                conversation_id=conversation_id,
                advisory_items=advisory_items,
            )

    def select(self, principal: PrincipalContext) -> list[MemoryItem]:
        with self._lock:
            binding = self._bindings.get(self._key(principal))
        if binding is None or binding.principal != principal:
            return []
        short_term = self.conversation_memory.strategy(
            principal,
            customer_id=binding.customer_id,
            conversation_id=binding.conversation_id,
        ).select(principal)
        return [*short_term, *binding.advisory_items][: self.max_items]

    def remember(self, item: MemoryItem) -> None:
        with self._lock:
            binding = next(
                (
                    candidate
                    for candidate in self._bindings.values()
                    if candidate.principal.principal_id == item.principal_id
                    and candidate.principal.tenant_id == item.tenant_id
                    and item.source_scope_id
                    == (
                        f"conversation:{candidate.customer_id}:"
                        f"{candidate.conversation_id}:{candidate.principal.session_id}"
                    )
                ),
                None,
            )
        if binding is None:
            raise ValueError("support memory is not bound to this principal")
        self.conversation_memory.strategy(
            binding.principal,
            customer_id=binding.customer_id,
            conversation_id=binding.conversation_id,
        ).remember(item)

    def clear(self, principal: PrincipalContext) -> None:
        with self._lock:
            self._bindings.pop(self._key(principal), None)

    @staticmethod
    def _key(principal: PrincipalContext) -> tuple[str, str, str]:
        return principal.tenant_id, principal.principal_id, principal.session_id

    @staticmethod
    def _memory_item(principal: PrincipalContext, entry: MemoryEntry) -> MemoryItem:
        return MemoryItem(
            memory_id=f"advisory:{entry.memory_id}",
            principal_id=principal.principal_id,
            tenant_id=principal.tenant_id,
            scope=HarnessMemoryScope.PRINCIPAL,
            source_scope_id=entry.entity_path,
            key=f"advisory:{entry.key}",
            value=entry.value,
            origin=f"{entry.provenance.provider}:{entry.memory_type.value}",
            created_at=entry.provenance.occurred_at,
        )


@dataclass
class SupportAgentAssembly:
    """Resolved dependencies needed by the CX execution service."""

    agent: BuiltAgent
    factory: AgentFactory
    tools: ToolRegistry
    skills: SkillRegistry
    policy: PolicyDefinition
    approval_policy: ApprovalPolicy
    approval_broker: ApprovalBroker
    runtime_state_store: StateStore
    memory_strategy: SupportMemoryStrategy | None


def build_support_policy() -> PolicyDefinition:
    """Return the deny-by-default policy for the exact Phase 3 tools."""

    tool_ids = [
        "get_customer",
        "get_customer_orders",
        "get_order",
        "get_order_lines",
        "get_order_payments",
        "get_shipment",
        "get_fulfillment_issues",
        "get_returns",
        "get_policy",
        "search_knowledge",
        "cancel_order",
        "request_return",
        "request_refund",
        "escalate_to_human",
    ]
    rules = [
        PolicyRule(
            rule_id=f"allow-{tool_id.replace('_', '-')}",
            effect=PolicyEffect.ALLOW,
            tool_ids=[tool_id],
            agent_ids=[SUPPORT_AGENT_ID],
            requires_approval=tool_id == "request_refund",
        )
        for tool_id in tool_ids
    ]
    return PolicyDefinition(
        policy_id=SUPPORT_POLICY_ID,
        version=SUPPORT_POLICY_VERSION,
        description="Allow only the registered customer-support tools.",
        owner_id="cx-platform",
        default_effect=PolicyEffect.DENY,
        rules=rules,
        lifecycle=AgentLifecycleStatus.ACTIVE,
    )


def build_support_approval_policy() -> ApprovalPolicy:
    """Require Harness approval for high-risk refund actions."""

    return ApprovalPolicy(
        policy_id=SUPPORT_APPROVAL_POLICY_ID,
        version=SUPPORT_APPROVAL_POLICY_VERSION,
        description="Require a human decision before a refund action runs.",
        owner_id="cx-platform",
        rules=[
            ApprovalPolicyRule(
                rule_id="refund-human-review",
                tool_ids=["request_refund"],
                action_kinds=[ToolKind.ACTION],
                risk_levels=[RiskLevel.HIGH],
                requires_approval=True,
                expiry_seconds=900,
            )
        ],
    )


def build_support_agent(
    client: MockBusinessClient,
    conversations: ConversationService,
    *,
    provider_mode: SupportProviderMode | str = SupportProviderMode.DETERMINISTIC,
    provider: ProviderAdapter | None = None,
    provider_client: Any | None = None,
    model: str = "gpt-4.1-mini",
    deterministic_tool_id: str | None = None,
    deterministic_arguments: Mapping[str, object] | None = None,
    memory_strategy: SupportMemoryStrategy | None = None,
    runtime_state_store: StateStore | None = None,
    approval_broker: ApprovalBroker | None = None,
    permission_broker: PermissionBroker | None = None,
    approval_policy: ApprovalPolicy | None = None,
) -> BuiltAgent:
    """Build and activate the one declarative customer-support agent."""

    return _build_support_assembly(
        client,
        conversations,
        provider_mode=provider_mode,
        provider=provider,
        provider_client=provider_client,
        model=model,
        deterministic_tool_id=deterministic_tool_id,
        deterministic_arguments=deterministic_arguments,
        memory_strategy=memory_strategy,
        runtime_state_store=runtime_state_store,
        approval_broker=approval_broker,
        permission_broker=permission_broker,
        approval_policy=approval_policy,
    ).agent


def assemble_support_agent(
    client: MockBusinessClient,
    conversations: ConversationService,
    **kwargs: Any,
) -> SupportAgentAssembly:
    """Build the agent and expose its governed dependencies to CX services."""

    return _build_support_assembly(client, conversations, **kwargs)


def _build_support_assembly(
    client: MockBusinessClient,
    conversations: ConversationService,
    *,
    provider_mode: SupportProviderMode | str = SupportProviderMode.DETERMINISTIC,
    provider: ProviderAdapter | None = None,
    provider_client: Any | None = None,
    model: str = "gpt-4.1-mini",
    deterministic_tool_id: str | None = None,
    deterministic_arguments: Mapping[str, object] | None = None,
    memory_strategy: SupportMemoryStrategy | None = None,
    runtime_state_store: StateStore | None = None,
    approval_broker: ApprovalBroker | None = None,
    permission_broker: PermissionBroker | None = None,
    approval_policy: ApprovalPolicy | None = None,
) -> SupportAgentAssembly:
    from cx_platform.tools.support import build_support_tools

    tools = build_support_tools(client, conversations)
    skills = build_support_skills(tools)
    prompt_registry = build_support_prompt_registry()
    policy = build_support_policy()
    selected_approval_policy = approval_policy or build_support_approval_policy()
    broker = approval_broker or InMemoryApprovalBroker(
        policies=[selected_approval_policy]
    )
    selected_provider = provider or _provider(
        provider_mode,
        provider_client=provider_client,
        model=model,
        deterministic_tool_id=deterministic_tool_id,
        deterministic_arguments=deterministic_arguments,
    )
    runtime_store = runtime_state_store or InMemoryStateStore()
    registry = AgentRegistry(
        prompts=prompt_registry,
        skills=skills,
        tools=tools,
        policies=[policy],
    )
    factory = AgentFactory(
        agent_registry=registry,
        providers={
            (
                _provider_id(selected_provider),
                _provider_version(selected_provider),
            ): selected_provider
        },
        memory_strategies=(
            {SUPPORT_MEMORY_STRATEGY_ID: memory_strategy}
            if memory_strategy is not None
            else None
        ),
        state_stores={SUPPORT_STATE_STRATEGY_ID: runtime_store},
        default_state_store=runtime_store,
        permission_broker=permission_broker,
        approval_broker=broker,
    )
    profile = ProviderProfile(
        provider_id=_provider_id(selected_provider),
        version=_provider_version(selected_provider),
        model=_provider_model(selected_provider),
    )
    tool_refs = [
        ComponentReference(
            component_type=ComponentType.TOOL,
            component_id=tool.tool_id,
            version=tool.version,
        )
        for tool in tools.list()
    ]
    skill_refs = [
        ComponentReference(
            component_type=ComponentType.SKILL,
            component_id=skill.skill_id,
            version=skill.version,
        )
        for skill in skills.list()
    ]
    config = AgentConfig(
        identity=AgentVersion(agent_id=SUPPORT_AGENT_ID, version=SUPPORT_AGENT_VERSION),
        goal=SUPPORT_AGENT_GOAL,
        supported_intents=["customer_support"],
        supported_languages=["en"],
        prompt_ref=ComponentReference(
            component_type=ComponentType.PROMPT,
            component_id=SUPPORT_PROMPT_ID,
            version=SUPPORT_PROMPT_VERSION,
        ),
        skill_refs=skill_refs,
        tool_refs=tool_refs,
        policy_refs=[
            ComponentReference(
                component_type=ComponentType.POLICY,
                component_id=policy.policy_id,
                version=policy.version,
            )
        ],
        provider_profile=profile,
        runtime_limits=RuntimeConfig(
            max_plan_steps=3,
            execution_timeout_seconds=60,
            provider_timeout_seconds=30,
            approval_expiry_seconds=900,
            environment="development",
            max_risk_level=RiskLevel.HIGH,
        ),
        risk_level=RiskLevel.HIGH,
        approval_requirements=["request_refund"],
        state_strategy=SUPPORT_STATE_STRATEGY_ID,
        memory_strategy=(
            SUPPORT_MEMORY_STRATEGY_ID if memory_strategy is not None else None
        ),
        owner_id="cx-platform",
        template=AgentTemplate.ACTION_AGENT,
    )
    agent = factory.build(config)
    return SupportAgentAssembly(
        agent=agent,
        factory=factory,
        tools=tools,
        skills=skills,
        policy=policy,
        approval_policy=selected_approval_policy,
        approval_broker=broker,
        runtime_state_store=runtime_store,
        memory_strategy=memory_strategy,
    )


def _provider(
    mode: SupportProviderMode | str,
    *,
    provider_client: Any | None,
    model: str,
    deterministic_tool_id: str | None,
    deterministic_arguments: Mapping[str, object] | None,
) -> ProviderAdapter:
    selected_mode = SupportProviderMode(mode)
    if selected_mode is SupportProviderMode.LIVE:
        return OpenAIProviderAdapter(
            model=model,
            client=provider_client,
            timeout_seconds=30,
        )

    configured = dict(deterministic_arguments or {})

    def argument_builder(_: object, tool: ToolDescriptor) -> dict[str, object]:
        del tool
        return configured.copy()

    return DeterministicProvider(
        tool_id=deterministic_tool_id,
        argument_builder=argument_builder,
    )


def _provider_id(provider: ProviderAdapter) -> str:
    return str(getattr(provider, "provider_id", "provider"))


def _provider_version(provider: ProviderAdapter) -> str:
    value = str(getattr(provider, "provider_version", "1.0.0"))
    if value == "responses-api":
        return "1.0.0"
    return value


def _provider_model(provider: ProviderAdapter) -> str:
    return str(getattr(provider, "model", "provider-model"))


__all__ = [
    "SUPPORT_AGENT_GOAL",
    "SUPPORT_AGENT_ID",
    "SUPPORT_AGENT_VERSION",
    "SUPPORT_APPROVAL_POLICY_ID",
    "SUPPORT_APPROVAL_POLICY_VERSION",
    "SUPPORT_MEMORY_STRATEGY_ID",
    "SUPPORT_POLICY_ID",
    "SUPPORT_POLICY_VERSION",
    "SUPPORT_PROMPT_ID",
    "SUPPORT_PROMPT_VERSION",
    "SupportAgentAssembly",
    "SupportMemoryStrategy",
    "SupportProviderMode",
    "assemble_support_agent",
    "build_support_agent",
    "build_support_approval_policy",
    "build_support_policy",
]
