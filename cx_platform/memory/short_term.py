"""Bounded conversation continuity on the harness memory boundary."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from threading import RLock
from typing import Literal
from uuid import uuid4

from enterprise_agent_harness import (
    BoundedMemory,
    MemoryItem,
    PrincipalContext,
)
from enterprise_agent_harness import (
    MemoryScope as HarnessMemoryScope,
)
from pydantic import BaseModel, ConfigDict, Field

from cx_platform.domain.models import now


class ConversationMemoryKind(StrEnum):
    ORDER_REFERENCE = "order_reference"
    LINE_REFERENCE = "line_reference"
    CUSTOMER_PREFERENCE = "customer_preference"
    CONSTRAINT = "constraint"
    RESOLVED_REFERENCE = "resolved_reference"
    SUMMARY = "summary"


class ShortTermMemoryRecord(BaseModel):
    """One compact, case-bound conversation memory item."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    key: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=500)
    kind: ConversationMemoryKind
    origin: str = Field(min_length=1)
    advisory: Literal[True] = True
    created_at: datetime = Field(default_factory=now)


class ConversationMemoryStrategy:
    """Harness MemoryStrategy view for one trusted conversation."""

    def __init__(
        self,
        owner: ConversationMemory,
        principal: PrincipalContext,
        customer_id: str,
        conversation_id: str,
    ) -> None:
        self.owner = owner
        self.principal = principal
        self.customer_id = customer_id
        self.conversation_id = conversation_id

    def select(self, principal: PrincipalContext) -> list[MemoryItem]:
        if principal != self.principal:
            return []
        return self.owner._select_harness(
            principal,
            customer_id=self.customer_id,
            conversation_id=self.conversation_id,
            session_id=self.principal.session_id,
        )

    def remember(self, item: MemoryItem) -> None:
        if (
            item.principal_id != self.principal.principal_id
            or item.tenant_id != self.principal.tenant_id
        ):
            raise ValueError("conversation memory principal does not match")
        self.owner._remember_harness(
            item,
            customer_id=self.customer_id,
            conversation_id=self.conversation_id,
            session_id=self.principal.session_id,
        )


