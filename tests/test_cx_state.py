import pytest
from enterprise_agent_harness import (
    ExecutionStateStatus,
    InMemoryStateStore,
    PrincipalContext,
    SQLiteStateStore,
)

from cx_platform.state import WorkflowStateManager, WorkflowStateValidationError


def principal(session_id: str) -> PrincipalContext:
    return PrincipalContext(
        principal_id="operator",
        tenant_id="demo",
        session_id=session_id,
    )


def build_manager(state_store) -> WorkflowStateManager:
    return WorkflowStateManager(
        state_store,
        agent_id="customer-support-agent",
        agent_version="1.0.0",
    )


def test_workflow_state_keeps_active_order_and_paused_approval_between_turns() -> None:
    state_manager = build_manager(InMemoryStateStore())
    identity = principal("session_01")

    state_manager.load(identity, customer_id="cx_cus_01", conversation_id="conv_01")
    first = state_manager.set_active_order(
        identity,
        customer_id="cx_cus_01",
        conversation_id="conv_01",
        order_id="ord_001",
        line_id="line_001",
        intent="damaged_item",
    )
    switched = state_manager.set_active_order(
        identity,
        customer_id="cx_cus_01",
        conversation_id="conv_01",
        order_id="ord_002",
        line_id="line_002",
    )
    paused = state_manager.set_approval_waiting(
        identity,
        customer_id="cx_cus_01",
        conversation_id="conv_01",
    )

    assert first.state.active_order_id == "ord_001"
    assert switched.state.active_order_id == "ord_002"
    assert switched.state.active_line_id == "line_002"
    assert switched.state.active_intent == "damaged_item"
    assert switched.agent_id == "customer-support-agent"
    assert switched.agent_version == "1.0.0"
    assert paused.status is ExecutionStateStatus.PAUSED
    assert paused.state.awaiting_approval is True

    bound = state_manager.bind_execution(
        identity,
        customer_id="cx_cus_01",
        conversation_id="conv_01",
        execution_id="exec_approval_01",
    )
    paused_execution = state_manager.load_execution(
        identity,
        "exec_approval_01",
        customer_id="cx_cus_01",
        conversation_id="conv_01",
    )
    resumed = state_manager.set_approval_waiting(
        identity,
        customer_id="cx_cus_01",
        conversation_id="conv_01",
        awaiting=False,
    )

    assert bound.execution_id == "exec_approval_01"
    assert paused_execution is not None
    assert paused_execution.status is ExecutionStateStatus.PAUSED
    assert resumed.status is ExecutionStateStatus.RUNNING


def test_workflow_state_is_bound_to_customer_session_and_conversation(tmp_path) -> None:
    database = tmp_path / "state.db"
    owner = principal("session_01")
    first_store = SQLiteStateStore(database)
    first_manager = build_manager(first_store)
    saved = first_manager.set_active_order(
        owner,
        customer_id="cx_cus_01",
        conversation_id="conv_01",
        order_id="ord_001",
    )
    first_store.close()

    reopened = build_manager(SQLiteStateStore(database))
    restored = reopened.load(
        owner,
        customer_id="cx_cus_01",
        conversation_id="conv_01",
    )

    assert restored.state.active_order_id == saved.state.active_order_id
    assert reopened.load(
        principal("session_02"),
        customer_id="cx_cus_01",
        conversation_id="conv_01",
    ).state.active_order_id is None
    with pytest.raises(WorkflowStateValidationError, match="another case"):
        reopened.load_execution(
            owner,
            saved.execution_id,
            customer_id="cx_cus_02",
            conversation_id="conv_02",
        )


def test_workflow_state_clears_case_data_only_at_terminal_boundary() -> None:
    state_manager = build_manager(InMemoryStateStore())
    identity = principal("session_01")
    state_manager.set_active_order(
        identity,
        customer_id="cx_cus_01",
        conversation_id="conv_01",
        order_id="ord_001",
    )
    waiting = state_manager.set_approval_waiting(
        identity,
        customer_id="cx_cus_01",
        conversation_id="conv_01",
    )

    assert waiting.state.awaiting_approval is True
    cleared = state_manager.clear_case(
        identity,
        customer_id="cx_cus_01",
        conversation_id="conv_01",
    )

    assert cleared.status is ExecutionStateStatus.COMPLETED
    assert cleared.state.active_order_id is None
    assert cleared.state.awaiting_approval is False
