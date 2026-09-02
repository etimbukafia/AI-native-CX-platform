"""Small composition helper for optional SenseLab memory."""

from __future__ import annotations

from .local import LocalMemory
from .port import (
    MemoryConfigurationError,
    MemoryEvidenceSink,
    MemoryPort,
    ResilientMemory,
)
from .senselab import SenseLabMemory


def build_memory(
    *,
    evidence_sink: MemoryEvidenceSink | None = None,
    local: LocalMemory | None = None,
    timeout_seconds: float = 3.0,
) -> MemoryPort:
    """Use SenseLab when configured, with local support-safe fallback."""

    fallback = local or LocalMemory(evidence_sink=evidence_sink)
    try:
        primary = SenseLabMemory.from_environment(
            timeout_seconds=timeout_seconds,
            evidence_sink=evidence_sink,
        )
    except MemoryConfigurationError:
        return fallback
    return ResilientMemory(
        primary,
        fallback=fallback,
        evidence_sink=evidence_sink,
    )


__all__ = ["build_memory"]
