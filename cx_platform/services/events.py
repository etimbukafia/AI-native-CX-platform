"""CX-owned operational event append and polling boundaries."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from uuid import uuid4

from pydantic import JsonValue

from cx_platform.domain.models import ActorType, CXEvent, CXEventType, now
from cx_platform.persistence import CXRepositories


class CXEventService:
    """Append and read the CX operational event stream."""

    def __init__(
        self,
        repositories: CXRepositories,
        *,
        event_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.repositories = repositories
        self._event_id = event_id_factory or self._new_event_id

    def append(self, event: CXEvent) -> CXEvent:
        """Append one immutable CX event."""

        return self.repositories.append_event(event)

    def emit(
        self,
        event_type: CXEventType,
        *,
        customer_id: str | None = None,
        ticket_id: str | None = None,
        conversation_id: str | None = None,
        message_id: str | None = None,
        execution_id: str | None = None,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: str = "cx-platform",
        data: Mapping[str, JsonValue] | None = None,
        occurred_at: datetime | None = None,
    ) -> CXEvent:
        """Create and append one small operational fact."""

        return self.append(
            CXEvent(
                event_id=self._event_id(),
                event_type=event_type,
                occurred_at=occurred_at or now(),
                customer_id=customer_id,
                ticket_id=ticket_id,
                conversation_id=conversation_id,
                message_id=message_id,
                execution_id=execution_id,
                actor_type=actor_type,
                actor_id=actor_id,
                data=dict(data or {}),
            )
        )

    def poll(
        self,
        *,
        after: str | None = None,
        limit: int = 100,
    ) -> list[CXEvent]:
        """Return events after an event ID or numeric cursor."""

        if limit < 1:
            raise ValueError("event limit must be positive")
        return self.repositories.events(after=after, limit=limit)

    @staticmethod
    def _new_event_id() -> str:
        return f"cxevt_{uuid4().hex}"


__all__ = ["CXEventService"]
