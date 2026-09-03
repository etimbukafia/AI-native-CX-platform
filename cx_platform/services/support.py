"""Application service for one governed customer-support turn."""

from __future__ import annotations

from typing import Any

from enterprise_agent_harness import (
    AgentOutcome,
    ApprovalDecision,
    ApprovalDecisionStatus,
    ApprovalRequest,
    ExecutionStateStatus,
    InMemoryStateStore,
    OutcomeStatus,
    PrincipalContext,
    RiskLevel,
    ToolResultStatus,
)
from pydantic import BaseModel, ConfigDict, Field

from cx_platform.agent import (
    SUPPORT_AGENT_ID,
    SUPPORT_AGENT_VERSION,
    SupportAgentAssembly,
    SupportMemoryStrategy,
    assemble_support_agent,
)
from cx_platform.domain.models import (
    ActorType,
    ApprovalRecord,
    ApprovalRecordStatus,
    Conversation,
    ConversationRead,
    CXEvent,
    CXEventType,
    CXMetrics,
    Escalation,
    EscalationReason,
    ExecutionReference,
    Message,
    Outcome,
    OutcomeRead,
    ResolutionCode,
    Ticket,
    TicketDetail,
    TicketStatus,
    now,
)
from cx_platform.memory import (
    ConversationMemory,
    MemoryEntry,
    MemoryPort,
    MemoryScope,
    build_memory,
)
from cx_platform.persistence import CXRepositories
from cx_platform.services.events import CXEventService
from cx_platform.services.lifecycle import ConversationService
from cx_platform.services.metrics import CXMetricsService
from cx_platform.services.outcomes import CXOutcomeService
from cx_platform.state import WorkflowStateManager, WorkflowStatePatch


class SupportServiceError(ValueError):
    """Raised when a support request cannot safely be handled."""


