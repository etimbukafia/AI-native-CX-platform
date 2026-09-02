"""Mappings between documented SenseLab payloads and CX models."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import cast

from cx_platform.domain.models import MemoryOperation, now

from ..models import (
    MemoryContext,
    MemoryEntry,
    MemoryKind,
    MemoryProvenance,
    MemoryScope,
)
from ..port import MemoryResponseError

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


def build_search_request(
    *,
    scope: MemoryScope,
    customer_id: str | None,
    capability_id: str | None,
    query: str | None,
    min_confidence: float,
    limit: int,
) -> dict[str, object]:
    """Build the documented SenseLab search request."""

    path = entity_path(scope, customer_id, capability_id)
    if limit < 1 or limit > 20:
        raise ValueError("limit must be between 1 and 20")
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError("min_confidence must be between 0 and 1")
    body: dict[str, object] = {
        "entity_path": path,
        "min_confidence": min_confidence,
        "sort_by": "confidence",
        "limit": limit,
        "branch": "main",
    }
    if query:
        body["query"] = query
    return body


def build_write_request(
    *,
    scope: MemoryScope,
    customer_id: str | None,
    capability_id: str | None,
    key: str,
    value: str,
    memory_type: MemoryKind,
    confidence: float,
    confirmed: bool,
    agent_id: str,
    session_id: str,
) -> dict[str, object]:
    """Build the documented SenseLab entry-write request."""

    path = entity_path(scope, customer_id, capability_id)
    validate_memory_write(
        scope=scope,
        key=key,
        value=value,
        memory_type=memory_type,
        confidence=confidence,
        confirmed=confirmed,
    )
    return {
        "entity_path": path,
        "key": key,
        "value": value,
        "confidence": confidence,
        "memory_type": memory_type.value,
        "shared": scope is MemoryScope.SHARED_SUPPORT,
        "branch": "main",
        "agent_id": agent_id,
        "session_id": session_id,
    }


def build_context_request(
    *,
    label: str,
    summary: str,
    source: str | None,
    agent_id: str,
) -> dict[str, object]:
    """Build the documented SenseLab context request."""

    return {
        "label": label,
        "summary": summary,
        "source": source,
        "agent_id": agent_id,
    }


def build_outcome_request(
    *,
    outcome_id: str,
    outcome_type: str,
    causal_entry_keys: list[str] | None,
    agent_id: str,
    decision_summary: str | None,
) -> dict[str, object]:
    """Build the documented SenseLab outcome request."""

    body: dict[str, object] = {
        "outcome_ref": outcome_id,
        "outcome_type": outcome_type,
        "causal_entry_keys": causal_entry_keys,
        "agent_id": agent_id,
    }
    if decision_summary:
        body["decision_summary"] = decision_summary
    return body


def build_explain_params(outcome_id: str | None) -> dict[str, str] | None:
    """Build the documented explain query parameters."""

    if outcome_id:
        return {"outcome_ref": outcome_id}
    return None


def validate_memory_write(
    *,
    scope: MemoryScope,
    key: str,
    value: str,
    memory_type: MemoryKind,
    confidence: float,
    confirmed: bool,
) -> None:
    """Enforce CX memory safety rules before sending a write."""

    if scope is MemoryScope.CUSTOMER and not confirmed:
        raise ValueError("customer memory requires explicit confirmation")
    if _contains_current_business_key(key):
        raise ValueError("memory cannot store current business state")
    if (
        scope is MemoryScope.SHARED_SUPPORT
        and memory_type is MemoryKind.FACT
        and _contains_business_term(key)
    ):
        raise ValueError("shared memory cannot store current business state")
    if not key or len(key) > 120 or not _IDENTIFIER.fullmatch(key):
        raise ValueError("memory key must be a short identifier")
    if not value or len(value) > 2000:
        raise ValueError("memory value must be between 1 and 2000 characters")
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1")


def entity_path(
    scope: MemoryScope,
    customer_id: str | None,
    capability_id: str | None,
) -> str:
    """Return the CX namespace used by one memory scope."""

    validate_scope(scope, customer_id, capability_id)
    if scope is MemoryScope.CUSTOMER:
        assert customer_id is not None
        return f"customers/{customer_id}"
    assert capability_id is not None
    return f"support/{capability_id}"


def validate_scope(
    scope: MemoryScope,
    customer_id: str | None,
    capability_id: str | None,
) -> None:
    """Require exactly one trusted identifier for a scoped namespace."""

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


def map_search_response(
    payload: object,
    *,
    scope: MemoryScope,
    customer_id: str | None,
    capability_id: str | None,
    execution_id: str,
) -> list[MemoryEntry]:
    """Map the documented search response, which is a list of entries."""

    rows = _required_entry_list(payload, "search")
    expected_path = entity_path(scope, customer_id, capability_id)
    entries: list[MemoryEntry] = []
    for row in rows:
        if row.get("entity_path") != expected_path:
            raise MemoryResponseError("SenseLab returned an entry outside the requested scope")
        entries.append(
            map_entry(
                row,
                scope=scope,
                customer_id=customer_id,
                capability_id=capability_id,
                execution_id=execution_id,
                conversation_id=None,
                operation=MemoryOperation.READ,
            )
        )
    return entries


def map_write_response(
    payload: object,
    *,
    scope: MemoryScope,
    customer_id: str | None,
    capability_id: str | None,
    key: str,
    execution_id: str,
    conversation_id: str | None,
) -> MemoryEntry:
    """Map the documented entry object returned by a write."""

    row = _required_entry_object(payload, "write")
    expected_path = entity_path(scope, customer_id, capability_id)
    if row.get("entity_path") != expected_path or row.get("key") != key:
        raise MemoryResponseError("SenseLab write returned the wrong entry")
    return map_entry(
        row,
        scope=scope,
        customer_id=customer_id,
        capability_id=capability_id,
        execution_id=execution_id,
        conversation_id=conversation_id,
        operation=MemoryOperation.WRITE,
    )


def validate_context_response(
    payload: object,
    *,
    label: str,
) -> None:
    """Validate the documented context acknowledgement."""

    response = _required_object(payload, "context")
    recorded = _required_text(response, "recorded", "context")
    if recorded != label:
        raise MemoryResponseError("SenseLab context response names the wrong label")
    source = response.get("source")
    if source is not None and not isinstance(source, str):
        raise MemoryResponseError("SenseLab context source is invalid")


def map_outcome_response(payload: object) -> tuple[str, ...]:
    """Map entry identifiers from the documented outcome response."""

    response = _required_object(payload, "outcome")
    raw_entries = response.get("entries")
    if not isinstance(raw_entries, list):
        raise MemoryResponseError("SenseLab outcome entries are invalid")
    entry_ids: list[str] = []
    for raw_entry in raw_entries:
        row = _required_object(raw_entry, "outcome entry")
        entity = _required_text(row, "entity_path", "outcome entry")
        key = _required_text(row, "key", "outcome entry")
        version = _positive_int(row.get("version"), "outcome entry version")
        entry_ids.append(_entry_id(entity, key, version))
    return tuple(entry_ids)


def map_explanation_response(
    payload: object,
    *,
    execution_id: str,
) -> tuple[str | None, tuple[MemoryProvenance, ...], tuple[MemoryContext, ...]]:
    """Map the documented causal explanation response."""

    response = _required_object(payload, "explanation")
    raw_outcome_id = response.get("outcome_ref")
    if raw_outcome_id is not None and not isinstance(raw_outcome_id, str):
        raise MemoryResponseError("SenseLab explanation outcome reference is invalid")

    raw_entries = response.get("causal_entries")
    if not isinstance(raw_entries, list):
        raise MemoryResponseError("SenseLab explanation entries are invalid")
    entries: list[MemoryProvenance] = []
    for raw_entry in raw_entries:
        row = _required_object(raw_entry, "explanation entry")
        entity = _required_text(row, "entity_path", "explanation entry")
        key = _required_text(row, "key", "explanation entry")
        version = _positive_int(row.get("version"), "explanation entry version")
        scope = _scope_from_path(entity)
        entries.append(
            MemoryProvenance(
                provider="senselab",
                entry_id=_entry_id(entity, key, version),
                key=key,
                version=version,
                scope=scope,
                operation=MemoryOperation.READ,
                execution_id=execution_id,
                occurred_at=_entry_timestamp(row),
            )
        )

    raw_contexts = response.get("external_contexts")
    if not isinstance(raw_contexts, list):
        raise MemoryResponseError("SenseLab explanation contexts are invalid")
    contexts: list[MemoryContext] = []
    for index, raw_context in enumerate(raw_contexts, start=1):
        row = _required_object(raw_context, "explanation context")
        label = _required_text(row, "label", "explanation context")
        summary = _required_text(row, "summary", "explanation context")
        source = row.get("source")
        if source is not None and not isinstance(source, str):
            raise MemoryResponseError("SenseLab context source is invalid")
        contexts.append(
            MemoryContext(
                context_id=f"remote_context_{index}",
                execution_id=execution_id,
                label=label,
                summary=summary,
                source=source,
                occurred_at=now(),
            )
        )
    return raw_outcome_id, tuple(entries), tuple(contexts)


def map_entry(
    row: dict[str, object],
    *,
    scope: MemoryScope,
    customer_id: str | None,
    capability_id: str | None,
    execution_id: str,
    conversation_id: str | None,
    operation: MemoryOperation,
) -> MemoryEntry:
    """Convert one documented SenseLab entry into a CX memory entry."""

    entity = _required_text(row, "entity_path", "entry")
    key = _required_text(row, "key", "entry")
    value = row.get("value")
    version = _positive_int(row.get("version"), "entry version")
    confidence = _number(row.get("confidence"), "entry confidence")
    if not 0.0 <= confidence <= 1.0:
        raise MemoryResponseError("SenseLab confidence is outside 0..1")
    raw_kind = _required_text(row, "memory_type", "entry").lower()
    try:
        memory_type = MemoryKind(raw_kind)
    except ValueError as exc:
        raise MemoryResponseError("SenseLab memory type is not supported") from exc
    if _contains_current_business_key(key):
        raise MemoryResponseError("SenseLab returned current business state")
    if (
        scope is MemoryScope.SHARED_SUPPORT
        and memory_type is MemoryKind.FACT
        and _contains_business_term(key)
    ):
        raise MemoryResponseError("SenseLab returned a shared business fact")
    entry_id = _entry_id(entity, key, version)
    occurred_at = _entry_timestamp(row)
    return MemoryEntry(
        memory_id=entry_id,
        entity_path=entity,
        key=key,
        value=_string_value(value),
        memory_type=memory_type,
        confidence=confidence,
        version=version,
        scope=scope,
        customer_id=customer_id,
        conversation_id=conversation_id,
        capability_id=capability_id,
        provenance=MemoryProvenance(
            provider="senselab",
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


def _required_entry_list(payload: object, operation: str) -> list[dict[str, object]]:
    if not isinstance(payload, list):
        raise MemoryResponseError(f"SenseLab {operation} response must be a list")
    return [_required_object(item, f"{operation} entry") for item in payload]


def _required_entry_object(payload: object, operation: str) -> dict[str, object]:
    response = _required_object(payload, f"{operation} response")
    if "entity_path" not in response or "key" not in response:
        raise MemoryResponseError(f"SenseLab {operation} response is missing entry fields")
    return response


def _required_object(payload: object, name: str) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise MemoryResponseError(f"SenseLab {name} must be an object")
    return cast(dict[str, object], payload)


def _required_text(row: dict[str, object], key: str, name: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise MemoryResponseError(f"SenseLab {name} is missing {key}")
    return value


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MemoryResponseError(f"SenseLab {name} must be a positive integer")
    return value


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MemoryResponseError(f"SenseLab {name} must be numeric")
    return float(value)


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


def _entry_id(entity_path: str, key: str, version: int) -> str:
    return f"senselab:{entity_path}/{key}:v{version}"


def _entry_timestamp(row: dict[str, object]) -> datetime:
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
    return now()


def _scope_from_path(entity_path: str) -> MemoryScope:
    if entity_path.startswith("customers/"):
        customer_id = entity_path.removeprefix("customers/")
        if customer_id and _IDENTIFIER.fullmatch(customer_id):
            return MemoryScope.CUSTOMER
    return MemoryScope.SHARED_SUPPORT


def _contains_current_business_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return normalized in _CURRENT_BUSINESS_KEYS


def _contains_business_term(key: str) -> bool:
    parts = set(re.split(r"[_:.\-]+", key.lower()))
    return bool(parts & _SHARED_BUSINESS_TERMS)


__all__ = [
    "build_context_request",
    "build_explain_params",
    "build_outcome_request",
    "build_search_request",
    "build_write_request",
    "entity_path",
    "map_explanation_response",
    "map_outcome_response",
    "map_search_response",
    "map_write_response",
    "validate_context_response",
]
