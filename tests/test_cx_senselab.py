import json

import httpx
import pytest

from cx_platform.memory import (
    MemoryConfigurationError,
    MemoryKind,
    MemoryScope,
    SenseLabMemory,
)


def test_senselab_adapter_uses_typed_documented_http_operations() -> None:
    calls: list[tuple[str, str, dict[str, object]]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = request.content
        parsed = json.loads(body.decode("utf-8")) if body else {}
        calls.append((request.method, request.url.path, parsed))
        assert request.headers["X-AMFS-API-Key"] == "test-key"
        if request.url.path == "/api/v1/search":
            return httpx.Response(
                200,
                json=[
                    {
                        "entity_path": "support/delivery_resolution",
                        "key": "clear_next_check",
                        "value": "State the next check.",
                        "version": 2,
                        "confidence": 0.9,
                        "memory_type": "belief",
                    }
                ],
                request=request,
            )
        if request.url.path == "/api/v1/entries":
            return httpx.Response(
                200,
                json={
                    "entity_path": "customers/cx_cus_01",
                    "key": "resolution_preference",
                    "value": "refund",
                    "version": 1,
                    "confidence": 1.0,
                    "memory_type": "fact",
                },
                request=request,
            )
        if request.url.path == "/api/v1/outcomes":
            return httpx.Response(200, json={"entries": []}, request=request)
        if request.url.path == "/api/v1/context":
            return httpx.Response(
                200,
                json={"recorded": "business_tool", "source": "business-api"},
                request=request,
            )
        if request.url.path == "/api/v1/explain":
            return httpx.Response(
                200,
                json={
                    "outcome_ref": "outcome_01",
                    "causal_entries": [],
                    "external_contexts": [],
                },
                request=request,
            )
        raise AssertionError(request.url.path)

    client = httpx.Client(
        transport=httpx.MockTransport(handle),
        base_url="https://memory.test",
    )
    memory = SenseLabMemory(
        "https://memory.test",
        "test-key",
        client=client,
    )

    found = memory.search_relevant(
        execution_id="exec_01",
        scope=MemoryScope.SHARED_SUPPORT,
        skill_id="delivery_resolution",
        query="delivery",
    )
    written = memory.write_memory(
        execution_id="exec_01",
        scope=MemoryScope.CUSTOMER,
        customer_id="cx_cus_01",
        key="resolution_preference",
        value="refund",
        memory_type=MemoryKind.FACT,
        confirmed=True,
    )
    memory.record_context(
        execution_id="exec_01",
        label="business_tool",
        summary="Current shipment result was read from the business API.",
    )
    outcome = memory.commit_outcome(
        execution_id="exec_01",
        outcome_id="outcome_01",
        outcome_type="success",
    )

    assert found[0].version == 2
    assert found[0].provenance.operation == "read"
    assert written.customer_id == "cx_cus_01"
    assert outcome.propagated is True
    explanation = memory.explain_usage(
        execution_id="exec_01",
        outcome_id="outcome_01",
    )
    assert [path for _, path, _ in calls] == [
        "/api/v1/search",
        "/api/v1/entries",
        "/api/v1/context",
        "/api/v1/outcomes",
        "/api/v1/explain",
    ]
    assert explanation.contexts[0].label == "business_tool"


def test_senselab_environment_requires_an_api_key(monkeypatch) -> None:
    monkeypatch.delenv("AMFS_API_KEY", raising=False)

    with pytest.raises(MemoryConfigurationError, match="AMFS_API_KEY"):
        SenseLabMemory.from_environment()
