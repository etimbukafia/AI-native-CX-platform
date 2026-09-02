import pytest
from enterprise_agent_harness import MemoryItem, PrincipalContext
from enterprise_agent_harness import MemoryScope as HarnessMemoryScope

from cx_platform.domain.models import MemoryOperation
from cx_platform.memory import (
    ConversationMemory,
    ConversationMemoryKind,
    LocalMemory,
    MemoryKind,
    MemoryScope,
    MemoryUnavailable,
    ResilientMemory,
)
from cx_platform.persistence import CXDatabase, CXRepositories


def test_customer_memory_is_confirmed_isolated_and_superseded_by_new_preference() -> None:
    memory = LocalMemory()
    memory.write_memory(
        execution_id="exec_01",
        scope=MemoryScope.CUSTOMER,
        key="resolution_preference",
        value="replacement",
        memory_type=MemoryKind.FACT,
        customer_id="cx_cus_01",
        confirmed=True,
    )
    latest = memory.write_memory(
        execution_id="exec_02",
        scope=MemoryScope.CUSTOMER,
        key="resolution_preference",
        value="refund",
        memory_type=MemoryKind.FACT,
        customer_id="cx_cus_01",
        confirmed=True,
    )

    recalled = memory.search_relevant(
        execution_id="exec_03",
        scope=MemoryScope.CUSTOMER,
        customer_id="cx_cus_01",
        query="resolution",
    )

    assert latest.version == 2
    assert [(item.value, item.version) for item in recalled] == [("refund", 2)]
    assert memory.search_relevant(
        execution_id="exec_04",
        scope=MemoryScope.CUSTOMER,
        customer_id="cx_cus_02",
    ) == []


def test_shared_memory_is_bounded_and_cannot_store_business_state_as_fact() -> None:
    memory = LocalMemory(max_results=3)
    for number in range(5):
        memory.write_memory(
            execution_id=f"exec_{number}",
            scope=MemoryScope.SHARED_SUPPORT,
            key=f"delivery_explanation_{number}",
            value="Explain the next shipment check clearly.",
            memory_type=MemoryKind.BELIEF,
            capability_id="delivery_resolution",
        )

    with pytest.raises(ValueError, match="business state"):
        memory.write_memory(
            execution_id="exec_bad",
            scope=MemoryScope.SHARED_SUPPORT,
            key="order_status",
            value="shipped",
            memory_type=MemoryKind.FACT,
            capability_id="delivery_resolution",
        )

    results = memory.search_relevant(
        execution_id="exec_read",
        scope=MemoryScope.SHARED_SUPPORT,
        capability_id="delivery_resolution",
        query="delivery",
        limit=3,
    )
    assert len(results) == 3
    assert all(item.advisory for item in results)


def test_conversation_memory_keeps_follow_up_reference_bounded_and_clearable() -> None:
    memory = ConversationMemory(max_items=2)
    identity = PrincipalContext(
        principal_id="operator",
        tenant_id="demo",
        session_id="session_01",
    )
    memory.remember(
        identity,
        customer_id="cx_cus_01",
        conversation_id="conv_01",
        key="active_order",
        value="ord_001",
        kind=ConversationMemoryKind.ORDER_REFERENCE,
    )
    memory.remember(
        identity,
        customer_id="cx_cus_01",
        conversation_id="conv_01",
        key="active_line",
        value="line_002",
        kind=ConversationMemoryKind.LINE_REFERENCE,
    )
    memory.remember(
        identity,
        customer_id="cx_cus_01",
        conversation_id="conv_01",
        key="resolution",
        value="refund",
        kind=ConversationMemoryKind.CUSTOMER_PREFERENCE,
    )

    records = memory.select(
        identity,
        customer_id="cx_cus_01",
        conversation_id="conv_01",
    )
    assert len(records) == 2
    assert records[-1].value == "refund"
    assert memory.select(
        identity,
        customer_id="cx_cus_02",
        conversation_id="conv_01",
    ) == []

    memory.clear(customer_id="cx_cus_01", conversation_id="conv_01")
    assert memory.select(
        identity,
        customer_id="cx_cus_01",
        conversation_id="conv_01",
    ) == []


def test_conversation_memory_rejects_stale_business_state() -> None:
    memory = ConversationMemory()
    identity = PrincipalContext(
        principal_id="operator",
        tenant_id="demo",
        session_id="session_01",
    )

    with pytest.raises(ValueError, match="business state"):
        memory.remember(
            identity,
            customer_id="cx_cus_01",
            conversation_id="conv_01",
            key="shipment_status",
            value="delayed",
            kind=ConversationMemoryKind.SUMMARY,
        )


def test_conversation_memory_strategy_uses_the_harness_boundary() -> None:
    memory = ConversationMemory(max_items=2)
    identity = PrincipalContext(
        principal_id="operator",
        tenant_id="demo",
        session_id="session_01",
    )
    strategy = memory.strategy(
        identity,
        customer_id="cx_cus_01",
        conversation_id="conv_01",
    )
    strategy.remember(
        MemoryItem(
            memory_id="runtime_memory_01",
            principal_id="operator",
            tenant_id="demo",
            scope=HarnessMemoryScope.EXECUTION,
            source_scope_id="runtime_state_01",
            key="resolved_reference:active_order",
            value="ord_001",
            origin="runtime",
        )
    )

    selected = strategy.select(identity)

    assert selected[0].source_scope_id == "conversation:cx_cus_01:conv_01:session_01"
    assert selected[0].value == "ord_001"


def test_conversation_memory_does_not_cross_session_boundaries() -> None:
    memory = ConversationMemory()
    first_session = PrincipalContext(
        principal_id="operator",
        tenant_id="demo",
        session_id="session_01",
    )
    second_session = first_session.model_copy(update={"session_id": "session_02"})

    memory.remember(
        first_session,
        customer_id="cx_cus_01",
        conversation_id="conv_01",
        key="active_order",
        value="ord_001",
        kind=ConversationMemoryKind.ORDER_REFERENCE,
    )

    assert memory.select(
        second_session,
        customer_id="cx_cus_01",
        conversation_id="conv_01",
    ) == []


class FailingMemory:
    provider = "senselab"

    def search_relevant(self, **kwargs):
        raise MemoryUnavailable("timeout")


def test_memory_failure_returns_safe_fallback_and_records_dependency_failure(tmp_path) -> None:
    cx_repositories = CXRepositories(CXDatabase(str(tmp_path / "cx.db")))
    local = LocalMemory()
    local.write_memory(
        execution_id="seed",
        scope=MemoryScope.SHARED_SUPPORT,
        key="delivery_language",
        value="State the next check.",
        memory_type=MemoryKind.BELIEF,
        capability_id="delivery_resolution",
    )
    resilient = ResilientMemory(
        FailingMemory(),
        fallback=local,
        evidence_sink=cx_repositories,
    )

    results = resilient.search_relevant(
        execution_id="exec_failed",
        scope=MemoryScope.SHARED_SUPPORT,
        capability_id="delivery_resolution",
    )

    assert [item.key for item in results] == ["delivery_language"]
    failures = cx_repositories.memory_references(execution_id="exec_failed")
    assert len(failures) == 1
    assert failures[0].operation is MemoryOperation.FAILURE
