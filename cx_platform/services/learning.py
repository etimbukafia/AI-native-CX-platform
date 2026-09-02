"""Secondary outcome signals for optional cross-session learning."""

from __future__ import annotations

import sqlite3
from enum import StrEnum

from cx_platform.domain.models import MemoryOperation, MemoryReference, now
from cx_platform.memory.models import MemoryOutcomeResult
from cx_platform.memory.port import MemoryDependencyError, MemoryPort
from cx_platform.persistence.sqlite import CXRepositories


class LearningSignal(StrEnum):
    """CX signals that can be mapped to SenseLab outcome types."""

    RESOLVED = "resolved"
    RESOLVED_AFTER_ESCALATION = "resolved_after_escalation"
    UNRESOLVED = "unresolved"
    CUSTOMER_ABANDONED = "customer_abandoned"
    POSITIVE_CSAT = "positive_csat"
    NEGATIVE_CSAT = "negative_csat"
    POLICY_REJECTED = "policy_rejected"
    DEPENDENCY_FAILURE = "dependency_failure"


_SENSELAB_OUTCOME_TYPES = {
    "success",
    "failure",
    "minor_failure",
    "critical_failure",
}
_SIGNAL_MAPPING = {
    LearningSignal.RESOLVED.value: "success",
    LearningSignal.RESOLVED_AFTER_ESCALATION.value: "success",
    LearningSignal.UNRESOLVED.value: "failure",
    LearningSignal.CUSTOMER_ABANDONED.value: "minor_failure",
    LearningSignal.POSITIVE_CSAT.value: "success",
    LearningSignal.NEGATIVE_CSAT.value: "minor_failure",
}


class OutcomeLearningService:
    """Commit memory signals only after CX records the source outcome."""

    def __init__(
        self,
        repositories: CXRepositories,
        memory: MemoryPort,
    ) -> None:
        self.repositories = repositories
        self.memory = memory

    def commit_outcome(
        self,
        *,
        execution_id: str,
        outcome_id: str,
        outcome_type: str,
        decision_summary: str | None = None,
    ) -> MemoryOutcomeResult:
        outcome = self.repositories.outcome(outcome_id)
        if outcome is None:
            raise KeyError(outcome_id)
        ticket = self.repositories.ticket(outcome.ticket_id)
        if ticket is None:
            raise KeyError(outcome.ticket_id)
        external_type = _map_signal(outcome_type)
        if external_type is None:
            result = MemoryOutcomeResult(
                provider=getattr(self.memory, "provider", "memory"),
                outcome_id=outcome.outcome_id,
                propagated=False,
                failure_reason="CX outcome is not eligible for memory learning",
            )
            self._record_outcome_reference(
                execution_id=execution_id,
                outcome_id=outcome.outcome_id,
                result=result,
                customer_id=ticket.customer_id,
                conversation_id=ticket.conversation_id,
            )
            return result
        result = self._commit(
            execution_id=execution_id,
            outcome_id=outcome.outcome_id,
            outcome_type=external_type,
            decision_summary=decision_summary,
        )
        self._record_outcome_reference(
            execution_id=execution_id,
            outcome_id=outcome.outcome_id,
            result=result,
            customer_id=ticket.customer_id,
            conversation_id=ticket.conversation_id,
        )
        return result

    def commit_csat_signal(
        self,
        *,
        execution_id: str,
        csat_id: str,
    ) -> MemoryOutcomeResult:
        csat = self.repositories.csat(csat_id)
        if csat is None:
            raise KeyError(csat_id)
        ticket = self.repositories.ticket(csat.ticket_id)
        if ticket is None:
            raise KeyError(csat.ticket_id)
        if csat.score >= 4:
            signal = "positive_csat"
        elif csat.score <= 2:
            signal = "negative_csat"
        else:
            signal = "neutral_csat"
        external_type = _map_signal(signal)
        if external_type is None:
            result = MemoryOutcomeResult(
                provider=getattr(self.memory, "provider", "memory"),
                outcome_id=csat.csat_id,
                propagated=False,
                failure_reason="neutral CSAT is not eligible for memory learning",
            )
            self._record_outcome_reference(
                execution_id=execution_id,
                outcome_id=csat.csat_id,
                result=result,
                csat_id=csat.csat_id,
                customer_id=ticket.customer_id,
                conversation_id=ticket.conversation_id,
            )
            return result
        result = self._commit(
            execution_id=execution_id,
            outcome_id=csat.csat_id,
            outcome_type=external_type,
            decision_summary="Customer feedback signal",
        )
        self._record_outcome_reference(
            execution_id=execution_id,
            outcome_id=csat.csat_id,
            result=result,
            csat_id=csat.csat_id,
            customer_id=ticket.customer_id,
            conversation_id=ticket.conversation_id,
        )
        return result

    def _commit(
        self,
        *,
        execution_id: str,
        outcome_id: str,
        outcome_type: str,
        decision_summary: str | None,
    ) -> MemoryOutcomeResult:
        try:
            return self.memory.commit_outcome(
                execution_id=execution_id,
                outcome_id=outcome_id,
                outcome_type=outcome_type,
                decision_summary=decision_summary,
            )
        except (MemoryDependencyError, RuntimeError) as exc:
            provider = getattr(self.memory, "provider", "memory")
            return MemoryOutcomeResult(
                provider=provider,
                outcome_id=outcome_id,
                propagated=False,
                failure_reason=str(exc),
            )

    def _record_outcome_reference(
        self,
        *,
        execution_id: str,
        outcome_id: str,
        result: MemoryOutcomeResult,
        csat_id: str | None = None,
        customer_id: str | None = None,
        conversation_id: str | None = None,
    ) -> None:
        reference = MemoryReference(
            reference_id=f"memory:{result.provider}:{execution_id}:outcome:{outcome_id}",
            execution_id=execution_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            memory_provider=result.provider,
            memory_entry_id=f"outcome:{outcome_id}",
            memory_key=outcome_id,
            memory_scope="outcome",
            operation=MemoryOperation.OUTCOME,
            outcome_id=None if csat_id else outcome_id,
            csat_id=csat_id,
            occurred_at=now(),
        )
        try:
            self.repositories.save_memory_reference(reference)
        except (sqlite3.Error, RuntimeError, TypeError, ValueError):
            return
        if not result.propagated:
            failure = reference.model_copy(
                update={
                    "reference_id": (
                        f"memory-failure:{result.provider}:{execution_id}:"
                        f"outcome:{outcome_id}"
                    ),
                    "memory_entry_id": f"failure:outcome:{outcome_id}",
                    "memory_key": result.failure_reason or outcome_id,
                    "operation": MemoryOperation.FAILURE,
                }
            )
            try:
                self.repositories.save_memory_reference(failure)
            except (sqlite3.Error, RuntimeError, TypeError, ValueError):
                return


__all__ = ["LearningSignal", "OutcomeLearningService"]


def _map_signal(signal: str) -> str | None:
    normalized = signal.strip().lower()
    if normalized in _SENSELAB_OUTCOME_TYPES:
        return normalized
    return _SIGNAL_MAPPING.get(normalized)
