"""SenseLab implementation of the application-owned memory port."""

from __future__ import annotations

import os
import sqlite3
from collections import defaultdict
from copy import deepcopy
from threading import RLock
from uuid import uuid4

import httpx

from cx_platform.domain.models import MemoryOperation, MemoryReference, now

from ..models import (
    MemoryContext,
    MemoryEntry,
    MemoryExplanation,
    MemoryKind,
    MemoryOutcomeResult,
    MemoryProvenance,
    MemoryScope,
)
from ..port import MemoryConfigurationError, MemoryEvidenceSink
from .senselab_http import SENSELAB_DEFAULT_URL, SenseLabHTTPClient
from .senselab_mapping import (
    build_context_request,
    build_explain_params,
    build_outcome_request,
    build_search_request,
    build_write_request,
    map_explanation_response,
    map_outcome_response,
    map_search_response,
    map_write_response,
    validate_context_response,
)


class SenseLabMemory:
    """Coordinate typed CX memory operations through SenseLab HTTP."""

    provider = "senselab"
    default_url = SENSELAB_DEFAULT_URL

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        agent_id: str = "cx-support",
        timeout_seconds: float = 3.0,
        client: httpx.Client | None = None,
        evidence_sink: MemoryEvidenceSink | None = None,
    ) -> None:
        self._http = SenseLabHTTPClient(
            base_url,
            api_key,
            timeout_seconds=timeout_seconds,
            client=client,
        )
        self.base_url = self._http.base_url
        self.agent_id = agent_id
        self.timeout_seconds = self._http.timeout_seconds
        self.evidence_sink = evidence_sink
        self._contexts: dict[str, list[MemoryContext]] = defaultdict(list)
        self._read_entries: dict[str, list[MemoryProvenance]] = defaultdict(list)
        self._read_keys: dict[str, list[str]] = defaultdict(list)
        self._outcomes: set[str] = set()
        self._lock = RLock()

    @classmethod
    def from_environment(
        cls,
        *,
        timeout_seconds: float = 3.0,
        client: httpx.Client | None = None,
        evidence_sink: MemoryEvidenceSink | None = None,
    ) -> SenseLabMemory:
        """Build an adapter from AMFS environment configuration."""

        api_key = os.getenv("AMFS_API_KEY", "")
        if not api_key:
            raise MemoryConfigurationError("AMFS_API_KEY is not configured")
        return cls(
            os.getenv("AMFS_HTTP_URL", cls.default_url),
            api_key,
            agent_id=os.getenv("AMFS_AGENT_ID", "cx-support"),
            timeout_seconds=timeout_seconds,
            client=client,
            evidence_sink=evidence_sink,
        )

    def close(self) -> None:
        """Close the underlying HTTP client when this adapter owns it."""

        self._http.close()

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
        """Search one bounded customer or shared-support namespace."""

        scope = MemoryScope(scope)
        body = build_search_request(
            scope=scope,
            customer_id=customer_id,
            capability_id=capability_id,
            query=query,
            min_confidence=min_confidence,
            limit=limit,
        )
        payload = self._http.request("POST", "/api/v1/search", json_body=body)
        entries = map_search_response(
            payload,
            scope=scope,
            customer_id=customer_id,
            capability_id=capability_id,
            execution_id=execution_id,
        )
        for entry in entries:
            self._remember_read(execution_id, entry)
            self._record(
                self._reference_for_entry(
                    entry=entry,
                    execution_id=execution_id,
                    operation=MemoryOperation.READ,
                )
            )
        return entries

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
        """Write one safe, typed advisory memory entry."""

        scope = MemoryScope(scope)
        memory_type = MemoryKind(memory_type)
        body = build_write_request(
            scope=scope,
            customer_id=customer_id,
            capability_id=capability_id,
            key=key,
            value=value,
            memory_type=memory_type,
            confidence=confidence,
            confirmed=confirmed,
            agent_id=self.agent_id,
            session_id=execution_id,
        )
        payload = self._http.request("POST", "/api/v1/entries", json_body=body)
        entry = map_write_response(
            payload,
            scope=scope,
            customer_id=customer_id,
            capability_id=capability_id,
            key=key,
            execution_id=execution_id,
            conversation_id=conversation_id,
        )
        self._record(
            self._reference_for_entry(
                entry=entry,
                execution_id=execution_id,
                operation=MemoryOperation.WRITE,
            )
        )
        return entry

    def record_context(
        self,
        *,
        execution_id: str,
        label: str,
        summary: str,
        source: str | None = None,
    ) -> MemoryContext:
        """Record one external context block in the SenseLab causal chain."""

        context = MemoryContext(
            context_id=f"senselab_context_{uuid4().hex}",
            execution_id=execution_id,
            label=label,
            summary=summary,
            source=source,
        )
        body = build_context_request(
            label=label,
            summary=summary,
            source=source,
            agent_id=self.agent_id,
        )
        payload = self._http.request("POST", "/api/v1/context", json_body=body)
        validate_context_response(payload, label=label)
        with self._lock:
            self._contexts[execution_id].append(context)
        self._record(
            MemoryReference(
                reference_id=f"memory:{self.provider}:{execution_id}:context:{context.context_id}",
                execution_id=execution_id,
                memory_provider=self.provider,
                memory_entry_id=context.context_id,
                memory_key=context.label,
                memory_scope="context",
                operation=MemoryOperation.CONTEXT,
                occurred_at=context.occurred_at,
            )
        )
        return context

    def commit_outcome(
        self,
        *,
        execution_id: str,
        outcome_id: str,
        outcome_type: str,
        decision_summary: str | None = None,
    ) -> MemoryOutcomeResult:
        """Send one CX outcome and the entries read by this execution."""

        with self._lock:
            causal_keys = list(dict.fromkeys(self._read_keys.get(execution_id, [])))
        body = build_outcome_request(
            outcome_id=outcome_id,
            outcome_type=outcome_type,
            causal_entry_keys=causal_keys or None,
            agent_id=self.agent_id,
            decision_summary=decision_summary,
        )
        payload = self._http.request("POST", "/api/v1/outcomes", json_body=body)
        entry_ids = map_outcome_response(payload)
        with self._lock:
            self._outcomes.add(outcome_id)
        self._record(
            MemoryReference(
                reference_id=f"memory:{self.provider}:{execution_id}:outcome:{outcome_id}",
                execution_id=execution_id,
                memory_provider=self.provider,
                memory_entry_id=f"outcome:{outcome_id}",
                memory_key=outcome_id,
                memory_scope="outcome",
                operation=MemoryOperation.OUTCOME,
                outcome_id=outcome_id,
            )
        )
        return MemoryOutcomeResult(
            provider=self.provider,
            outcome_id=outcome_id,
            propagated=True,
            memory_entry_ids=entry_ids,
        )

    def explain_usage(
        self,
        *,
        execution_id: str,
        outcome_id: str | None = None,
    ) -> MemoryExplanation:
        """Return a safe explanation of memory and context used by an execution."""

        payload = self._http.request(
            "GET",
            "/api/v1/explain",
            params=build_explain_params(outcome_id),
        )
        remote_outcome_id, remote_entries, remote_contexts = map_explanation_response(
            payload,
            execution_id=execution_id,
        )
        with self._lock:
            local_entries = tuple(deepcopy(self._read_entries.get(execution_id, [])))
            local_contexts = tuple(deepcopy(self._contexts.get(execution_id, [])))
            committed = outcome_id is not None and outcome_id in self._outcomes
        entries = self._merge_provenance(local_entries, remote_entries)
        contexts = self._merge_contexts(local_contexts, remote_contexts)
        committed = committed or bool(outcome_id and remote_outcome_id == outcome_id)
        return MemoryExplanation(
            provider=self.provider,
            execution_id=execution_id,
            outcome_id=outcome_id,
            entries=entries,
            contexts=contexts,
            outcome_committed=committed,
        )

    def _remember_read(self, execution_id: str, entry: MemoryEntry) -> None:
        with self._lock:
            self._read_entries[execution_id].append(entry.provenance)
            self._read_keys[execution_id].append(f"{entry.entity_path}/{entry.key}")

    def _record(self, reference: MemoryReference) -> None:
        if self.evidence_sink is None:
            return
        try:
            self.evidence_sink.save_memory_reference(reference)
        except (sqlite3.Error, RuntimeError, TypeError, ValueError):
            return

    def _reference_for_entry(
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

    @staticmethod
    def _merge_provenance(
        local: tuple[MemoryProvenance, ...],
        remote: tuple[MemoryProvenance, ...],
    ) -> tuple[MemoryProvenance, ...]:
        values: dict[tuple[str, str, int], MemoryProvenance] = {
            (item.provider, item.entry_id, item.version): item for item in local
        }
        values.update(
            {(item.provider, item.entry_id, item.version): item for item in remote}
        )
        return tuple(values.values())

    @staticmethod
    def _merge_contexts(
        local: tuple[MemoryContext, ...],
        remote: tuple[MemoryContext, ...],
    ) -> tuple[MemoryContext, ...]:
        values = {item.context_id: item for item in local}
        values.update({item.context_id: item for item in remote})
        return tuple(values.values())


__all__ = ["SenseLabMemory"]
