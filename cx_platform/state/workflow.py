"""Typed CX workflow state backed by the harness StateStore."""

from __future__ import annotations

from enterprise_agent_harness import (
    ExecutionState,
    ExecutionStateStatus,
    PrincipalContext,
    StateStore,
)
from pydantic import BaseModel, ConfigDict, Field


class WorkflowStateValidationError(ValueError):
    """Raised when stored state does not belong to its requested case."""


class WorkflowState(BaseModel):
    """Small, case-specific state for one support conversation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    customer_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    active_intent: str | None = Field(default=None, min_length=1)
    active_order_id: str | None = Field(default=None, min_length=1)
    active_line_id: str | None = Field(default=None, min_length=1)
    customer_requested_resolution: str | None = Field(default=None, min_length=1)
    awaiting_approval: bool = False


class WorkflowStatePatch(BaseModel):
    """Explicit fields that a support turn may update."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    active_intent: str | None = Field(default=None, min_length=1)
    active_order_id: str | None = Field(default=None, min_length=1)
    active_line_id: str | None = Field(default=None, min_length=1)
    customer_requested_resolution: str | None = Field(default=None, min_length=1)
    awaiting_approval: bool | None = None


class WorkflowStateRecord(BaseModel):
    """Typed view of a harness ExecutionState record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    state_id: str
    execution_id: str
    agent_id: str
    agent_version: str
    principal_id: str
    tenant_id: str
    session_id: str
    status: ExecutionStateStatus
    version: int = Field(ge=0)
    state: WorkflowState


class WorkflowStateManager:
    """Store CX state through a harness StateStore.

    The caller supplies the real Harness agent identity. Phase 6 can therefore
    use the same agent ID and version for state and governed executions.
    The state ID is only a case key for one customer conversation.
    """

    def __init__(
        self,
        state_store: StateStore,
        *,
        agent_id: str,
        agent_version: str,
    ) -> None:
        if not agent_id or not agent_version:
            raise ValueError("agent ID and agent version are required")
        self.state_store = state_store
        self.agent_id = agent_id
        self.agent_version = agent_version

    def load(
        self,
        principal: PrincipalContext,
        *,
        customer_id: str,
        conversation_id: str,
    ) -> WorkflowStateRecord:
        state = self._get_harness_state(
            principal,
            customer_id=customer_id,
            conversation_id=conversation_id,
        )
        if not state.data:
            initial = WorkflowState(
                customer_id=customer_id,
                conversation_id=conversation_id,
            )
            state = state.model_copy(
                update={"data": initial.model_dump(mode="json"), "version": state.version + 1}
            )
            self.state_store.save(state, expected_version=state.version - 1)
        return self._record(state, customer_id=customer_id, conversation_id=conversation_id)

    def save(
        self,
        principal: PrincipalContext,
        record: WorkflowStateRecord,
        *,
        execution_id: str | None = None,
    ) -> WorkflowStateRecord:
        self._validate_record_owner(principal, record)
        current = self.state_store.get_or_create(
            principal,
            agent_id=self.agent_id,
            agent_version=self.agent_version,
            state_id=record.state_id,
        )
        if current.version != record.version:
            raise WorkflowStateValidationError("workflow state version is stale")
        updated = current.model_copy(
            update={
                "status": record.status,
                "version": record.version + 1,
                "data": record.state.model_dump(mode="json"),
                "execution_id": execution_id or current.execution_id,
            }
        )
        self.state_store.save(updated, expected_version=record.version)
        return self._record(
            updated,
            customer_id=record.state.customer_id,
            conversation_id=record.state.conversation_id,
        )

    def update(
        self,
        principal: PrincipalContext,
        *,
        customer_id: str,
        conversation_id: str,
        patch: WorkflowStatePatch,
        status: ExecutionStateStatus | None = None,
        execution_id: str | None = None,
    ) -> WorkflowStateRecord:
        current = self.load(
            principal,
            customer_id=customer_id,
            conversation_id=conversation_id,
        )
        changes = patch.model_dump(exclude_unset=True)
        next_state = current.state.model_copy(update=changes)
        next_status = status or current.status
        return self.save(
            principal,
            current.model_copy(update={"state": next_state, "status": next_status}),
            execution_id=execution_id,
        )

    def bind_execution(
        self,
        principal: PrincipalContext,
        *,
        customer_id: str,
        conversation_id: str,
        execution_id: str,
    ) -> WorkflowStateRecord:
        """Associate application state with the harness execution being run."""

        if not execution_id:
            raise WorkflowStateValidationError("execution ID is required")
        current = self.load(
            principal,
            customer_id=customer_id,
            conversation_id=conversation_id,
        )
        return self.save(principal, current, execution_id=execution_id)

    def set_active_order(
        self,
        principal: PrincipalContext,
        *,
        customer_id: str,
        conversation_id: str,
        order_id: str,
        line_id: str | None = None,
        intent: str | None = None,
    ) -> WorkflowStateRecord:
        patch_data: dict[str, str | None] = {
            "active_order_id": order_id,
            "active_line_id": line_id,
        }
        if intent is not None:
            patch_data["active_intent"] = intent
        return self.update(
            principal,
            customer_id=customer_id,
            conversation_id=conversation_id,
            patch=WorkflowStatePatch.model_validate(patch_data),
        )

    def set_resolution(
        self,
        principal: PrincipalContext,
        *,
        customer_id: str,
        conversation_id: str,
        resolution: str,
    ) -> WorkflowStateRecord:
        return self.update(
            principal,
            customer_id=customer_id,
            conversation_id=conversation_id,
            patch=WorkflowStatePatch(customer_requested_resolution=resolution),
        )

    def set_approval_waiting(
        self,
        principal: PrincipalContext,
        *,
        customer_id: str,
        conversation_id: str,
        awaiting: bool = True,
        execution_id: str | None = None,
    ) -> WorkflowStateRecord:
        return self.update(
            principal,
            customer_id=customer_id,
            conversation_id=conversation_id,
            patch=WorkflowStatePatch(awaiting_approval=awaiting),
            status=ExecutionStateStatus.PAUSED if awaiting else ExecutionStateStatus.RUNNING,
            execution_id=execution_id,
        )

    def clear_case(
        self,
        principal: PrincipalContext,
        *,
        customer_id: str,
        conversation_id: str,
        terminal_status: ExecutionStateStatus = ExecutionStateStatus.COMPLETED,
    ) -> WorkflowStateRecord:
        if terminal_status not in {
            ExecutionStateStatus.COMPLETED,
            ExecutionStateStatus.ESCALATED,
            ExecutionStateStatus.REFUSED,
            ExecutionStateStatus.FAILED,
        }:
            raise WorkflowStateValidationError("case state must use a terminal status")
        return self.update(
            principal,
            customer_id=customer_id,
            conversation_id=conversation_id,
            patch=WorkflowStatePatch(
                active_intent=None,
                active_order_id=None,
                active_line_id=None,
                customer_requested_resolution=None,
                awaiting_approval=False,
            ),
            status=terminal_status,
        )

    def load_execution(
        self,
        principal: PrincipalContext,
        execution_id: str,
        *,
        customer_id: str,
        conversation_id: str,
    ) -> WorkflowStateRecord | None:
        state = self.state_store.find_execution(principal, execution_id)
        if state is None:
            return None
        return self._record(state, customer_id=customer_id, conversation_id=conversation_id)

    def _get_harness_state(
        self,
        principal: PrincipalContext,
        *,
        customer_id: str,
        conversation_id: str,
    ) -> ExecutionState:
        if not customer_id or not conversation_id:
            raise WorkflowStateValidationError("customer and conversation IDs are required")
        return self.state_store.get_or_create(
            principal,
            agent_id=self.agent_id,
            agent_version=self.agent_version,
            state_id=self._state_id(customer_id, conversation_id),
        )

    def _record(
        self,
        state: ExecutionState,
        *,
        customer_id: str,
        conversation_id: str,
    ) -> WorkflowStateRecord:
        if state.agent_id != self.agent_id or state.agent_version != self.agent_version:
            raise WorkflowStateValidationError("stored workflow state uses another agent version")
        if state.state_id != self._state_id(customer_id, conversation_id):
            raise WorkflowStateValidationError("workflow state belongs to another case")
        try:
            workflow = WorkflowState.model_validate(state.data)
        except ValueError as exc:
            raise WorkflowStateValidationError("stored workflow state is invalid") from exc
        if (
            workflow.customer_id != customer_id
            or workflow.conversation_id != conversation_id
        ):
            raise WorkflowStateValidationError("workflow state belongs to another case")
        return WorkflowStateRecord(
            state_id=state.state_id,
            execution_id=state.execution_id,
            agent_id=state.agent_id,
            agent_version=state.agent_version,
            principal_id=state.principal_id,
            tenant_id=state.tenant_id,
            session_id=state.session_id,
            status=state.status,
            version=state.version,
            state=workflow,
        )

    def _validate_record_owner(
        self,
        principal: PrincipalContext,
        record: WorkflowStateRecord,
    ) -> None:
        if (
            record.principal_id != principal.principal_id
            or record.tenant_id != principal.tenant_id
            or record.session_id != principal.session_id
        ):
            raise WorkflowStateValidationError("workflow state belongs to another principal")
        if record.agent_id != self.agent_id or record.agent_version != self.agent_version:
            raise WorkflowStateValidationError("workflow state uses another agent version")
        expected_state_id = self._state_id(
            record.state.customer_id,
            record.state.conversation_id,
        )
        if record.state_id != expected_state_id:
            raise WorkflowStateValidationError("workflow state ID does not match its case")

    @staticmethod
    def _state_id(customer_id: str, conversation_id: str) -> str:
        return f"cx-workflow:{customer_id}:{conversation_id}"


__all__ = [
    "WorkflowState",
    "WorkflowStateManager",
    "WorkflowStatePatch",
    "WorkflowStateRecord",
    "WorkflowStateValidationError",
]
