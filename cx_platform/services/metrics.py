"""Small aggregate CX metrics derived from persisted evidence."""

from __future__ import annotations

from collections.abc import Sequence

from cx_platform.domain.models import CXEventType, CXMetrics, OutcomeRead
from cx_platform.persistence import CXRepositories
from cx_platform.services.outcomes import CXOutcomeService


class CXMetricsService:
    """Calculate reproducible metrics for the current CX database."""

    def __init__(
        self,
        repositories: CXRepositories,
        outcomes: CXOutcomeService | None = None,
    ) -> None:
        self.repositories = repositories
        self.outcomes = outcomes or CXOutcomeService(repositories)

    def compute(self) -> CXMetrics:
        conversations = self.repositories.all_conversations()
        all_outcomes = self.outcomes.list_outcomes(limit=1_000_000)
        outcomes = [
            outcome
            for outcome in all_outcomes
            if outcome.resolved or outcome.escalated
        ]
        terminal_count = len(outcomes)
        resolved_count = sum(item.resolved for item in outcomes)
        escalated_count = sum(item.escalated for item in outcomes)

        events = self.repositories.all_events()
        tool_calls = [
            event
            for event in events
            if event.event_type is CXEventType.AGENT_TOOL_CALLED
        ]
        tool_failures = [
            event
            for event in events
            if event.event_type is CXEventType.AGENT_TOOL_FAILED
        ]
        approvals = self.repositories.approvals()
        decided_approvals = [
            record
            for record in approvals
            if record.status.value != "PENDING"
        ]
        csat = self.repositories.all_csats()

        return CXMetrics(
            conversation_count=len(conversations),
            terminal_outcome_count=terminal_count,
            resolved_count=resolved_count,
            resolution_rate=_rate(resolved_count, terminal_count),
            escalated_count=escalated_count,
            escalation_rate=_rate(escalated_count, terminal_count),
            average_turns=(
                sum(self._turn_count(item.conversation_id) for item in conversations)
                / len(conversations)
                if conversations
                else 0.0
            ),
            tool_call_count=len(tool_calls),
            tool_failure_count=len(tool_failures),
            tool_failure_rate=_rate(len(tool_failures), len(tool_calls)),
            approval_count=len(approvals),
            approval_decided_count=len(decided_approvals),
            approval_rate=_rate(
                sum(record.status.value == "APPROVED" for record in decided_approvals),
                len(decided_approvals),
            ),
            average_submitted_csat=(
                sum(item.score for item in csat) / len(csat) if csat else None
            ),
            outcome_distribution=_distribution(outcomes),
        )

    def _turn_count(self, conversation_id: str) -> int:
        return sum(
            message.actor_type.value == "CUSTOMER"
            for message in self.repositories.messages(conversation_id)
        )


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _distribution(outcomes: Sequence[OutcomeRead]) -> dict[str, int]:
    distribution: dict[str, int] = {}
    for outcome in outcomes:
        key = outcome.resolution_code.value
        distribution[key] = distribution.get(key, 0) + 1
    return distribution


__all__ = ["CXMetricsService"]