class SupportTurnResult(BaseModel):
    """Typed result returned to a CX caller after one support operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    customer_id: str = Field(min_length=1)
    ticket_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    customer_message_id: str | None = Field(default=None, min_length=1)
    agent_message_id: str | None = Field(default=None, min_length=1)
    execution_id: str = Field(min_length=1)
    status: OutcomeStatus
    ticket_status: TicketStatus
    response: str = Field(min_length=1)
    approval_id: str | None = Field(default=None, min_length=1)
    escalation_id: str | None = Field(default=None, min_length=1)
    outcome_id: str | None = Field(default=None, min_length=1)
    trace_id: str | None = Field(default=None, min_length=1)
    error_code: str | None = Field(default=None, min_length=1)


class SupportService:
    """Coordinate CX records around a Harness-built support agent."""

    def __init__(
        self,
        *,
        repositories: CXRepositories,
        conversations: ConversationService,
        assembly: SupportAgentAssembly,
        memory: MemoryPort,
        short_term_memory: ConversationMemory,
        workflow_state: WorkflowStateManager,
        tenant_id: str = "cx-platform",
    ) -> None:
        if conversations.repositories is not repositories:
            raise ValueError(
                "conversation and support services must share repositories"
            )
        if not tenant_id:
            raise ValueError("tenant ID is required")
        self.repositories = repositories
        self.conversations = conversations
        self.event_service: CXEventService = conversations.event_service
        self.assembly = assembly
        self.agent = assembly.agent
        self.approval_broker = assembly.approval_broker
        self.memory = memory
        self.short_term_memory = short_term_memory
        self.workflow_state = workflow_state
        self.tenant_id = tenant_id
        self.outcome_service = CXOutcomeService(repositories)
        self.metrics_service = CXMetricsService(repositories, self.outcome_service)

    @property
    def workflow_state_manager(self) -> WorkflowStateManager:
        """Return the CX state manager bound to the real support identity."""

        return self.workflow_state

    def handle_message(
        self,
        conversation_id: str,
        content: str,
        *,
        customer_id: str | None = None,
        session_id: str | None = None,
    ) -> SupportTurnResult:
        """Store and process one customer message through Harness."""

        _, ticket = self._case(conversation_id, customer_id)
        if not content.strip():
            raise SupportServiceError("message content is required")
        if ticket.status in {TicketStatus.CLOSED, TicketStatus.RESOLVED}:
            raise SupportServiceError("the ticket is no longer accepting messages")
        if ticket.status is TicketStatus.WAITING_APPROVAL:
            raise SupportServiceError("the ticket is waiting for an approval decision")

        principal = self._principal(ticket.customer_id, session_id or conversation_id)
        execution_id = self.assembly.factory.new_id("execution")
        self._start_execution_reference(
            ticket=ticket,
            conversation_id=conversation_id,
            execution_id=execution_id,
        )
        customer_message = self.conversations.append_message(
            conversation_id,
            actor_type=ActorType.CUSTOMER,
            actor_id=ticket.customer_id,
            content=content,
            execution_id=execution_id,
        )
        if ticket.status is TicketStatus.OPEN:
            self.conversations.transition_ticket(
                ticket.ticket_id,
                TicketStatus.IN_PROGRESS,
                execution_id=execution_id,
            )
        self.event_service.emit(
            CXEventType.AGENT_EXECUTION_STARTED,
            customer_id=ticket.customer_id,
            ticket_id=ticket.ticket_id,
            conversation_id=conversation_id,
            execution_id=execution_id,
            actor_type=ActorType.AI_AGENT,
            actor_id=SUPPORT_AGENT_ID,
            data={"agent_version": SUPPORT_AGENT_VERSION},
        )
        self.workflow_state.bind_execution(
            principal,
            customer_id=ticket.customer_id,
            conversation_id=conversation_id,
            execution_id=execution_id,
        )
        self._bind_memory(
            principal,
            execution_id,
            content,
            ticket.customer_id,
            conversation_id,
        )
        try:
            outcome = self.agent.execute(
                principal,
                content,
                execution_id=execution_id,
                environment="development",
                max_risk_level=RiskLevel.HIGH,
            )
        except Exception as exc:  # noqa: BLE001 - an application boundary needs a safe handoff.
            return self._application_failure(
                ticket=ticket,
                conversation_id=conversation_id,
                principal=principal,
                execution_id=execution_id,
                customer_message_id=customer_message.message_id,
                error=exc,
            )
        finally:
            if self.assembly.memory_strategy is not None:
                self.assembly.memory_strategy.clear(principal)

        return self._record_outcome(
            outcome,
            ticket=ticket,
            conversation_id=conversation_id,
            principal=principal,
            customer_message_id=customer_message.message_id,
        )

    def approve(
        self,
        execution_id: str,
        *,
        decided_by: str,
        reason_code: str = "approved",
    ) -> SupportTurnResult:
        """Approve and resume the exact paused Harness execution."""

        return self._decide(
            execution_id,
            decided_by=decided_by,
            decision=ApprovalDecisionStatus.APPROVED,
            reason_code=reason_code,
        )

    def reject(
        self,
        execution_id: str,
        *,
        decided_by: str,
        reason_code: str = "rejected",
    ) -> SupportTurnResult:
        """Reject the exact paused action and close it through Harness."""

        return self._decide(
            execution_id,
            decided_by=decided_by,
            decision=ApprovalDecisionStatus.REJECTED,
            reason_code=reason_code,
        )

    def approval_records(self, *, ticket_id: str | None = None) -> list[ApprovalRecord]:
        """Return the small CX approval references for operator presentation."""

        return self.repositories.approvals(ticket_id=ticket_id)

    def events(
        self,
        *,
        after: str | None = None,
        limit: int = 100,
    ) -> list[CXEvent]:
        """Return CX operational events after an event ID or cursor."""

        return self.event_service.poll(after=after, limit=limit)

    def execution_reference(self, execution_id: str) -> ExecutionReference | None:
        """Return the safe CX reference for one Harness execution."""

        return self.repositories.execution_reference(execution_id)

    def tickets(
        self,
        *,
        status: TicketStatus | str | None = None,
        customer_id: str | None = None,
        after: str | None = None,
        limit: int = 100,
    ) -> list[Ticket]:
        """Return typed tickets for external consumers."""

        status_value = status.value if isinstance(status, TicketStatus) else status
        return self.repositories.tickets(
            status=status_value,
            customer_id=customer_id,
            after=after,
            limit=limit,
        )

    def ticket_detail(self, ticket_id: str) -> TicketDetail | None:
        """Return one ticket and its safe related CX records."""

        ticket = self.repositories.ticket(ticket_id)
        if ticket is None:
            return None
        conversation = self.repositories.conversation(ticket.conversation_id)
        if conversation is None:
            return None
        return TicketDetail(
            ticket=ticket,
            conversation=conversation,
            messages=self.repositories.messages(conversation.conversation_id),
            escalations=self.repositories.escalations(ticket_id),
            approvals=self.repositories.approvals(ticket_id=ticket_id),
            outcomes=self.outcome_service.list_outcomes(
                ticket_id=ticket_id,
                limit=1_000_000,
            ),
            csat=self.repositories.csats(ticket_id),
        )

    def conversation_read(self, conversation_id: str) -> ConversationRead | None:
        """Return one conversation, its ticket, and ordered messages."""

        conversation = self.repositories.conversation(conversation_id)
        if conversation is None:
            return None
        ticket = self.repositories.ticket(conversation.ticket_id)
        if ticket is None:
            return None
        return ConversationRead(
            conversation=conversation,
            ticket=ticket,
            messages=self.repositories.messages(conversation_id),
        )

    def outcomes(
        self,
        *,
        ticket_id: str | None = None,
        after: str | None = None,
        limit: int = 100,
    ) -> list[OutcomeRead]:
        """Return structured outcome evidence for external consumers."""

        return self.outcome_service.list_outcomes(
            ticket_id=ticket_id,
            after=after,
            limit=limit,
        )

    def metrics(self) -> CXMetrics:
        """Return deterministic aggregate CX metrics."""

        return self.metrics_service.compute()

    def _decide(
        self,
        execution_id: str,
        *,
        decided_by: str,
        decision: ApprovalDecisionStatus,
        reason_code: str,
    ) -> SupportTurnResult:
        if not decided_by.strip():
            raise SupportServiceError("a reviewer identity is required")
        records = self.repositories.approvals(execution_id=execution_id)
        if not records:
            raise SupportServiceError("approval reference was not found")
        record = records[-1]
        if record.status is not ApprovalRecordStatus.PENDING:
            raise SupportServiceError("approval has already been decided")
        conversation = self.repositories.conversation(record.conversation_id)
        ticket = self.repositories.ticket(record.ticket_id)
        if conversation is None or ticket is None:
            raise SupportServiceError("approval case is no longer available")
        principal = self._principal(record.customer_id, record.session_id)
        try:
            decision_value = self._broker_decide(
                record.harness_request_id,
                decision=decision,
                decided_by=decided_by,
                reason_code=reason_code,
            )
        except Exception as exc:
            raise SupportServiceError("approval decision could not be recorded") from exc
        status = self._approval_status(decision_value)
        updated_record = record.model_copy(
            update={
                "status": status,
                "harness_approval_id": decision_value.approval_id,
                "decided_by": decision_value.decided_by,
                "decision_reason": decision_value.reason_code,
                "decided_at": decision_value.decided_at,
            }
        )
        self.repositories.save_approval(updated_record)
        decision_event = (
            CXEventType.APPROVAL_APPROVED
            if status is ApprovalRecordStatus.APPROVED
            else CXEventType.APPROVAL_REJECTED
        )
        self.event_service.emit(
            decision_event,
            customer_id=record.customer_id,
            ticket_id=record.ticket_id,
            conversation_id=record.conversation_id,
            execution_id=record.execution_id,
            actor_type=ActorType.HUMAN_AGENT,
            actor_id=decided_by,
            data={
                "approval_id": record.approval_id,
                "harness_request_id": record.harness_request_id,
                "harness_approval_id": decision_value.approval_id,
                "decision_status": decision_value.status.value,
                "reason_code": decision_value.reason_code,
            },
        )
        self._bind_memory(
            principal,
            execution_id,
            record.action_summary,
            record.customer_id,
            conversation.conversation_id,
        )
        try:
            outcome = self.agent.runtime.resume(
                execution_id,
                decision_value,
                principal=principal,
            )
        except Exception as exc:  # noqa: BLE001 - stale approval becomes a safe handoff.
            return self._application_failure(
                ticket=ticket,
                conversation_id=conversation.conversation_id,
                principal=principal,
                execution_id=execution_id,
                customer_message_id=self._message_for_execution(
                    conversation.conversation_id,
                    execution_id,
                    actor_type=ActorType.CUSTOMER,
                ),
                error=exc,
            )
        finally:
            if self.assembly.memory_strategy is not None:
                self.assembly.memory_strategy.clear(principal)
        return self._record_outcome(
            outcome,
            ticket=ticket,
            conversation_id=conversation.conversation_id,
            principal=principal,
            customer_message_id=self._message_for_execution(
                conversation.conversation_id,
                execution_id,
                actor_type=ActorType.CUSTOMER,
            ),
        )

    def _record_outcome(
        self,
        outcome: AgentOutcome,
        *,
        ticket: Ticket,
        conversation_id: str,
        principal: PrincipalContext,
        customer_message_id: str | None,
    ) -> SupportTurnResult:
        request = self.agent.runtime.approval_request_for(outcome.execution_id)
        self._record_tool_events(
            outcome,
            ticket=ticket,
            conversation_id=conversation_id,
        )
        if request is not None:
            self._update_execution_reference(
                outcome,
                pending=True,
                customer_id=ticket.customer_id,
            )
            approval, created = self._save_pending_approval(
                request,
                ticket=ticket,
                conversation_id=conversation_id,
                principal=principal,
            )
            if created:
                self.event_service.emit(
                    CXEventType.APPROVAL_REQUESTED,
                    customer_id=ticket.customer_id,
                    ticket_id=ticket.ticket_id,
                    conversation_id=conversation_id,
                    execution_id=outcome.execution_id,
                    actor_type=ActorType.AI_AGENT,
                    actor_id=SUPPORT_AGENT_ID,
                    data={
                        "approval_id": approval.approval_id,
                        "harness_request_id": approval.harness_request_id,
                        "tool_id": approval.tool_id,
                        "action_digest": approval.action_digest,
                    },
                )
            self.workflow_state.set_approval_waiting(
                principal,
                customer_id=ticket.customer_id,
                conversation_id=conversation_id,
                awaiting=True,
                execution_id=outcome.execution_id,
            )
            self.conversations.transition_ticket(
                ticket.ticket_id,
                TicketStatus.WAITING_APPROVAL,
                execution_id=outcome.execution_id,
            )
            message = self._append_agent_message(
                conversation_id,
                execution_id=outcome.execution_id,
                content="This request needs human approval before the action can run.",
            )
            return self._result(
                outcome,
                ticket_status=TicketStatus.WAITING_APPROVAL,
                customer_id=ticket.customer_id,
                ticket_id=ticket.ticket_id,
                conversation_id=conversation_id,
                customer_message_id=customer_message_id,
                agent_message_id=message.message_id,
                approval_id=approval.approval_id,
                response="This request needs human approval before the action can run.",
            )

        self._update_execution_reference(
            outcome,
            pending=False,
            customer_id=ticket.customer_id,
        )
        if outcome.status is OutcomeStatus.COMPLETED:
            return self._completed(
                outcome,
                ticket=ticket,
                conversation_id=conversation_id,
                principal=principal,
                customer_message_id=customer_message_id,
            )

        if outcome.status is OutcomeStatus.NEEDS_INPUT:
            return self._needs_input(
                outcome,
                ticket=ticket,
                conversation_id=conversation_id,
                principal=principal,
                customer_message_id=customer_message_id,
            )

        reason = self._escalation_reason(outcome, self._failure_codes(outcome))
        response = self._safe_response(outcome, reason)
        resolution_code = self._resolution_code_for_escalation(reason, outcome)
        escalation = self._escalate(
            ticket=ticket,
            conversation_id=conversation_id,
            execution_id=outcome.execution_id,
            principal=principal,
            reason=reason,
            summary=response,
            outcome=outcome,
            resolution_code=resolution_code,
        )
        terminal_outcome = self._record_escalated_outcome(
            ticket=ticket,
            execution_id=outcome.execution_id,
            reason=reason,
            outcome=outcome,
            escalation=escalation,
            resolution_code=resolution_code,
        )
        message = self._append_agent_message(
            conversation_id,
            execution_id=outcome.execution_id,
            content=response,
        )
        return self._result(
            outcome,
            ticket_status=TicketStatus.ESCALATED,
            customer_id=ticket.customer_id,
            ticket_id=ticket.ticket_id,
            conversation_id=conversation_id,
            customer_message_id=customer_message_id,
            agent_message_id=message.message_id,
            escalation_id=escalation.escalation_id,
            outcome_id=terminal_outcome.outcome_id,
            response=response,
        )

    def _needs_input(
        self,
        outcome: AgentOutcome,
        *,
        ticket: Ticket,
        conversation_id: str,
        principal: PrincipalContext,
        customer_message_id: str | None,
    ) -> SupportTurnResult:
        response = "I need more information before I can safely continue."
        self.workflow_state.update(
            principal,
            customer_id=ticket.customer_id,
            conversation_id=conversation_id,
            patch=WorkflowStatePatch(),
            status=ExecutionStateStatus.PAUSED,
            execution_id=outcome.execution_id,
        )
        message = self._append_agent_message(
            conversation_id,
            execution_id=outcome.execution_id,
            content=response,
        )
        return self._result(
            outcome,
            ticket_status=TicketStatus.IN_PROGRESS,
            customer_id=ticket.customer_id,
            ticket_id=ticket.ticket_id,
            conversation_id=conversation_id,
            customer_message_id=customer_message_id,
            agent_message_id=message.message_id,
            response=response,
        )

    def _completed(
        self,
        outcome: AgentOutcome,
        *,
        ticket: Ticket,
        conversation_id: str,
        principal: PrincipalContext,
        customer_message_id: str | None,
    ) -> SupportTurnResult:
        current_ticket = self.repositories.ticket(ticket.ticket_id) or ticket
        if current_ticket.status is TicketStatus.ESCALATED:
            escalation = self._latest_escalation(ticket.ticket_id)
            if escalation is not None:
                escalation = self.repositories.save_escalation(
                    escalation.model_copy(
                        update={
                            "conversation_id": conversation_id,
                            "execution_id": outcome.execution_id,
                            "customer_goal": ticket.reason,
                            "actions_attempted": [
                                call.tool_id for call in outcome.tool_calls
                            ],
                            "tool_result_refs": outcome.evidence_ids,
                        }
                    )
                )
            escalation_reason = (
                escalation.reason
                if escalation is not None
                else EscalationReason.CUSTOMER_REQUESTED_HUMAN
            )
            terminal_outcome = self._record_escalated_outcome(
                ticket=ticket,
                execution_id=outcome.execution_id,
                reason=escalation_reason,
                outcome=outcome,
                escalation=escalation,
                resolution_code=self._resolution_code_for_escalation(
                    escalation_reason,
                    outcome,
                ),
            )
            self.workflow_state.clear_case(
                principal,
                customer_id=ticket.customer_id,
                conversation_id=conversation_id,
                terminal_status=ExecutionStateStatus.ESCALATED,
            )
            response = "I have handed this request to a human support specialist."
            message = self._append_agent_message(
                conversation_id,
                execution_id=outcome.execution_id,
                content=response,
            )
            return self._result(
                outcome,
                ticket_status=TicketStatus.ESCALATED,
                customer_id=ticket.customer_id,
                ticket_id=ticket.ticket_id,
                conversation_id=conversation_id,
                customer_message_id=customer_message_id,
                agent_message_id=message.message_id,
                escalation_id=escalation.escalation_id if escalation else None,
                outcome_id=terminal_outcome.outcome_id,
                response=response,
            )

        resolution_code = self._resolution_code_for_completed(outcome)
        resolved = self.conversations.resolve(
            ticket.ticket_id,
            resolution_code=resolution_code.value,
            outcome_type="support_resolved",
            execution_id=outcome.execution_id,
            metadata={
                "execution_id": outcome.execution_id,
                "harness_outcome_id": outcome.outcome_id,
                "resolution_code": resolution_code.value,
                "tool_ids": [call.tool_id for call in outcome.tool_calls],
                "evidence_ids": outcome.evidence_ids,
            },
        )
        outcome_id = self.repositories.outcomes(ticket.ticket_id)[-1].outcome_id
        self.workflow_state.clear_case(
            principal,
            customer_id=ticket.customer_id,
            conversation_id=conversation_id,
            terminal_status=ExecutionStateStatus.COMPLETED,
        )
        response = outcome.summary
        message = self._append_agent_message(
            conversation_id,
            execution_id=outcome.execution_id,
            content=response,
        )
        self.short_term_memory.clear_after_resolution(
            customer_id=ticket.customer_id,
            conversation_id=conversation_id,
            session_id=principal.session_id,
        )
        return self._result(
            outcome,
            ticket_status=resolved.status,
            customer_id=ticket.customer_id,
            ticket_id=ticket.ticket_id,
            conversation_id=conversation_id,
            customer_message_id=customer_message_id,
            agent_message_id=message.message_id,
            outcome_id=outcome_id,
            response=response,
        )

    def _application_failure(
        self,
        *,
        ticket: Ticket,
        conversation_id: str,
        principal: PrincipalContext,
        execution_id: str,
        customer_message_id: str | None,
        error: Exception,
    ) -> SupportTurnResult:
        reason = (
            EscalationReason.BUSINESS_SYSTEM_UNAVAILABLE
            if "depend" in str(error).lower() or "transport" in str(error).lower()
            else EscalationReason.AGENT_UNCERTAIN
        )
        response = self._safe_response(None, reason)
        self._fail_execution_reference(
            execution_id,
            customer_id=ticket.customer_id,
        )
        escalation = self._escalate(
            ticket=ticket,
            conversation_id=conversation_id,
            execution_id=execution_id,
            principal=principal,
            reason=reason,
            summary=response,
            outcome=None,
            resolution_code=self._resolution_code_for_escalation(reason, None),
        )
        terminal_outcome = self._record_escalated_outcome(
            ticket=ticket,
            execution_id=execution_id,
            reason=reason,
            outcome=None,
            escalation=escalation,
            resolution_code=self._resolution_code_for_escalation(reason, None),
        )
        self.workflow_state.clear_case(
            principal,
            customer_id=ticket.customer_id,
            conversation_id=conversation_id,
            terminal_status=ExecutionStateStatus.ESCALATED,
        )
        message = self._append_agent_message(
            conversation_id,
            execution_id=execution_id,
            content=response,
        )
        return SupportTurnResult(
            customer_id=ticket.customer_id,
            ticket_id=ticket.ticket_id,
            conversation_id=conversation_id,
            customer_message_id=customer_message_id,
            agent_message_id=message.message_id,
            execution_id=execution_id,
            status=OutcomeStatus.FAILED,
            ticket_status=TicketStatus.ESCALATED,
            response=response,
            escalation_id=escalation.escalation_id,
            outcome_id=terminal_outcome.outcome_id,
            error_code="support_execution_failed",
        )

    def _escalate(
        self,
        *,
        ticket: Ticket,
        conversation_id: str,
        execution_id: str,
        principal: PrincipalContext,
        reason: EscalationReason,
        summary: str,
        outcome: AgentOutcome | None,
        resolution_code: ResolutionCode,
    ) -> Escalation:
        current_ticket = self.repositories.ticket(ticket.ticket_id) or ticket
        if current_ticket.status is TicketStatus.ESCALATED:
            latest = self._latest_escalation(ticket.ticket_id)
            if latest is not None:
                return latest
        actions = [call.tool_id for call in outcome.tool_calls] if outcome else []
        refs = list(outcome.evidence_ids) if outcome else []
        return self.conversations.escalate(
            ticket.ticket_id,
            reason=reason,
            summary=summary,
            conversation_id=conversation_id,
            execution_id=execution_id,
            resolution_code=resolution_code.value,
            customer_goal=ticket.reason,
            actions_attempted=actions,
            tool_result_refs=refs,
        )

    def _record_escalated_outcome(
        self,
        *,
        ticket: Ticket,
        execution_id: str,
        reason: EscalationReason,
        outcome: AgentOutcome | None,
        escalation: Escalation | None,
        resolution_code: ResolutionCode,
    ) -> Outcome:
        existing = [
            item
            for item in self.repositories.outcomes(ticket.ticket_id)
            if item.metadata.get("execution_id") == execution_id
        ]
        if existing:
            return existing[-1]
        current_ticket = self.repositories.ticket(ticket.ticket_id)
        if current_ticket is not None and current_ticket.resolution_code != resolution_code.value:
            self.repositories.save_ticket(
                current_ticket.model_copy(
                    update={"resolution_code": resolution_code.value}
                )
            )
        metadata: dict[str, object] = {
            "execution_id": execution_id,
            "resolution_code": resolution_code.value,
            "escalation_reason": reason.value,
        }
        if escalation is not None:
            metadata["escalation_id"] = escalation.escalation_id
        if outcome is not None:
            metadata.update(
                {
                    "harness_outcome_id": outcome.outcome_id,
                    "tool_ids": [call.tool_id for call in outcome.tool_calls],
                    "evidence_ids": outcome.evidence_ids,
                }
            )
            if outcome.error_code is not None:
                metadata["error_code"] = outcome.error_code
        return self.conversations.record_outcome(
            ticket.ticket_id,
            outcome_type="support_escalated",
            metadata=metadata,
            execution_id=execution_id,
        )

    @staticmethod
    def _resolution_code_for_completed(outcome: AgentOutcome) -> ResolutionCode:
        tool_ids = {call.tool_id for call in outcome.tool_calls}
        if "cancel_order" in tool_ids:
            return ResolutionCode.ORDER_CANCELLED
        if "request_return" in tool_ids:
            return ResolutionCode.RETURN_CREATED
        if "request_refund" in tool_ids:
            if "get_order_payments" in tool_ids:
                return ResolutionCode.PAYMENT_ISSUE_RESOLVED
            return ResolutionCode.REFUND_REQUESTED
        if "get_shipment" in tool_ids:
            return ResolutionCode.DELIVERY_EXPLAINED
        return ResolutionCode.INFORMATION_PROVIDED

    def _resolution_code_for_escalation(
        self,
        reason: EscalationReason,
        outcome: AgentOutcome | None,
    ) -> ResolutionCode:
        if reason is EscalationReason.BUSINESS_SYSTEM_UNAVAILABLE:
            return ResolutionCode.DEPENDENCY_UNAVAILABLE
        if (
            outcome is not None
            and "request_refund" in {call.tool_id for call in outcome.tool_calls}
            and "business_rule_rejected" in self._failure_codes(outcome)
        ):
            return ResolutionCode.REFUND_DENIED
        if reason is EscalationReason.UNSUPPORTED_REQUEST:
            return ResolutionCode.UNRESOLVED
        return ResolutionCode.ESCALATED_TO_HUMAN

    def _save_pending_approval(
        self,
        request: ApprovalRequest,
        *,
        ticket: Ticket,
        conversation_id: str,
        principal: PrincipalContext,
    ) -> tuple[ApprovalRecord, bool]:
        existing = self.repositories.approvals(execution_id=request.execution_id)
        for record in existing:
            if record.harness_request_id == request.request_id:
                return record, False
        action = request.action.tool_call
        record = ApprovalRecord(
            approval_id=self.assembly.factory.new_id("approval"),
            customer_id=ticket.customer_id,
            ticket_id=ticket.ticket_id,
            conversation_id=conversation_id,
            execution_id=request.execution_id,
            session_id=principal.session_id,
            harness_request_id=request.request_id,
            action_digest=request.action_digest,
            tool_id=action.tool_id,
            action_summary=f"Review {action.tool_id} action {request.action_digest}.",
            requested_at=request.created_at,
        )
        return self.repositories.save_approval(record), True

    def _start_execution_reference(
        self,
        *,
        ticket: Ticket,
        conversation_id: str,
        execution_id: str,
    ) -> ExecutionReference:
        reference = ExecutionReference(
            execution_id=execution_id,
            ticket_id=ticket.ticket_id,
            conversation_id=conversation_id,
            agent_id=SUPPORT_AGENT_ID,
            agent_version=SUPPORT_AGENT_VERSION,
            started_at=now(),
        )
        return self.repositories.save_execution_reference(reference)

    def _update_execution_reference(
        self,
        outcome: AgentOutcome,
        *,
        pending: bool,
        customer_id: str,
    ) -> ExecutionReference | None:
        reference = self.repositories.execution_reference(outcome.execution_id)
        if reference is None:
            return None
        trace_reference = self._trace_reference(
            outcome.execution_id,
            fallback=outcome.trace_id,
        )
        updated = reference.model_copy(
            update={
                "trace_reference": trace_reference,
                "outcome_status": outcome.status.value,
                "completed_at": None if pending else now(),
            }
        )
        saved = self.repositories.save_execution_reference(updated)
        if not pending:
            event_type = (
                CXEventType.AGENT_EXECUTION_FAILED
                if outcome.status
                in {OutcomeStatus.FAILED, OutcomeStatus.TIMED_OUT}
                else CXEventType.AGENT_EXECUTION_COMPLETED
            )
            data = {
                "outcome_id": outcome.outcome_id,
                "outcome_status": outcome.status.value,
                **(
                    {"trace_reference": trace_reference}
                    if trace_reference is not None
                    else {}
                ),
                **(
                    {"error_code": outcome.error_code}
                    if outcome.error_code is not None
                    else {}
                ),
            }
            self.event_service.emit(
                event_type,
                customer_id=customer_id,
                ticket_id=reference.ticket_id,
                conversation_id=reference.conversation_id,
                execution_id=reference.execution_id,
                actor_type=ActorType.AI_AGENT,
                actor_id=reference.agent_id,
                data=data,
            )
        return saved

    def _fail_execution_reference(
        self,
        execution_id: str,
        *,
        customer_id: str,
    ) -> None:
        reference = self.repositories.execution_reference(execution_id)
        if reference is None:
            return
        trace_reference = self._trace_reference(execution_id, fallback=None)
        updated = reference.model_copy(
            update={
                "trace_reference": trace_reference,
                "outcome_status": OutcomeStatus.FAILED.value,
                "completed_at": now(),
            }
        )
        self.repositories.save_execution_reference(updated)
        data = {"outcome_status": OutcomeStatus.FAILED.value}
        if trace_reference is not None:
            data["trace_reference"] = trace_reference
        self.event_service.emit(
            CXEventType.AGENT_EXECUTION_FAILED,
            customer_id=customer_id,
            ticket_id=reference.ticket_id,
            conversation_id=reference.conversation_id,
            execution_id=reference.execution_id,
            actor_type=ActorType.AI_AGENT,
            actor_id=reference.agent_id,
            data=data,
        )

    def _record_tool_events(
        self,
        outcome: AgentOutcome,
        *,
        ticket: Ticket,
        conversation_id: str,
    ) -> None:
        for call in outcome.tool_calls:
            data = {
                "call_id": call.call_id,
                "step_id": call.step_id,
                "tool_id": call.tool_id,
                "tool_version": call.tool_version,
                "result_status": call.result_status.value,
                **(
                    {"evidence_ids": list(call.evidence_ids)}
                    if call.evidence_ids
                    else {}
                ),
                **(
                    {"permission_reason_code": call.permission_reason_code}
                    if call.permission_reason_code is not None
                    else {}
                ),
            }
            event_kwargs = {
                "customer_id": ticket.customer_id,
                "ticket_id": ticket.ticket_id,
                "conversation_id": conversation_id,
                "execution_id": outcome.execution_id,
                "actor_type": ActorType.AI_AGENT,
                "actor_id": SUPPORT_AGENT_ID,
                "data": data,
            }
            self.event_service.emit(CXEventType.AGENT_TOOL_CALLED, **event_kwargs)
            if call.result_status in {
                ToolResultStatus.SUCCEEDED,
                ToolResultStatus.EMPTY,
            }:
                self.event_service.emit(
                    CXEventType.AGENT_TOOL_SUCCEEDED,
                    **event_kwargs,
                )
            elif call.result_status is ToolResultStatus.FAILED:
                self.event_service.emit(
                    CXEventType.AGENT_TOOL_FAILED,
                    **event_kwargs,
                )

    def _trace_reference(
        self,
        execution_id: str,
        *,
        fallback: str | None,
    ) -> str | None:
        try:
            trace = self.agent.trace_for(execution_id)
        except Exception:  # noqa: BLE001 - trace lookup must not block support.
            return fallback
        return trace.trace_id or fallback

    def _bind_memory(
        self,
        principal: PrincipalContext,
        execution_id: str,
        query: str,
        customer_id: str,
        conversation_id: str,
    ) -> None:
        strategy = self.assembly.memory_strategy
        if strategy is None:
            return
        customer_entries = self._search_memory(
            execution_id=execution_id,
            scope=MemoryScope.CUSTOMER,
            query=query,
            customer_id=customer_id,
        )
        shared_entries = self._search_memory(
            execution_id=execution_id,
            scope=MemoryScope.SHARED_SUPPORT,
            query=query,
            capability_id="customer_support",
        )
        strategy.bind(
            principal,
            customer_id=customer_id,
            conversation_id=conversation_id,
            entries=tuple([*customer_entries, *shared_entries][:6]),
        )

    def _search_memory(
        self,
        *,
        execution_id: str,
        scope: MemoryScope,
        query: str,
        customer_id: str | None = None,
        capability_id: str | None = None,
    ) -> list[MemoryEntry]:
        try:
            return self.memory.search_relevant(
                execution_id=execution_id,
                scope=scope,
                query=query,
                customer_id=customer_id,
                capability_id=capability_id,
                limit=3,
            )
        except Exception:  # noqa: BLE001 - memory is advisory and must not block support.
            return []

    def _case(
        self,
        conversation_id: str,
        customer_id: str | None,
    ) -> tuple[Conversation, Ticket]:
        conversation = self.repositories.conversation(conversation_id)
        if conversation is None:
            raise SupportServiceError("conversation was not found")
        if customer_id is not None and customer_id != conversation.customer_id:
            raise SupportServiceError("customer does not own this conversation")
        ticket = self.repositories.ticket(conversation.ticket_id)
        if ticket is None or ticket.customer_id != conversation.customer_id:
            raise SupportServiceError("conversation ticket is invalid")
        return conversation, ticket

    def _principal(self, customer_id: str, session_id: str) -> PrincipalContext:
        return PrincipalContext(
            principal_id=customer_id,
            tenant_id=self.tenant_id,
            session_id=session_id,
        )

    def _append_agent_message(
        self, conversation_id: str, *, execution_id: str, content: str
    ) -> Message:
        return self.conversations.append_message(
            conversation_id,
            actor_type=ActorType.AI_AGENT,
            actor_id=SUPPORT_AGENT_ID,
            content=content,
            execution_id=execution_id,
        )

    def _message_for_execution(
        self,
        conversation_id: str,
        execution_id: str,
        *,
        actor_type: ActorType,
    ) -> str | None:
        for message in reversed(self.repositories.messages(conversation_id)):
            if (
                message.execution_id == execution_id
                and message.actor_type is actor_type
            ):
                return message.message_id
        return None

    def _latest_escalation(self, ticket_id: str) -> Escalation | None:
        values = self.repositories.escalations(ticket_id)
        return values[-1] if values else None

    def _broker_decide(
        self,
        request_id: str,
        *,
        decision: ApprovalDecisionStatus,
        decided_by: str,
        reason_code: str,
    ) -> ApprovalDecision:
        method_name = (
            "approve" if decision is ApprovalDecisionStatus.APPROVED else "reject"
        )
        method = getattr(self.approval_broker, method_name, None)
        if not callable(method):
            raise SupportServiceError(
                "configured approval broker cannot record decisions"
            )
        return method(request_id, decided_by=decided_by, reason_code=reason_code)

    @staticmethod
    def _approval_status(decision: ApprovalDecision) -> ApprovalRecordStatus:
        mapping = {
            ApprovalDecisionStatus.APPROVED: ApprovalRecordStatus.APPROVED,
            ApprovalDecisionStatus.REJECTED: ApprovalRecordStatus.REJECTED,
            ApprovalDecisionStatus.REQUEST_CHANGES: ApprovalRecordStatus.REQUEST_CHANGES,
            ApprovalDecisionStatus.EXPIRED: ApprovalRecordStatus.EXPIRED,
        }
        return mapping[decision.status]

    def _failure_codes(self, outcome: AgentOutcome) -> set[str]:
        return {
            record.error_code
            for record in self.assembly.tools.execution_records
            if record.execution_id == outcome.execution_id
            and record.error_code is not None
        }

    @staticmethod
    def _escalation_reason(
        outcome: AgentOutcome,
        failure_codes: set[str],
    ) -> EscalationReason:
        if outcome.error_code in {"direct_prompt_injection", "unsupported_request"}:
            return EscalationReason.UNSUPPORTED_REQUEST
        if "business_rule_rejected" in failure_codes:
            return EscalationReason.UNSUPPORTED_REQUEST
        if "business_approval_still_required" in failure_codes:
            return EscalationReason.ACTION_REQUIRES_HUMAN
        if outcome.error_code in {"approval_rejected", "approval_expired"}:
            return EscalationReason.ACTION_REQUIRES_HUMAN
        if outcome.error_code in {
            "approval_stale",
            "approval_action_mismatch",
            "approval_request_mismatch",
            "approval_expiry_invalid",
        }:
            return EscalationReason.POLICY_CONFLICT
        if outcome.error_code in {
            "provider_failed",
            "provider_error",
            "provider_timeout",
            "provider_output_invalid",
        }:
            return EscalationReason.AGENT_UNCERTAIN
        if outcome.error_code in {
            "policy_denied",
            "permission_denied",
            "required_permission_missing",
            "tool_not_authorized",
            "tool_not_in_capability",
            "tool_version_not_authorized",
            "tool_not_in_execution_allowlist",
            "runtime_authorization_failed",
        }:
            return EscalationReason.POLICY_CONFLICT
        if outcome.error_code in {
            "tool_failed",
            "all_tools_failed",
            "dependency_unavailable",
            "transport_failure",
        } or any(call.result_status.value == "failed" for call in outcome.tool_calls):
            return EscalationReason.BUSINESS_SYSTEM_UNAVAILABLE
        if outcome.status is OutcomeStatus.REFUSED:
            return EscalationReason.POLICY_CONFLICT
        return EscalationReason.AGENT_UNCERTAIN

    @staticmethod
    def _safe_response(
        outcome: AgentOutcome | None,
        reason: EscalationReason,
    ) -> str:
        if reason is EscalationReason.BUSINESS_SYSTEM_UNAVAILABLE:
            return (
                "I could not verify the current business information. "
                "I have handed this request to a human support specialist."
            )
        if reason is EscalationReason.POLICY_CONFLICT:
            return "I cannot complete that action under the current support policy. I have handed this request to a human support specialist."
        if reason is EscalationReason.UNSUPPORTED_REQUEST:
            return "I cannot safely handle that request. I have handed it to a human support specialist."
        if outcome is not None and outcome.error_code == "approval_expired":
            return "The approval expired before the action could run. I have handed this request to a human support specialist."
        if outcome is not None and outcome.error_code == "approval_rejected":
            return "The reviewed action was rejected. I have handed this request to a human support specialist."
        return "I could not safely complete this request. I have handed it to a human support specialist."

    def _result(
        self,
        outcome: AgentOutcome,
        *,
        ticket_status: TicketStatus,
        customer_id: str,
        ticket_id: str,
        conversation_id: str,
        customer_message_id: str | None,
        agent_message_id: str | None,
        response: str,
        approval_id: str | None = None,
        escalation_id: str | None = None,
        outcome_id: str | None = None,
    ) -> SupportTurnResult:
        return SupportTurnResult(
            customer_id=customer_id,
            ticket_id=ticket_id,
            conversation_id=conversation_id,
            customer_message_id=customer_message_id,
            agent_message_id=agent_message_id,
            execution_id=outcome.execution_id,
            status=outcome.status,
            ticket_status=ticket_status,
            response=response,
            approval_id=approval_id,
            escalation_id=escalation_id,
            outcome_id=outcome_id,
            trace_id=outcome.trace_id,
            error_code=outcome.error_code,
        )


def build_support_service(
    client,
    conversations: ConversationService,
    *,
    repositories: CXRepositories | None = None,
    memory: MemoryPort | None = None,
    short_term_memory: ConversationMemory | None = None,
    workflow_state_store=None,
    tenant_id: str = "cx-platform",
    **agent_options: Any,
) -> SupportService:
    """Build the support service with the real agent and Phase 5 adapters."""

    selected_repositories = repositories or conversations.repositories
    selected_short_term = short_term_memory or ConversationMemory()
    selected_memory = memory or build_memory(evidence_sink=selected_repositories)
    strategy = SupportMemoryStrategy(selected_short_term)
    assembly = assemble_support_agent(
        client,
        conversations,
        memory_strategy=strategy,
        **agent_options,
    )
    workflow_store = workflow_state_store or InMemoryStateStore()
    workflow_state = WorkflowStateManager(
        workflow_store,
        agent_id=SUPPORT_AGENT_ID,
        agent_version=SUPPORT_AGENT_VERSION,
    )
    return SupportService(
        repositories=selected_repositories,
        conversations=conversations,
        assembly=assembly,
        memory=selected_memory,
        short_term_memory=selected_short_term,
        workflow_state=workflow_state,
        tenant_id=tenant_id,
    )


__all__ = [
    "SupportService",
    "SupportServiceError",
    "SupportTurnResult",
    "build_support_service",
]
