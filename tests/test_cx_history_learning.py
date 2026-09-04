import sqlite3

import pytest

from cx_platform.domain.models import (
    ActorType,
    CustomerBinding,
    EscalationReason,
    MemoryOperation,
    MemoryReference,
)
from cx_platform.memory import LocalMemory, MemoryKind, MemoryScope
from cx_platform.persistence import CXDatabase, CXRepositories
from cx_platform.services import (
    ConversationService,
    CXHistoryService,
    OutcomeLearningService,
)


def setup_repositories(tmp_path) -> CXRepositories:
    repositories = CXRepositories(CXDatabase(str(tmp_path / "cx.db")))
    repositories.save_binding(
        CustomerBinding(
            customer_id="cx_cus_01",
            external_customer_id="cus_001",
            display_name="Ada Okafor",
        )
    )
    repositories.save_binding(
        CustomerBinding(
            customer_id="cx_cus_02",
            external_customer_id="cus_002",
            display_name="Bola Adeyemi",
        )
    )
    return repositories


def test_customer_history_returns_cx_records_without_cross_customer_records(tmp_path) -> None:
    repositories = setup_repositories(tmp_path)
    service = ConversationService(repositories)
    first_conversation, first_ticket = service.start(
        customer_id="cx_cus_01",
        reason="Damaged item",
    )
    service.append_message(
        first_conversation.conversation_id,
        actor_type=ActorType.CUSTOMER,
        actor_id="cx_cus_01",
        content="The item is damaged.",
    )
    service.escalate(
        first_ticket.ticket_id,
        reason=EscalationReason.CUSTOMER_REQUESTED_HUMAN,
        summary="Customer requested a person",
    )
    service.resolve(
        first_ticket.ticket_id,
        resolution_code="REPLACEMENT",
        outcome_type="resolved_after_escalation",
    )
    csat = service.submit_csat(first_ticket.ticket_id, score=5)
    service.start(customer_id="cx_cus_02", reason="Delivery question")

    history = CXHistoryService(repositories).get_customer_history("cx_cus_01")

    assert history.customer_id == "cx_cus_01"
    assert [item.conversation_id for item in history.conversations] == [
        first_conversation.conversation_id
    ]
    assert len(history.tickets) == 1
    assert len(history.messages) == 1
    assert len(history.escalations) == 1
    assert len(history.outcomes) == 1
    assert len(history.csat) == 1

    result = OutcomeLearningService(repositories, LocalMemory()).commit_csat_signal(
        execution_id="exec_csat",
        csat_id=csat.csat_id,
    )
    assert result.propagated is True
    assert repositories.memory_references(csat_id=csat.csat_id)[0].outcome_id is None


def test_outcome_learning_links_after_cx_outcome_and_survives_memory_failure(tmp_path) -> None:
    repositories = setup_repositories(tmp_path)
    service = ConversationService(repositories)
    _, ticket = service.start(customer_id="cx_cus_01", reason="Delivery question")
    service.resolve(
        ticket.ticket_id,
        resolution_code="DELIVERY_UPDATE",
        outcome_type="delivery_update",
    )
    outcome = repositories.outcomes(ticket.ticket_id)[0]
    memory = LocalMemory(evidence_sink=repositories)
    memory.write_memory(
        execution_id="exec_01",
        scope=MemoryScope.SHARED_SUPPORT,
        key="delivery_language",
        value="Give one clear next check.",
        memory_type=MemoryKind.BELIEF,
        skill_id="delivery_resolution",
    )
    memory.search_relevant(
        execution_id="exec_01",
        scope=MemoryScope.SHARED_SUPPORT,
        skill_id="delivery_resolution",
    )
    learning = OutcomeLearningService(repositories, memory)

    result = learning.commit_outcome(
        execution_id="exec_01",
        outcome_id=outcome.outcome_id,
        outcome_type="success",
    )

    assert result.propagated is True
    assert repositories.outcome(outcome.outcome_id) == outcome
    references = repositories.memory_references(outcome_id=outcome.outcome_id)
    assert references[0].execution_id == "exec_01"
    assert references[0].customer_id == "cx_cus_01"
    assert references[0].conversation_id == ticket.conversation_id
    assert references[0].operation.value == "outcome"

    class FailingMemory:
        provider = "senselab"

        def commit_outcome(self, **kwargs):
            raise RuntimeError("memory unavailable")

    failed = OutcomeLearningService(repositories, FailingMemory()).commit_outcome(
        execution_id="exec_02",
        outcome_id=outcome.outcome_id,
        outcome_type="success",
    )

    assert failed.propagated is False
    assert repositories.outcome(outcome.outcome_id) == outcome