class ConversationMemory:
    """Provide bounded continuity without storing current business truth."""

    def __init__(self, *, max_items: int = 8) -> None:
        if max_items < 1:
            raise ValueError("max_items must be positive")
        self.max_items = max_items
        self._stores: dict[str, BoundedMemory] = {}
        self._lock = RLock()

    def remember(
        self,
        principal: PrincipalContext,
        *,
        customer_id: str,
        conversation_id: str,
        key: str,
        value: str,
        kind: ConversationMemoryKind,
        origin: str = "customer_conversation",
    ) -> ShortTermMemoryRecord:
        kind = ConversationMemoryKind(kind)
        if not key or len(key) > 120:
            raise ValueError("conversation memory key must be between 1 and 120 characters")
        if not value or len(value) > 500:
            raise ValueError("conversation memory value must be between 1 and 500 characters")
        if self._contains_business_state_key(key):
            raise ValueError("conversation memory cannot store current business state")
        item = MemoryItem(
            memory_id=f"conversation_memory_{uuid4().hex}",
            principal_id=principal.principal_id,
            tenant_id=principal.tenant_id,
            scope=HarnessMemoryScope.EXECUTION,
            source_scope_id=self._scope_id(
                customer_id,
                conversation_id,
                principal.session_id,
            ),
            key=f"{kind.value}:{key}",
            value=value,
            origin=origin,
        )
        self._remember_harness(
            item,
            customer_id=customer_id,
            conversation_id=conversation_id,
            session_id=principal.session_id,
        )
        return self._record_from_item(
            item,
            customer_id=customer_id,
            conversation_id=conversation_id,
            session_id=principal.session_id,
            kind=kind,
            key=key,
        )

    def select(
        self,
        principal: PrincipalContext,
        *,
        customer_id: str,
        conversation_id: str,
    ) -> list[ShortTermMemoryRecord]:
        items = self._select_harness(
            principal,
            customer_id=customer_id,
            conversation_id=conversation_id,
            session_id=principal.session_id,
        )
        records: list[ShortTermMemoryRecord] = []
        for item in items:
            kind, key = self._split_key(item.key)
            records.append(
                self._record_from_item(
                    item,
                    customer_id=customer_id,
                    conversation_id=conversation_id,
                    session_id=principal.session_id,
                    kind=kind,
                    key=key,
                )
            )
        return records

    def strategy(
        self,
        principal: PrincipalContext,
        *,
        customer_id: str,
        conversation_id: str,
    ) -> ConversationMemoryStrategy:
        return ConversationMemoryStrategy(
            self,
            principal,
            customer_id,
            conversation_id,
        )

    def clear(
        self,
        *,
        customer_id: str,
        conversation_id: str,
        session_id: str | None = None,
    ) -> None:
        with self._lock:
            if session_id is not None:
                self._stores.pop(
                    self._scope_id(customer_id, conversation_id, session_id),
                    None,
                )
                return
            prefix = f"conversation:{customer_id}:{conversation_id}:"
            for scope_id in tuple(self._stores):
                if scope_id.startswith(prefix):
                    del self._stores[scope_id]

    def clear_after_resolution(
        self,
        *,
        customer_id: str,
        conversation_id: str,
        session_id: str | None = None,
    ) -> None:
        """Drop case continuity when the caller reaches its terminal boundary."""

        self.clear(
            customer_id=customer_id,
            conversation_id=conversation_id,
            session_id=session_id,
        )

    def _remember_harness(
        self,
        item: MemoryItem,
        *,
        customer_id: str,
        conversation_id: str,
        session_id: str,
    ) -> None:
        expected_scope = self._scope_id(customer_id, conversation_id, session_id)
        if len(item.value) > 500 or len(item.key) > 120:
            raise ValueError("conversation memory must stay compact")
        _, raw_key = self._split_key(item.key)
        if self._contains_business_state_key(raw_key):
            raise ValueError("conversation memory cannot store current business state")
        if item.source_scope_id != expected_scope:
            item = item.model_copy(
                update={
                    "source_scope_id": expected_scope,
                    "scope": HarnessMemoryScope.EXECUTION,
                }
            )
        with self._lock:
            store = self._stores.setdefault(
                expected_scope,
                BoundedMemory(max_items=self.max_items),
            )
        store.remember(item)

    def _select_harness(
        self,
        principal: PrincipalContext,
        *,
        customer_id: str,
        conversation_id: str,
        session_id: str,
    ) -> list[MemoryItem]:
        scope_id = self._scope_id(customer_id, conversation_id, session_id)
        with self._lock:
            store = self._stores.get(scope_id)
        if store is None:
            return []
        scoped_principal = PrincipalContext(
            principal_id=principal.principal_id,
            tenant_id=principal.tenant_id,
            session_id=scope_id,
        )
        return store.select(scoped_principal)

    @staticmethod
    def _scope_id(customer_id: str, conversation_id: str, session_id: str) -> str:
        if not customer_id or not conversation_id or not session_id:
            raise ValueError("customer, conversation, and session IDs are required")
        return f"conversation:{customer_id}:{conversation_id}:{session_id}"

    @staticmethod
    def _split_key(value: str) -> tuple[ConversationMemoryKind, str]:
        prefix, separator, key = value.partition(":")
        if not separator:
            return ConversationMemoryKind.SUMMARY, value
        try:
            kind = ConversationMemoryKind(prefix)
        except ValueError:
            kind = ConversationMemoryKind.SUMMARY
            key = value
        return kind, key

    @staticmethod
    def _record_from_item(
        item: MemoryItem,
        *,
        customer_id: str,
        conversation_id: str,
        session_id: str,
        kind: ConversationMemoryKind,
        key: str,
    ) -> ShortTermMemoryRecord:
        return ShortTermMemoryRecord(
            memory_id=item.memory_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            session_id=session_id,
            key=key,
            value=item.value,
            kind=kind,
            origin=item.origin,
            advisory=True,
            created_at=item.created_at,
        )

    @staticmethod
    def _contains_business_state_key(key: str) -> bool:
        normalized = key.lower().replace("-", "_")
        forbidden = (
            "order_status",
            "shipment_status",
            "payment_status",
            "refund_is_allowed",
            "return_is_allowed",
            "cancel_is_allowed",
        )
        return any(term in normalized for term in forbidden)


__all__ = [
    "ConversationMemory",
    "ConversationMemoryItem",
    "ConversationMemoryKind",
    "ConversationMemoryStrategy",
    "ShortTermMemoryRecord",
]


ConversationMemoryItem = ShortTermMemoryRecord
