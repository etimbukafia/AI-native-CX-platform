from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime
from typing import Any, TypeVar

from pydantic import BaseModel

from cx_platform.domain.models import (
    CSAT,
    Conversation,
    CustomerBinding,
    CustomerHistory,
    Escalation,
    MemoryReference,
    Message,
    Outcome,
    Ticket,
)

T = TypeVar("T", bound=BaseModel)


class CXDatabase:
    schema_version = 3

    def __init__(self, path: str = "cx_platform.db") -> None:
        self.path = path
        self._memory_connection: sqlite3.Connection | None = None
        if path == ":memory:":
            self._memory_connection = sqlite3.connect(
                ":memory:",
                check_same_thread=False,
            )
        self._migrate()

    def connect(self) -> sqlite3.Connection:
        if self._memory_connection is not None:
            connection = self._memory_connection
        else:
            connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _migrate(self) -> None:
        with self.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS cx_schema_version (version INTEGER NOT NULL)"
            )
            row = connection.execute(
                "SELECT version FROM cx_schema_version LIMIT 1"
            ).fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO cx_schema_version VALUES (?)",
                    (self.schema_version,),
                )
            elif row["version"] != self.schema_version:
                raise RuntimeError(f"Unsupported CX schema version: {row['version']}")

            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS customer_bindings (
                    customer_id TEXT PRIMARY KEY,
                    external_customer_id TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tickets (
                    ticket_id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    conversation_id TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    resolution_code TEXT,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    UNIQUE (ticket_id, customer_id),
                    FOREIGN KEY (customer_id)
                        REFERENCES customer_bindings(customer_id)
                        ON DELETE RESTRICT
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    ticket_id TEXT UNIQUE NOT NULL,
                    customer_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    FOREIGN KEY (ticket_id, customer_id)
                        REFERENCES tickets(ticket_id, customer_id)
                        ON DELETE RESTRICT
                );
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    actor_type TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (conversation_id)
                        REFERENCES conversations(conversation_id)
                        ON DELETE RESTRICT
                );
                CREATE TABLE IF NOT EXISTS escalations (
                    escalation_id TEXT PRIMARY KEY,
                    ticket_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT,
                    FOREIGN KEY (ticket_id)
                        REFERENCES tickets(ticket_id)
                        ON DELETE RESTRICT
                );
                CREATE TABLE IF NOT EXISTS outcomes (
                    outcome_id TEXT PRIMARY KEY,
                    ticket_id TEXT NOT NULL,
                    outcome_type TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (ticket_id)
                        REFERENCES tickets(ticket_id)
                        ON DELETE RESTRICT
                );
                CREATE TABLE IF NOT EXISTS csat (
                    csat_id TEXT PRIMARY KEY,
                    ticket_id TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    comment TEXT,
                    submitted_at TEXT NOT NULL,
                    FOREIGN KEY (ticket_id)
                        REFERENCES tickets(ticket_id)
                        ON DELETE RESTRICT
                );
                CREATE TABLE IF NOT EXISTS memory_references (
                    reference_id TEXT PRIMARY KEY,
                    execution_id TEXT NOT NULL,
                    customer_id TEXT,
                    conversation_id TEXT,
                    memory_provider TEXT NOT NULL,
                    memory_entry_id TEXT NOT NULL,
                    memory_key TEXT NOT NULL,
                    memory_version INTEGER,
                    memory_scope TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    outcome_id TEXT,
                    csat_id TEXT,
                    occurred_at TEXT NOT NULL,
                    FOREIGN KEY (customer_id)
                        REFERENCES customer_bindings(customer_id)
                        ON DELETE RESTRICT,
                    FOREIGN KEY (conversation_id)
                        REFERENCES conversations(conversation_id)
                        ON DELETE RESTRICT,
                    FOREIGN KEY (outcome_id)
                        REFERENCES outcomes(outcome_id)
                        ON DELETE RESTRICT,
                    FOREIGN KEY (csat_id)
                        REFERENCES csat(csat_id)
                        ON DELETE RESTRICT
                );
                """
            )


class CXRepositories:
    def __init__(self, database: CXDatabase) -> None:
        self.database = database

    def save_binding(self, item: CustomerBinding) -> CustomerBinding:
        return self._save("customer_bindings", item)

    def save_ticket(self, item: Ticket) -> Ticket:
        return self._save("tickets", item)

    def save_conversation(self, item: Conversation) -> Conversation:
        return self._save("conversations", item)

    def save_message(self, item: Message) -> Message:
        return self._save("messages", item)

    def save_escalation(self, item: Escalation) -> Escalation:
        return self._save("escalations", item)

    def save_outcome(self, item: Outcome) -> Outcome:
        return self._save("outcomes", item)

    def save_csat(self, item: CSAT) -> CSAT:
        return self._save("csat", item)

    def save_memory_reference(self, item: MemoryReference) -> MemoryReference:
        return self._save("memory_references", item)

    def ticket(self, ticket_id: str) -> Ticket | None:
        return self._one("tickets", "ticket_id", ticket_id, Ticket)

    def conversation(self, conversation_id: str) -> Conversation | None:
        return self._one("conversations", "conversation_id", conversation_id, Conversation)

    def escalation(self, escalation_id: str) -> Escalation | None:
        return self._one("escalations", "escalation_id", escalation_id, Escalation)

    def outcome(self, outcome_id: str) -> Outcome | None:
        return self._one("outcomes", "outcome_id", outcome_id, Outcome)

    def csat(self, csat_id: str) -> CSAT | None:
        return self._one("csat", "csat_id", csat_id, CSAT)

    def messages(self, conversation_id: str) -> list[Message]:
        return self._many("messages", "conversation_id", conversation_id, Message)

    def outcomes(self, ticket_id: str) -> list[Outcome]:
        return self._many("outcomes", "ticket_id", ticket_id, Outcome)

    def memory_references(
        self,
        *,
        execution_id: str | None = None,
        outcome_id: str | None = None,
        csat_id: str | None = None,
    ) -> list[MemoryReference]:
        clauses: list[str] = []
        values: list[str] = []
        if execution_id is not None:
            clauses.append("execution_id=?")
            values.append(execution_id)
        if outcome_id is not None:
            clauses.append("outcome_id=?")
            values.append(outcome_id)
        if csat_id is not None:
            clauses.append("csat_id=?")
            values.append(csat_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM memory_references{where} ORDER BY occurred_at",
                values,
            ).fetchall()
        return [self._model(row, MemoryReference) for row in rows]

    def customer_history(self, customer_id: str) -> CustomerHistory:
        if self.binding(customer_id) is None:
            raise KeyError(customer_id)
        conversations = self._many(
            "conversations",
            "customer_id",
            customer_id,
            Conversation,
            order_column="started_at",
        )
        messages = self._customer_many(
            """
            SELECT messages.*
            FROM messages
            JOIN conversations
                ON conversations.conversation_id = messages.conversation_id
            WHERE conversations.customer_id=?
            ORDER BY messages.created_at
            """,
            customer_id,
            Message,
        )
        tickets = self._many("tickets", "customer_id", customer_id, Ticket)
        escalations = self._customer_many(
            """
            SELECT escalations.*
            FROM escalations
            JOIN tickets ON tickets.ticket_id = escalations.ticket_id
            WHERE tickets.customer_id=?
            ORDER BY escalations.created_at
            """,
            customer_id,
            Escalation,
        )
        outcomes = self._customer_many(
            """
            SELECT outcomes.*
            FROM outcomes
            JOIN tickets ON tickets.ticket_id = outcomes.ticket_id
            WHERE tickets.customer_id=?
            ORDER BY outcomes.created_at
            """,
            customer_id,
            Outcome,
        )
        csat = self._customer_many(
            """
            SELECT csat.*
            FROM csat
            JOIN tickets ON tickets.ticket_id = csat.ticket_id
            WHERE tickets.customer_id=?
            ORDER BY csat.submitted_at
            """,
            customer_id,
            CSAT,
        )
        return CustomerHistory(
            customer_id=customer_id,
            conversations=conversations,
            messages=messages,
            tickets=tickets,
            escalations=escalations,
            outcomes=outcomes,
            csat=csat,
        )

    def binding(self, customer_id: str) -> CustomerBinding | None:
        return self._one("customer_bindings", "customer_id", customer_id, CustomerBinding)

    def _save(self, table: str, item: T) -> T:
        data = item.model_dump(mode="json")
        columns = list(data)
        values = [
            json.dumps(value) if isinstance(value, (dict, list)) else value
            for value in data.values()
        ]
        assignments = ", ".join(
            f"{column}=excluded.{column}" for column in columns if column != columns[0]
        )
        placeholders = ", ".join("?" for _ in columns)
        statement = (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT({columns[0]}) DO UPDATE SET {assignments}"
        )
        with self.database.connect() as connection:
            connection.execute(statement, values)
        return item

    def _one(
        self,
        table: str,
        key: str,
        value: str,
        factory: Callable[..., T],
    ) -> T | None:
        with self.database.connect() as connection:
            row = connection.execute(
                f"SELECT * FROM {table} WHERE {key}=?",
                (value,),
            ).fetchone()
        return self._model(row, factory) if row else None

    def _many(
        self,
        table: str,
        key: str,
        value: str,
        factory: Callable[..., T],
        *,
        order_column: str = "created_at",
    ) -> list[T]:
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM {table} WHERE {key}=? ORDER BY {order_column}",
                (value,),
            ).fetchall()
        return [self._model(row, factory) for row in rows]

    def _customer_many(
        self,
        statement: str,
        customer_id: str,
        factory: Callable[..., T],
    ) -> list[T]:
        with self.database.connect() as connection:
            rows = connection.execute(statement, (customer_id,)).fetchall()
        return [self._model(row, factory) for row in rows]

    @staticmethod
    def _model(row: sqlite3.Row, factory: Callable[..., T]) -> T:
        data: dict[str, Any] = dict(row)
        for key, value in data.items():
            if key.endswith("_at") and value is not None:
                data[key] = datetime.fromisoformat(value)
            elif key == "metadata":
                data[key] = json.loads(value)
        return factory(**data)
