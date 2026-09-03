"""Structured outcome reads derived from CX-owned evidence."""

from __future__ import annotations

from collections.abc import Sequence

from cx_platform.domain.models import (
    ApprovalRecord,
    ApprovalRecordStatus,
    CXEventType,
    Escalation,
    ExecutionReference,
    Outcome,
    OutcomeRead,
    ResolutionCode,
    TicketStatus,
)
from cx_platform.persistence import CXRepositories


class CXOutcomeService:
    """Build small, reproducible outcome views without copying external traces."""

    def __init__(self, repositories: CXRepositories) -> None:
        self.repositories = repositories

    def list_outcomes(
        self,
        *,
        ticket_id: str | None = None,
        after: str | None = None,
        limit: int = 100,
    ) -> list[OutcomeRead]:
        if limit < 1:
            raise ValueError("outcome limit must be positive")
        outcomes = self.repositories.outcomes(ticket_id)
        if after is not None:
            try:
                start = next(
                    index
                    for index, outcome in enumerate(outcomes)
                    if outcome.outcome_id == after
                )
            except StopIteration as exc:
                raise KeyError(f"unknown CX outcome cursor: {after}") from exc
            outcomes = outcomes[start + 1 :]
        return [self._read(outcome) for outcome in outcomes[:limit]]

    def read(self, outcome_id: str) -> OutcomeRead | None:
        outcome = self.repositories.outcome(outcome_id)
        return None if outcome is None else self._read(outcome)

    def _read(self, outcome: Outcome) -> OutcomeRead:
        ticket = self.repositories.ticket(outcome.ticket_id)
        if ticket is None:
            raise KeyError(outcome.ticket_id)

        execution_id = _string_value(outcome.metadata.get("execution_id"))
        execution = (
            self.repositories.execution_reference(execution_id)
            if execution_id is not None
            else None
        )
        events = [
            event
            for event in self.repositories.all_events()
            if event.ticket_id == ticket.ticket_id
            and (
                execution_id is None
                or event.execution_id == execution_id
            )
        ]
        tool_called = [
            event
            for event in events
            if event.event_type is CXEventType.AGENT_TOOL_CALLED
        ]
        tool_failed = [
            event
            for event in events
            if event.event_type is CXEventType.AGENT_TOOL_FAILED
        ]
        tool_ids = _unique_strings(
            [
                _string_value(event.data.get("tool_id"))
                for event in tool_called
            ]
        )
        if not tool_ids:
            tool_ids = _unique_strings(_string_values(outcome.metadata.get("tool_ids")))

        escalation = self._escalation(ticket.ticket_id, execution_id, outcome)
        approvals = (
            self.repositories.approvals(execution_id=execution_id)
            if execution_id is not None
            else []
        )
        approval_result = _approval_result(approvals)
        csat = self.repositories.csats(ticket.ticket_id)
        duration = _duration(execution)
        escalated_outcome = (
            outcome.outcome_type == "support_escalated"
            or _string_value(outcome.metadata.get("escalation_id")) is not None
        )
        return OutcomeRead(
            outcome_id=outcome.outcome_id,
            ticket_id=ticket.ticket_id,
            execution_id=execution_id,
            resolution_code=_resolution_code(ticket.resolution_code),
            resolved=(
                not escalated_outcome
                and ticket.status in {TicketStatus.RESOLVED, TicketStatus.CLOSED}
            ),
            escalated=(escalated_outcome or ticket.status is TicketStatus.ESCALATED),
            turn_count=self._turn_count(ticket.conversation_id),
            tool_call_count=len(tool_called),
            tool_failure_count=len(tool_failed),
            approval_required=bool(approvals),
            approval_result=approval_result,
            duration=duration,
            csat_score=csat[-1].score if csat else None,
            escalation_id=(
                escalation.escalation_id if escalation is not None else None
            ),
            tool_ids=tool_ids,
            evidence_ids=_unique_strings(
                _string_values(outcome.metadata.get("evidence_ids"))
            ),
            created_at=outcome.created_at,
        )

    def _turn_count(self, conversation_id: str) -> int:
        return sum(
            message.actor_type.value == "CUSTOMER"
            for message in self.repositories.messages(conversation_id)
        )

    def _escalation(
        self,
        ticket_id: str,
        execution_id: str | None,
        outcome: Outcome,
    ) -> Escalation | None:
        escalation_id = _string_value(outcome.metadata.get("escalation_id"))
        if escalation_id is not None:
            escalation = self.repositories.escalation(escalation_id)
            if escalation is not None:
                return escalation
        escalations = self.repositories.escalations(ticket_id)
        if execution_id is not None:
            matching = [
                escalation
                for escalation in escalations
                if escalation.execution_id == execution_id
            ]
            return matching[-1] if matching else None
        return escalations[-1] if escalations else None


def _resolution_code(value: str | None) -> ResolutionCode:
    try:
        return ResolutionCode(value or "")
    except ValueError:
        return ResolutionCode.UNRESOLVED


def _approval_result(records: Sequence[ApprovalRecord]) -> ApprovalRecordStatus | None:
    for record in reversed(records):
        if record.status is not ApprovalRecordStatus.PENDING:
            return record.status
    return None


def _duration(execution: ExecutionReference | None) -> float | None:
    if execution is None or execution.completed_at is None:
        return None
    return max(
        0.0,
        (execution.completed_at - execution.started_at).total_seconds(),
    )


def _string_value(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _string_values(value: object) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []


def _unique_strings(values: list[str | None]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value is not None))


__all__ = ["CXOutcomeService"]
