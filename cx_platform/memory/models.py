"""Typed models used by the CX memory boundary."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from cx_platform.domain.models import MemoryOperation, now


class MemoryScope(StrEnum):
    CUSTOMER = "customer"
    SHARED_SUPPORT = "shared_support"


class MemoryKind(StrEnum):
    EXPERIENCE = "experience"
    BELIEF = "belief"
    FACT = "fact"


class MemoryProvenance(BaseModel):
    """Reference to the external memory entry and the current operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1)
    entry_id: str = Field(min_length=1)
    key: str = Field(min_length=1)
    version: int = Field(ge=1)
    scope: MemoryScope
    operation: MemoryOperation
    execution_id: str = Field(min_length=1)
    conversation_id: str | None = Field(default=None, min_length=1)
    occurred_at: datetime = Field(default_factory=now)


class MemoryEntry(BaseModel):
    """Advisory memory. It cannot authorize a CX or business action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_id: str = Field(min_length=1)
    entity_path: str = Field(min_length=1)
    key: str = Field(min_length=1)
    value: str = Field(min_length=1, max_length=2000)
    memory_type: MemoryKind
    confidence: float = Field(ge=0.0, le=1.0)
    version: int = Field(ge=1)
    scope: MemoryScope
    customer_id: str | None = Field(default=None, min_length=1)
    conversation_id: str | None = Field(default=None, min_length=1)
    capability_id: str | None = Field(default=None, min_length=1)
    provenance: MemoryProvenance
    advisory: Literal[True] = True


class MemoryContext(BaseModel):
    """External context associated with one memory execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    context_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    label: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=1000)
    source: str | None = Field(default=None, max_length=200)
    occurred_at: datetime = Field(default_factory=now)


class MemoryOutcomeResult(BaseModel):
    """Result of sending a CX outcome signal to a memory provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1)
    outcome_id: str = Field(min_length=1)
    propagated: bool
    memory_entry_ids: tuple[str, ...] = ()
    failure_reason: str | None = None
    occurred_at: datetime = Field(default_factory=now)


class MemoryExplanation(BaseModel):
    """Safe explanation of memory references used by one execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    outcome_id: str | None = None
    entries: tuple[MemoryProvenance, ...] = ()
    contexts: tuple[MemoryContext, ...] = ()
    outcome_committed: bool = False


__all__ = [
    "MemoryContext",
    "MemoryEntry",
    "MemoryExplanation",
    "MemoryKind",
    "MemoryOutcomeResult",
    "MemoryProvenance",
    "MemoryScope",
]