def test_policy_rejection_does_not_become_a_negative_learning_signal(tmp_path) -> None:
    repositories = setup_repositories(tmp_path)
    service = ConversationService(repositories)
    _, ticket = service.start(customer_id="cx_cus_01", reason="Refund request")
    service.resolve(
        ticket.ticket_id,
        resolution_code="POLICY_DENIED",
        outcome_type="policy_denied",
    )
    outcome = repositories.outcomes(ticket.ticket_id)[0]

    class RecordingMemory:
        provider = "senselab"

        def __init__(self) -> None:
            self.calls: list[str] = []

        def commit_outcome(self, **kwargs):
            self.calls.append(kwargs["outcome_type"])
            raise AssertionError("policy rejection must not be propagated")

    memory = RecordingMemory()
    result = OutcomeLearningService(repositories, memory).commit_outcome(
        execution_id="exec_policy",
        outcome_id=outcome.outcome_id,
        outcome_type="policy_rejected",
    )

    assert result.propagated is False
    assert memory.calls == []


def test_neutral_csat_is_not_sent_as_a_negative_learning_signal(tmp_path) -> None:
    repositories = setup_repositories(tmp_path)
    service = ConversationService(repositories)
    _, ticket = service.start(customer_id="cx_cus_01", reason="Question")
    service.resolve(
        ticket.ticket_id,
        resolution_code="ANSWERED",
        outcome_type="answered",
    )
    csat = service.submit_csat(ticket.ticket_id, score=3)

    class RecordingMemory:
        provider = "senselab"

        def commit_outcome(self, **kwargs):
            raise AssertionError("neutral feedback must not be propagated")

    result = OutcomeLearningService(repositories, RecordingMemory()).commit_csat_signal(
        execution_id="exec_neutral_csat",
        csat_id=csat.csat_id,
    )

    assert result.propagated is False


def test_in_memory_cx_database_keeps_schema_and_records_across_connections() -> None:
    repositories = CXRepositories(CXDatabase(":memory:"))
    repositories.save_binding(
        CustomerBinding(
            customer_id="cx_cus_01",
            external_customer_id="cus_001",
            display_name="Ada Okafor",
        )
    )

    conversation, ticket = ConversationService(repositories).start(
        customer_id="cx_cus_01",
        reason="Question",
    )

    assert repositories.ticket(ticket.ticket_id) == ticket
    assert repositories.conversation(conversation.conversation_id) == conversation


def test_memory_reference_cannot_point_to_missing_customer_or_outcome(tmp_path) -> None:
    repositories = CXRepositories(CXDatabase(str(tmp_path / "cx.db")))
    with pytest.raises(sqlite3.IntegrityError):
        repositories.save_memory_reference(
            MemoryReference(
                reference_id="memory_orphan",
                execution_id="exec_01",
                customer_id="cx_missing",
                memory_provider="local",
                memory_entry_id="entry_01",
                memory_key="preference",
                memory_scope="customer",
                operation=MemoryOperation.WRITE,
                outcome_id=None,
            )
        )
    repositories.save_binding(
        CustomerBinding(
            customer_id="cx_cus_01",
            external_customer_id="cus_001",
            display_name="Ada Okafor",
        )
    )
    with pytest.raises(sqlite3.IntegrityError):
        repositories.save_memory_reference(
            MemoryReference(
                reference_id="memory_orphan_outcome",
                execution_id="exec_01",
                customer_id="cx_cus_01",
                memory_provider="local",
                memory_entry_id="outcome:missing",
                memory_key="missing",
                memory_scope="outcome",
                operation=MemoryOperation.OUTCOME,
                outcome_id="outcome_missing",
            )
        )
