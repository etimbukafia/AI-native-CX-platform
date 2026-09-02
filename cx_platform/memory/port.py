"""Small application-owned port for optional cross-session memory."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from cx_platform.domain.models import MemoryOperation, MemoryReference

from .models import (
    MemoryContext,
    MemoryEntry,
    MemoryExplanation,
    MemoryKind,
    MemoryOutcomeResult,
    MemoryScope,
)


class MemoryDependencyError(RuntimeError):
    """Base error for an unavailable or invalid external memory dependency."""


class MemoryUnavailable(MemoryDependencyError):
    """Raised when a memory provider cannot be reached."""


class MemoryResponseError(MemoryDependencyError):
    """Raised when a memory provider returns an invalid response."""


class MemoryConfigurationError(MemoryDependencyError):
    """Raised when a provider is missing required configuration."""


class MemoryEvidenceSink(Protocol):
    """Minimal persistence boundary for memory operation references."""

    def save_memory_reference(self, item: MemoryReference) -> MemoryReference:
        """Persist one small memory reference."""


class MemoryPort(Protocol):
    """Operations needed by CX support. Values are always advisory strings."""

    provider: str

    def search_relevant(
        self,
        *,
        execution_id: str,
        scope: MemoryScope,
        query: str | None = None,
        customer_id: str | None = None,
        capability_id: str | None = None,
        min_confidence: float = 0.0,
        limit: int = 5,
    ) -> list[MemoryEntry]: ...

    def write_memory(
        self,
        *,
        execution_id: str,
        scope: MemoryScope,
        key: str,
        value: str,
        memory_type: MemoryKind,
        confidence: float = 1.0,
        customer_id: str | None = None,
        capability_id: str | None = None,
        confirmed: bool = False,
        conversation_id: str | None = None,
    ) -> MemoryEntry: ...

    def record_context(
        self,
        *,
        execution_id: str,
        label: str,
        summary: str,
        source: str | None = None,
    ) -> MemoryContext: ...

    def commit_outcome(
        self,
        *,
        execution_id: str,
        outcome_id: str,
        outcome_type: str,
        decision_summary: str | None = None,
    ) -> MemoryOutcomeResult: ...

    def explain_usage(
        self,
        *,
        execution_id: str,
        outcome_id: str | None = None,
    ) -> MemoryExplanation: ...


class ResilientMemory:
    """Keep support usable when the optional primary memory is unavailable."""

    provider = "resilient"

    def __init__(
        self,
        primary: MemoryPort,
        *,
        fallback: MemoryPort | None = None,
        evidence_sink: MemoryEvidenceSink | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.evidence_sink = evidence_sink

    def search_relevant(
        self,
        *,
        execution_id: str,
        scope: MemoryScope,
        query: str | None = None,
        customer_id: str | None = None,
        capability_id: str | None = None,
        min_confidence: float = 0.0,
        limit: int = 5,
    ) -> list[MemoryEntry]:
        try:
            return self.primary.search_relevant(
                execution_id=execution_id,
                scope=scope,
                query=query,
                customer_id=customer_id,
                capability_id=capability_id,
                min_confidence=min_confidence,
                limit=limit,
            )
        except MemoryDependencyError as exc:
            self._record_failure(
                execution_id=execution_id,
                operation=MemoryOperation.READ,
                key=query or "search",
                customer_id=customer_id,
                reason=str(exc),
            )
            if self.fallback is None:
                return []
            return self.fallback.search_relevant(
                execution_id=execution_id,
                scope=scope,
                query=query,
                customer_id=customer_id,
                capability_id=capability_id,
                min_confidence=min_confidence,
                limit=limit,
            )

    def write_memory(
        self,
        *,
        execution_id: str,
        scope: MemoryScope,
        key: str,
        value: str,
        memory_type: MemoryKind,
        confidence: float = 1.0,
        customer_id: str | None = None,
        capability_id: str | None = None,
        confirmed: bool = False,
        conversation_id: str | None = None,
    ) -> MemoryEntry:
        try:
            return self.primary.write_memory(
                execution_id=execution_id,
                scope=scope,
                key=key,
                value=value,
                memory_type=memory_type,
                confidence=confidence,
                customer_id=customer_id,
                capability_id=capability_id,
                confirmed=confirmed,
                conversation_id=conversation_id,
            )
        except MemoryDependencyError as exc:
            self._record_failure(
                execution_id=execution_id,
                operation=MemoryOperation.WRITE,
                key=key,
                customer_id=customer_id,
                reason=str(exc),
            )
            if self.fallback is None:
                raise
            return self.fallback.write_memory(
                execution_id=execution_id,
                scope=scope,
                key=key,
                value=value,
                memory_type=memory_type,
                confidence=confidence,
                customer_id=customer_id,
                capability_id=capability_id,
                confirmed=confirmed,
                conversation_id=conversation_id,
            )

    def record_context(
        self,
        *,
        execution_id: str,
        label: str,
        summary: str,
        source: str | None = None,
    ) -> MemoryContext:
        try:
            return self.primary.record_context(
                execution_id=execution_id,
                label=label,
                summary=summary,
                source=source,
            )
        except MemoryDependencyError as exc:
            self._record_failure(
                execution_id=execution_id,
                operation=MemoryOperation.CONTEXT,
                key=label,
                reason=str(exc),
            )
            if self.fallback is None:
                return MemoryContext(
                    context_id=f"failed_context_{uuid4().hex}",
                    execution_id=execution_id,
                    label=label,
                    summary=summary,
                    source=source,
                )
            return self.fallback.record_context(
                execution_id=execution_id,
                label=label,
                summary=summary,
                source=source,
            )

    def commit_outcome(
        self,
        *,
        execution_id: str,
        outcome_id: str,
        outcome_type: str,
        decision_summary: str | None = None,
    ) -> MemoryOutcomeResult:
        try:
            return self.primary.commit_outcome(
                execution_id=execution_id,
                outcome_id=outcome_id,
                outcome_type=outcome_type,
                decision_summary=decision_summary,
            )
        except MemoryDependencyError as exc:
            reason = str(exc)
            self._record_failure(
                execution_id=execution_id,
                operation=MemoryOperation.OUTCOME,
                key=outcome_id,
                outcome_id=outcome_id,
                reason=reason,
            )
            return MemoryOutcomeResult(
                provider=getattr(self.primary, "provider", "memory"),
                outcome_id=outcome_id,
                propagated=False,
                failure_reason=reason,
            )

    def explain_usage(
        self,
        *,
        execution_id: str,
        outcome_id: str | None = None,
    ) -> MemoryExplanation:
        try:
            return self.primary.explain_usage(
                execution_id=execution_id,
                outcome_id=outcome_id,
            )
        except MemoryDependencyError as exc:
            self._record_failure(
                execution_id=execution_id,
                operation=MemoryOperation.READ,
                key="explain",
                outcome_id=outcome_id,
                reason=str(exc),
            )
            if self.fallback is None:
                return MemoryExplanation(
                    provider=getattr(self.primary, "provider", "memory"),
                    execution_id=execution_id,
                    outcome_id=outcome_id,
                )
            return self.fallback.explain_usage(
                execution_id=execution_id,
                outcome_id=outcome_id,
            )

    def _record_failure(
        self,
        *,
        execution_id: str,
        operation: MemoryOperation,
        key: str,
        reason: str,
        customer_id: str | None = None,
        outcome_id: str | None = None,
    ) -> None:
        if self.evidence_sink is None:
            return
        reference = MemoryReference(
            reference_id=f"memory-failure:{execution_id}:{operation.value}:{key}",
            execution_id=execution_id,
            customer_id=customer_id,
            memory_provider=getattr(self.primary, "provider", "memory"),
            memory_entry_id=f"failure:{operation.value}",
            memory_key=f"{key}:{reason[:120]}",
            memory_scope="dependency",
            operation=MemoryOperation.FAILURE,
            outcome_id=outcome_id,
            occurred_at=datetime.now().astimezone(),
        )
        try:
            self.evidence_sink.save_memory_reference(reference)
        except (sqlite3.Error, RuntimeError, TypeError, ValueError):
            return


__all__ = [
    "MemoryConfigurationError",
    "MemoryDependencyError",
    "MemoryEvidenceSink",
    "MemoryPort",
    "MemoryResponseError",
    "MemoryUnavailable",
    "ResilientMemory",
]
