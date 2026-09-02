"""Deterministic, bounded memory adapter for local runs and CI."""

from __future__ import annotations

import re
import sqlite3
from copy import deepcopy
from threading import RLock

from cx_platform.domain.models import MemoryOperation, MemoryReference, now

from .models import (
    MemoryContext,
    MemoryEntry,
    MemoryExplanation,
    MemoryKind,
    MemoryOutcomeResult,
    MemoryProvenance,
    MemoryScope,
)
from .port import MemoryEvidenceSink

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]+$")
_BUSINESS_TERMS = {
    "order",
    "shipment",
    "payment",
    "refund",
    "return",
    "cancel",
    "cancellation",
    "policy",
    "account",
    "status",
    "state",
    "eligible",
}
_CURRENT_BUSINESS_KEYS = {
    "order_id",
    "line_id",
    "shipment_id",
    "payment_id",
    "refund_id",
    "return_id",
    "order_status",
    "shipment_status",
    "payment_status",
    "refund_is_allowed",
    "return_is_allowed",
    "cancel_is_allowed",
}


class LocalMemory:
    """Keep current memory entries in a small deterministic in-process store."""

    provider = "local"

    def __init__(
        self,
        *,
        max_entries: int = 128,
        max_results: int = 5,
        evidence_sink: MemoryEvidenceSink | None = None,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        if max_results < 1:
            raise ValueError("max_results must be positive")
        self.max_entries = max_entries
        self.max_results = max_results
        self.evidence_sink = evidence_sink
        self._entries: dict[tuple[MemoryScope, str, str], MemoryEntry] = {}
        self._contexts: dict[str, list[MemoryContext]] = {}
        self._read_usage: dict[str, list[MemoryProvenance]] = {}
        self._outcomes: dict[str, str] = {}
        self._counter = 0
        self._context_counter = 0
        self._lock = RLock()

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
        scope = MemoryScope(scope)
        self._validate_search(
            scope=scope,
            customer_id=customer_id,
            capability_id=capability_id,
            min_confidence=min_confidence,
            limit=limit,
        )
        entity_path = self._entity_path(
            scope,
            customer_id=customer_id,
            capability_id=capability_id,
        )
        query_text = query.lower().strip() if query else None
        with self._lock:
            candidates = [
                entry
                for (entry_scope, path, _), entry in self._entries.items()
                if entry_scope is scope
                and path == entity_path
                and entry.confidence >= min_confidence
                and (
                    query_text is None
                    or query_text in entry.key.lower()
                    or query_text in entry.value.lower()
                )
            ]
            candidates.sort(
                key=lambda entry: (-entry.confidence, -entry.version, entry.memory_id)
            )
            selected = deepcopy(candidates[: min(limit, self.max_results)])

        for entry in selected:
            reference = self._operation_reference(
                entry=entry,
                execution_id=execution_id,
                operation=MemoryOperation.READ,
            )
            with self._lock:
                usage = self._read_usage.setdefault(execution_id, [])
                usage.append(
                    entry.provenance.model_copy(
                        update={
                            "operation": MemoryOperation.READ,
                            "execution_id": execution_id,
                            "occurred_at": reference.occurred_at,
                        }
                    )
                )
            self._record(reference)
            selected[selected.index(entry)] = entry.model_copy(
                update={"provenance": reference_to_provenance(reference)}
            )
        return selected

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
        scope = MemoryScope(scope)
        memory_type = MemoryKind(memory_type)
        self._validate_write(
            scope=scope,
            key=key,
            value=value,
            memory_type=memory_type,
            confidence=confidence,
            customer_id=customer_id,
            capability_id=capability_id,
            confirmed=confirmed,
        )
        entity_path = self._entity_path(
            scope,
            customer_id=customer_id,
            capability_id=capability_id,
        )
        entry_key = (scope, entity_path, key)
        with self._lock:
            previous = self._entries.get(entry_key)
            version = previous.version + 1 if previous else 1
            self._counter += 1
            memory_id = f"local_memory_{self._counter}"
            entry = MemoryEntry(
                memory_id=memory_id,
                entity_path=entity_path,
                key=key,
                value=value,
                memory_type=memory_type,
                confidence=confidence,
                version=version,
                scope=scope,
                customer_id=customer_id,
                conversation_id=conversation_id,
                capability_id=capability_id,
                provenance=MemoryProvenance(
                    provider=self.provider,
                    entry_id=memory_id,
                    key=key,
                    version=version,
                    scope=scope,
                    operation=MemoryOperation.WRITE,
                    execution_id=execution_id,
                    conversation_id=conversation_id,
                ),
            )
            self._entries[entry_key] = entry
            self._trim_entries()
        self._record(
            self._operation_reference(
                entry=entry,
                execution_id=execution_id,
                operation=MemoryOperation.WRITE,
            )
        )
        return deepcopy(entry)

    def record_context(
        self,
        *,
        execution_id: str,
        label: str,
        summary: str,
        source: str | None = None,
    ) -> MemoryContext:
        context = MemoryContext(
            context_id=self._next_context_id(),
            execution_id=execution_id,
            label=label,
            summary=summary,
            source=source,
        )
        with self._lock:
            values = self._contexts.setdefault(execution_id, [])
            values.append(context)
            del values[:-self.max_results]
        self._record_context_reference(context)
        return context

    def commit_outcome(
        self,
        *,
        execution_id: str,
        outcome_id: str,
        outcome_type: str,
        decision_summary: str | None = None,
    ) -> MemoryOutcomeResult:
        del decision_summary
        with self._lock:
            self._outcomes[outcome_id] = outcome_type
            causal_entries = self._read_usage.get(execution_id, [])
        reference = MemoryReference(
            reference_id=f"memory:{self.provider}:{execution_id}:outcome:{outcome_id}",
            execution_id=execution_id,
            memory_provider=self.provider,
            memory_entry_id=f"outcome:{outcome_id}",
            memory_key=outcome_id,
            memory_scope="outcome",
            operation=MemoryOperation.OUTCOME,
            outcome_id=outcome_id,
        )
        self._record(reference)
        return MemoryOutcomeResult(
            provider=self.provider,
            outcome_id=outcome_id,
            propagated=True,
            memory_entry_ids=tuple(item.entry_id for item in causal_entries),
        )

    def explain_usage(
        self,
        *,
        execution_id: str,
        outcome_id: str | None = None,
    ) -> MemoryExplanation:
        with self._lock:
            entries = tuple(deepcopy(self._read_usage.get(execution_id, [])))
            contexts = tuple(deepcopy(self._contexts.get(execution_id, [])))
            committed = outcome_id is not None and outcome_id in self._outcomes
        return MemoryExplanation(
            provider=self.provider,
            execution_id=execution_id,
            outcome_id=outcome_id,
            entries=entries,
            contexts=contexts,
            outcome_committed=committed,
        )

    def _validate_search(
        self,
        *,
        scope: MemoryScope,
        customer_id: str | None,
        capability_id: str | None,
        min_confidence: float,
        limit: int,
    ) -> None:
        if limit < 1 or limit > self.max_results:
            raise ValueError(f"limit must be between 1 and {self.max_results}")
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0 and 1")
        self._validate_scope(scope, customer_id, capability_id)

    def _validate_write(
        self,
        *,
        scope: MemoryScope,
        key: str,
        value: str,
        memory_type: MemoryKind,
        confidence: float,
        customer_id: str | None,
        capability_id: str | None,
        confirmed: bool,
    ) -> None:
        if not key or len(key) > 120 or not _IDENTIFIER.fullmatch(key):
            raise ValueError("memory key must be a short identifier")
        if not value or len(value) > 2000:
            raise ValueError("memory value must be between 1 and 2000 characters")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        self._validate_scope(scope, customer_id, capability_id)
        if scope is MemoryScope.CUSTOMER and not confirmed:
            raise ValueError("customer memory requires explicit confirmation")
        if self._contains_current_business_key(key):
            raise ValueError("memory cannot store current business state")
        if (
            scope is MemoryScope.SHARED_SUPPORT
            and memory_type is MemoryKind.FACT
            and self._contains_business_term(key)
        ):
            raise ValueError("shared memory cannot store current business state")

    @staticmethod
    def _validate_scope(
        scope: MemoryScope,
        customer_id: str | None,
        capability_id: str | None,
    ) -> None:
        if scope is MemoryScope.CUSTOMER:
            if not customer_id or not _IDENTIFIER.fullmatch(customer_id):
                raise ValueError("customer memory requires a valid customer ID")
            if capability_id is not None:
                raise ValueError("customer memory cannot use a capability ID")
        elif scope is MemoryScope.SHARED_SUPPORT:
            if not capability_id or not _IDENTIFIER.fullmatch(capability_id):
                raise ValueError("shared memory requires a capability ID")
            if customer_id is not None:
                raise ValueError("shared memory cannot use a customer ID")

    @staticmethod
    def _contains_business_term(key: str) -> bool:
        parts = set(re.split(r"[_:.\-]+", key.lower()))
        return bool(parts & _BUSINESS_TERMS)

    @staticmethod
    def _contains_current_business_key(key: str) -> bool:
        normalized = key.lower().replace("-", "_")
        return normalized in _CURRENT_BUSINESS_KEYS

    @staticmethod
    def _entity_path(
        scope: MemoryScope,
        *,
        customer_id: str | None,
        capability_id: str | None,
    ) -> str:
        if scope is MemoryScope.CUSTOMER:
            assert customer_id is not None
            return f"customers/{customer_id}"
        assert capability_id is not None
        return f"support/{capability_id}"

    def _trim_entries(self) -> None:
        if len(self._entries) <= self.max_entries:
            return
        ordered = sorted(
            self._entries.items(),
            key=lambda item: item[1].provenance.occurred_at,
        )
        for entry_key, _ in ordered[: len(self._entries) - self.max_entries]:
            del self._entries[entry_key]

    def _next_context_id(self) -> str:
        with self._lock:
            self._context_counter += 1
            return f"local_context_{self._context_counter}"

    def _operation_reference(
        self,
        *,
        entry: MemoryEntry,
        execution_id: str,
        operation: MemoryOperation,
    ) -> MemoryReference:
        return MemoryReference(
            reference_id=(
                f"memory:{self.provider}:{execution_id}:{operation.value}:"
                f"{entry.memory_id}:{entry.version}"
            ),
            execution_id=execution_id,
            customer_id=entry.customer_id,
            conversation_id=entry.conversation_id,
            memory_provider=self.provider,
            memory_entry_id=entry.memory_id,
            memory_key=entry.key,
            memory_version=entry.version,
            memory_scope=entry.scope.value,
            operation=operation,
            occurred_at=now(),
        )

    def _record(self, reference: MemoryReference) -> None:
        if self.evidence_sink is None:
            return
        try:
            self.evidence_sink.save_memory_reference(reference)
        except (sqlite3.Error, RuntimeError, TypeError, ValueError):
            return

    def _record_context_reference(self, context: MemoryContext) -> None:
        self._record(
            MemoryReference(
                reference_id=f"memory:{self.provider}:{context.execution_id}:context:{context.context_id}",
                execution_id=context.execution_id,
                memory_provider=self.provider,
                memory_entry_id=context.context_id,
                memory_key=context.label,
                memory_scope="context",
                operation=MemoryOperation.CONTEXT,
                occurred_at=context.occurred_at,
            )
        )


def reference_to_provenance(reference: MemoryReference) -> MemoryProvenance:
    """Map a CX evidence reference back to a typed memory provenance value."""

    if reference.memory_version is None:
        raise ValueError("entry references require a memory version")
    return MemoryProvenance(
        provider=reference.memory_provider,
        entry_id=reference.memory_entry_id,
        key=reference.memory_key,
        version=reference.memory_version,
        scope=MemoryScope(reference.memory_scope),
        operation=reference.operation,
        execution_id=reference.execution_id,
        conversation_id=reference.conversation_id,
        occurred_at=reference.occurred_at,
    )


__all__ = ["LocalMemory"]
