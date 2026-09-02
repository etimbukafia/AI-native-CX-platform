"""SenseLab AMFS adapter using its documented HTTP boundary."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections import defaultdict
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from threading import RLock
from typing import cast
from uuid import uuid4

import httpx

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
from .port import (
    MemoryConfigurationError,
    MemoryEvidenceSink,
    MemoryResponseError,
    MemoryUnavailable,
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.:-]+$")
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
_SHARED_BUSINESS_TERMS = {
    "order",
    "shipment",
    "payment",
    "refund",
    "return",
    "cancel",
    "policy",
    "account",
    "status",
    "state",
    "eligible",
}


class SenseLabMemory:
    """Map the small CX memory port to SenseLab AMFS REST operations."""

    provider = "senselab"
    default_url = "https://amfs-login.sense-lab.ai"

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
        if not base_url.strip():
            raise MemoryConfigurationError("SenseLab URL is required")
        if not api_key.strip():
            raise MemoryConfigurationError("SenseLab API key is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self.base_url = base_url.rstrip("/")
        self.agent_id = agent_id
        self.timeout_seconds = timeout_seconds
        self.evidence_sink = evidence_sink
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self.base_url,
            headers={"X-AMFS-API-Key": api_key},
            timeout=timeout_seconds,
        )
        self._client.headers.setdefault("X-AMFS-API-Key", api_key)
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
        api_key = os.getenv("AMFS_API_KEY", "")
        base_url = os.getenv("AMFS_HTTP_URL", cls.default_url)
        agent_id = os.getenv("AMFS_AGENT_ID", "cx-support")
        if not api_key:
            raise MemoryConfigurationError("AMFS_API_KEY is not configured")
        return cls(
            base_url,
            api_key,
            agent_id=agent_id,
            timeout_seconds=timeout_seconds,
            client=client,
            evidence_sink=evidence_sink,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

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
        self._validate_scope(scope, customer_id, capability_id)
        if limit < 1 or limit > 20:
            raise ValueError("limit must be between 1 and 20")
        if not 0.0 <= min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0 and 1")
        body: dict[str, object] = {
            "entity_path": self._entity_path(scope, customer_id, capability_id),
            "min_confidence": min_confidence,
            "sort_by": "confidence",
            "limit": limit,
            "branch": "main",
        }
        if query:
            body["query"] = query
        payload = self._request("POST", "/api/v1/search", json_body=body)
        self._raise_if_error(payload, "search")
        rows = self._entry_rows(payload)
        expected_path = str(body["entity_path"])
        if any(row.get("entity_path") != expected_path for row in rows):
            raise MemoryResponseError("SenseLab returned an entry outside the requested scope")
        entries = [
            self._entry_from_response(
                row,
                scope=scope,
                customer_id=customer_id,
                capability_id=capability_id,
                execution_id=execution_id,
                conversation_id=None,
                operation=MemoryOperation.READ,
            )
            for row in rows[:limit]
        ]
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
        scope = MemoryScope(scope)
        memory_type = MemoryKind(memory_type)
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
        if not key or len(key) > 120 or not _IDENTIFIER.fullmatch(key):
            raise ValueError("memory key must be a short identifier")
        if not value or len(value) > 2000:
            raise ValueError("memory value must be between 1 and 2000 characters")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        body: dict[str, object] = {
            "entity_path": self._entity_path(scope, customer_id, capability_id),
            "key": key,
            "value": value,
            "confidence": confidence,
            "memory_type": memory_type.value,
            "shared": scope is MemoryScope.SHARED_SUPPORT,
            "branch": "main",
            "agent_id": self.agent_id,
            "session_id": execution_id,
        }
        payload = self._request("POST", "/api/v1/entries", json_body=body)
        self._raise_if_error(payload, "write")
        rows = self._entry_rows(payload)
        if not rows:
            raise MemoryResponseError("SenseLab write returned no entry")
        expected_path = self._entity_path(scope, customer_id, capability_id)
        if rows[0].get("entity_path") != expected_path or rows[0].get("key") != key:
            raise MemoryResponseError("SenseLab write returned the wrong entry")
        entry = self._entry_from_response(
            rows[0],
            scope=scope,
            customer_id=customer_id,
            capability_id=capability_id,
            execution_id=execution_id,
            conversation_id=conversation_id,
            operation=MemoryOperation.WRITE,
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
        """Record typed context locally and through SenseLab's REST API."""

        context = MemoryContext(
            context_id=f"senselab_context_{uuid4().hex}",
            execution_id=execution_id,
            label=label,
            summary=summary,
            source=source,
        )
        body: dict[str, object] = {
            "label": label,
            "summary": summary,
            "source": source,
            "agent_id": self.agent_id,
        }
        payload = self._request("POST", "/api/v1/context", json_body=body)
        self._raise_if_error(payload, "context")
        if not isinstance(payload, dict):
            raise MemoryResponseError("SenseLab context response is not an object")
        external_id = self._context_id(payload)
        if external_id != context.context_id:
            context = context.model_copy(update={"context_id": external_id})
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
        with self._lock:
            causal_keys = list(dict.fromkeys(self._read_keys.get(execution_id, [])))
        body: dict[str, object] = {
            "outcome_ref": outcome_id,
            "outcome_type": outcome_type,
            "causal_entry_keys": causal_keys or None,
            "agent_id": self.agent_id,
        }
        if decision_summary:
            body["decision_summary"] = decision_summary
        payload = self._request("POST", "/api/v1/outcomes", json_body=body)
        self._raise_if_error(payload, "outcome")
        rows = self._entry_rows(payload)
        entry_ids = tuple(
            self._entry_id(row, entity_path="", key="", version=1) for row in rows
        )
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
        params: dict[str, str] | None = None
        if outcome_id:
            params = {"outcome_ref": outcome_id}
        payload = self._request("GET", "/api/v1/explain", params=params)
        if not isinstance(payload, dict):
            raise MemoryResponseError("SenseLab explanation is not an object")
        if payload.get("error"):
            raise MemoryResponseError("SenseLab explanation returned an error")

        remote_entries = self._explanation_entries(payload, execution_id)
        remote_contexts = self._explanation_contexts(payload, execution_id)
        with self._lock:
            local_entries = tuple(deepcopy(self._read_entries.get(execution_id, [])))
            local_contexts = tuple(deepcopy(self._contexts.get(execution_id, [])))
            committed = outcome_id is not None and outcome_id in self._outcomes
        entries = self._merge_provenance(local_entries, remote_entries)
        contexts = self._merge_contexts(local_contexts, remote_contexts)
        committed = committed or bool(outcome_id and payload.get("outcome_ref") == outcome_id)
        return MemoryExplanation(
            provider=self.provider,
            execution_id=execution_id,
            outcome_id=outcome_id,
            entries=entries,
            contexts=contexts,
            outcome_committed=committed,
        )

    @staticmethod
    def _context_id(payload: object) -> str:
        if isinstance(payload, dict):
            for name in ("context_id", "id"):
                value = payload.get(name)
                if isinstance(value, str) and value:
                    return value
        return f"senselab_context_{uuid4().hex}"

    @staticmethod
    def _raise_if_error(payload: object, operation: str) -> None:
        if isinstance(payload, dict) and payload.get("error"):
            raise MemoryResponseError(f"SenseLab rejected {operation} request")

    def _explanation_entries(
        self,
        payload: dict[str, object],
        execution_id: str,
    ) -> tuple[MemoryProvenance, ...]:
        raw_entries = payload.get("causal_entries", [])
        if raw_entries is None:
            raw_entries = []
        if not isinstance(raw_entries, list):
            raise MemoryResponseError("SenseLab explanation entries are invalid")
        entries: list[MemoryProvenance] = []
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict):
                raise MemoryResponseError("SenseLab explanation entry is invalid")
            entity_path = self._required_text(raw_entry, "entity_path")
            key = self._required_text(raw_entry, "key")
            version = self._positive_int(raw_entry.get("version", 1), "version")
            entry_id = self._entry_id(
                raw_entry,
                entity_path=entity_path,
                key=key,
                version=version,
            )
            scope = self._scope_from_path(entity_path)
            occurred_at = self._timestamp(raw_entry)
            entries.append(
                MemoryProvenance(
                    provider=self.provider,
                    entry_id=entry_id,
                    key=key,
                    version=version,
                    scope=scope,
                    operation=MemoryOperation.READ,
                    execution_id=execution_id,
                    conversation_id=None,
                    occurred_at=occurred_at,
                )
            )
        return tuple(entries)

    def _explanation_contexts(
        self,
        payload: dict[str, object],
        execution_id: str,
    ) -> tuple[MemoryContext, ...]:
        raw_contexts = payload.get("external_contexts", [])
        if raw_contexts is None:
            raw_contexts = []
        if not isinstance(raw_contexts, list):
            raise MemoryResponseError("SenseLab explanation contexts are invalid")
        contexts: list[MemoryContext] = []
        for index, raw_context in enumerate(raw_contexts, start=1):
            if not isinstance(raw_context, dict):
                raise MemoryResponseError("SenseLab explanation context is invalid")
            label = self._required_text(raw_context, "label")
            summary = self._required_text(raw_context, "summary")
            source = raw_context.get("source")
            if source is not None and not isinstance(source, str):
                raise MemoryResponseError("SenseLab context source is invalid")
            contexts.append(
                MemoryContext(
                    context_id=str(raw_context.get("context_id") or f"remote_context_{index}"),
                    execution_id=execution_id,
                    label=label,
                    summary=summary,
                    source=source,
                    occurred_at=self._timestamp(raw_context),
                )
            )
        return tuple(contexts)

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

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int | float] | None = None,
        json_body: dict[str, object] | None = None,
    ) -> object:
        try:
            response = self._client.request(
                method,
                path,
                params=params,
                json=json_body,
                timeout=self.timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise MemoryUnavailable("SenseLab memory request failed") from exc
        if response.is_error:
            detail = response.text[:200]
            raise MemoryUnavailable(
                f"SenseLab memory request returned HTTP {response.status_code}: {detail}"
            )
        try:
            return response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise MemoryResponseError("SenseLab returned invalid JSON") from exc

    @staticmethod
    def _entry_rows(payload: object) -> list[dict[str, object]]:
        if isinstance(payload, list):
            values = payload
        elif isinstance(payload, dict):
            container = cast(dict[str, object], payload)
            if all(key in container for key in ("entity_path", "key")):
                values = [container]
            else:
                values = []
                for name in ("entries", "results", "data", "entry"):
                    candidate = container.get(name)
                    if isinstance(candidate, list):
                        values = candidate
                        break
                    if isinstance(candidate, dict):
                        values = [candidate]
                        break
        else:
            raise MemoryResponseError("SenseLab response is not a JSON object or list")
        rows = [cast(dict[str, object], value) for value in values if isinstance(value, dict)]
        if len(rows) != len(values):
            raise MemoryResponseError("SenseLab response contains an invalid entry")
        return rows

    def _entry_from_response(
        self,
        row: dict[str, object],
        *,
        scope: MemoryScope,
        customer_id: str | None,
        capability_id: str | None,
        execution_id: str,
        conversation_id: str | None,
        operation: MemoryOperation,
    ) -> MemoryEntry:
        entity_path = self._required_text(row, "entity_path")
        key = self._required_text(row, "key")
        version = self._positive_int(row.get("version", 1), "version")
        confidence = self._number(row.get("confidence", 1.0), "confidence")
        if not 0.0 <= confidence <= 1.0:
            raise MemoryResponseError("SenseLab confidence is outside 0..1")
        raw_kind = str(row.get("memory_type", MemoryKind.FACT.value)).lower()
        try:
            memory_type = MemoryKind(raw_kind)
        except ValueError as exc:
            raise MemoryResponseError("SenseLab memory type is not supported") from exc
        if self._contains_current_business_key(key):
            raise MemoryResponseError("SenseLab returned current business state")
        if (
            scope is MemoryScope.SHARED_SUPPORT
            and memory_type is MemoryKind.FACT
            and self._contains_business_term(key)
        ):
            raise MemoryResponseError("SenseLab returned a shared business fact")
        entry_id = self._entry_id(
            row,
            entity_path=entity_path,
            key=key,
            version=version,
        )
        occurred_at = self._timestamp(row)
        return MemoryEntry(
            memory_id=entry_id,
            entity_path=entity_path,
            key=key,
            value=self._string_value(row.get("value")),
            memory_type=memory_type,
            confidence=confidence,
            version=version,
            scope=scope,
            customer_id=customer_id,
            conversation_id=conversation_id,
            capability_id=capability_id,
            provenance=MemoryProvenance(
                provider=self.provider,
                entry_id=entry_id,
                key=key,
                version=version,
                scope=scope,
                operation=operation,
                execution_id=execution_id,
                conversation_id=conversation_id,
                occurred_at=occurred_at,
            ),
        )

    @staticmethod
    def _scope_from_path(entity_path: str) -> MemoryScope:
        if entity_path.startswith("customers/"):
            customer_id = entity_path.removeprefix("customers/")
            if customer_id and _IDENTIFIER.fullmatch(customer_id):
                return MemoryScope.CUSTOMER
        return MemoryScope.SHARED_SUPPORT

    @staticmethod
    def _timestamp(row: dict[str, object]) -> datetime:
        provenance = row.get("provenance")
        if isinstance(provenance, dict):
            value = provenance.get("written_at") or provenance.get("read_at")
            if isinstance(value, str):
                try:
                    timestamp = datetime.fromisoformat(value)
                    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                        return timestamp.replace(tzinfo=UTC)
                    return timestamp
                except ValueError:
                    pass
        value = row.get("occurred_at")
        if isinstance(value, str):
            try:
                timestamp = datetime.fromisoformat(value)
                if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                    return timestamp.replace(tzinfo=UTC)
                return timestamp
            except ValueError:
                pass
        return now()

    def _remember_read(self, execution_id: str, entry: MemoryEntry) -> None:
        with self._lock:
            self._read_entries[execution_id].append(entry.provenance)
            key = f"{entry.entity_path}/{entry.key}"
            self._read_keys[execution_id].append(key)

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
    def _entry_id(
        row: dict[str, object],
        *,
        entity_path: str,
        key: str,
        version: int,
    ) -> str:
        candidate = row.get("memory_id") or row.get("id")
        if isinstance(candidate, str) and candidate:
            return candidate
        return f"senselab:{entity_path}/{key}:v{version}"

    @staticmethod
    def _required_text(row: dict[str, object], key: str) -> str:
        value = row.get(key)
        if not isinstance(value, str) or not value:
            raise MemoryResponseError(f"SenseLab entry is missing {key}")
        return value

    @staticmethod
    def _positive_int(value: object, key: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise MemoryResponseError(f"SenseLab {key} must be a positive integer")
        return value

    @staticmethod
    def _number(value: object, key: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MemoryResponseError(f"SenseLab {key} must be numeric")
        return float(value)

    @staticmethod
    def _string_value(value: object) -> str:
        if isinstance(value, str):
            if not value:
                raise MemoryResponseError("SenseLab entry value is empty")
            return value[:2000]
        try:
            encoded = json.dumps(value, sort_keys=True, default=str)
        except (TypeError, ValueError) as exc:
            raise MemoryResponseError("SenseLab entry value is not serializable") from exc
        if not encoded:
            raise MemoryResponseError("SenseLab entry value is empty")
        return encoded[:2000]

    @staticmethod
    def _validate_scope(
        scope: MemoryScope,
        customer_id: str | None,
        capability_id: str | None,
    ) -> None:
        if scope is MemoryScope.CUSTOMER and (
            not customer_id
            or capability_id is not None
            or not _IDENTIFIER.fullmatch(customer_id or "")
        ):
            raise ValueError("customer memory requires only a customer ID")
        if scope is MemoryScope.SHARED_SUPPORT and (
            not capability_id
            or customer_id is not None
            or not _IDENTIFIER.fullmatch(capability_id or "")
        ):
            raise ValueError("shared memory requires only a capability ID")

    @staticmethod
    def _contains_current_business_key(key: str) -> bool:
        normalized = key.lower().replace("-", "_")
        return normalized in _CURRENT_BUSINESS_KEYS

    @staticmethod
    def _contains_business_term(key: str) -> bool:
        parts = set(re.split(r"[_:.\-]+", key.lower()))
        return bool(parts & _SHARED_BUSINESS_TERMS)

    @staticmethod
    def _entity_path(
        scope: MemoryScope,
        customer_id: str | None,
        capability_id: str | None,
    ) -> str:
        if scope is MemoryScope.CUSTOMER:
            assert customer_id is not None
            return f"customers/{customer_id}"
        assert capability_id is not None
        return f"support/{capability_id}"


__all__ = ["SenseLabMemory"]
