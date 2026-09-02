from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime
from typing import Any, TypeVar

from cx_platform.domain.models import CSAT, CustomerBinding, Conversation, Escalation, Message, Outcome, Ticket

T = TypeVar("T")


class CXDatabase:
    schema_version = 1

    def __init__(self, path: str = "cx_platform.db") -> None:
        self.path = path
        self._migrate()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _migrate(self) -> None:
        with self.connect() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS cx_schema_version (version INTEGER NOT NULL)")
            row = connection.execute("SELECT version FROM cx_schema_version LIMIT 1").fetchone()
            if row is None:
                connection.execute("INSERT INTO cx_schema_version VALUES (?)", (self.schema_version,))
            elif row["version"] != self.schema_version:
                raise RuntimeError(f"Unsupported CX schema version: {row['version']}")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS customer_bindings (customer_id TEXT PRIMARY KEY, external_customer_id TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tickets (ticket_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, conversation_id TEXT UNIQUE NOT NULL, status TEXT NOT NULL, reason TEXT NOT NULL, priority TEXT NOT NULL, resolution_code TEXT, created_at TEXT NOT NULL, resolved_at TEXT);
                CREATE TABLE IF NOT EXISTS conversations (conversation_id TEXT PRIMARY KEY, ticket_id TEXT UNIQUE NOT NULL, customer_id TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL, ended_at TEXT);
                CREATE TABLE IF NOT EXISTS messages (message_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, actor_type TEXT NOT NULL, actor_id TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS escalations (escalation_id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL, reason TEXT NOT NULL, summary TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, resolved_at TEXT);
                CREATE TABLE IF NOT EXISTS outcomes (outcome_id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL, outcome_type TEXT NOT NULL, metadata TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS csat (csat_id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL, score INTEGER NOT NULL, comment TEXT, submitted_at TEXT NOT NULL);
            """)


class CXRepositories:
    def __init__(self, database: CXDatabase) -> None:
        self.database = database

    def save_binding(self, item: CustomerBinding) -> CustomerBinding: return self._save("customer_bindings", item)
    def save_ticket(self, item: Ticket) -> Ticket: return self._save("tickets", item)
    def save_conversation(self, item: Conversation) -> Conversation: return self._save("conversations", item)
    def save_message(self, item: Message) -> Message: return self._save("messages", item)
    def save_escalation(self, item: Escalation) -> Escalation: return self._save("escalations", item)
    def save_outcome(self, item: Outcome) -> Outcome: return self._save("outcomes", item)
    def save_csat(self, item: CSAT) -> CSAT: return self._save("csat", item)

    def ticket(self, ticket_id: str) -> Ticket | None: return self._one("tickets", "ticket_id", ticket_id, Ticket)
    def conversation(self, conversation_id: str) -> Conversation | None: return self._one("conversations", "conversation_id", conversation_id, Conversation)
    def escalation(self, escalation_id: str) -> Escalation | None: return self._one("escalations", "escalation_id", escalation_id, Escalation)
    def messages(self, conversation_id: str) -> list[Message]: return self._many("messages", "conversation_id", conversation_id, Message)
    def outcomes(self, ticket_id: str) -> list[Outcome]: return self._many("outcomes", "ticket_id", ticket_id, Outcome)

    def _save(self, table: str, item: T) -> T:
        data = item.model_dump(mode="json")  # type: ignore[attr-defined]
        columns = list(data)
        values = [json.dumps(value) if isinstance(value, (dict, list)) else value for value in data.values()]
        assignments = ", ".join(f"{column}=excluded.{column}" for column in columns if column != columns[0])
        with self.database.connect() as connection:
            connection.execute(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)}) ON CONFLICT({columns[0]}) DO UPDATE SET {assignments}", values)
        return item

    def _one(self, table: str, key: str, value: str, factory: Callable[..., T]) -> T | None:
        with self.database.connect() as connection: row = connection.execute(f"SELECT * FROM {table} WHERE {key}=?", (value,)).fetchone()
        return self._model(row, factory) if row else None

    def _many(self, table: str, key: str, value: str, factory: Callable[..., T]) -> list[T]:
        with self.database.connect() as connection: rows = connection.execute(f"SELECT * FROM {table} WHERE {key}=? ORDER BY created_at", (value,)).fetchall()
        return [self._model(row, factory) for row in rows]

    @staticmethod
    def _model(row: sqlite3.Row, factory: Callable[..., T]) -> T:
        data: dict[str, Any] = dict(row)
        for key, value in data.items():
            if key.endswith("_at") and value is not None: data[key] = datetime.fromisoformat(value)
            elif key == "metadata": data[key] = json.loads(value)
        return factory(**data)
