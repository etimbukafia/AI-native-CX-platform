from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from .models import BusinessEvent, Customer, Order, Policy, Refund, Shipment
from .scenarios import ScenarioDefinition


class Database:
    def __init__(self, path: str | Path = "mock_business.db") -> None:
        self.path = str(path)
        self._anchor: sqlite3.Connection | None = None
        if self.path == ":memory:":
            self._dsn = "file:mock_business?mode=memory&cache=shared"
            self._uri = True
            self._anchor = sqlite3.connect(self._dsn, uri=True)
            self._anchor.row_factory = sqlite3.Row
        else:
            self._dsn = self.path
            self._uri = False
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._dsn, uri=self._uri)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS customers (
                    customer_id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL,
                    segment TEXT NOT NULL, country TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS products (
                    product_id TEXT PRIMARY KEY, name TEXT NOT NULL, price TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, product_id TEXT NOT NULL,
                    amount TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS shipments (
                    shipment_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, tracking_number TEXT NOT NULL,
                    status TEXT NOT NULL, expected_delivery_at TEXT NOT NULL, last_update_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS policies (
                    policy_id TEXT PRIMARY KEY, topic TEXT NOT NULL, version TEXT NOT NULL, text TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS refunds (
                    refund_id TEXT PRIMARY KEY, order_id TEXT NOT NULL, amount TEXT NOT NULL,
                    status TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL, scenario_id TEXT NOT NULL, entity_type TEXT,
                    entity_id TEXT, data_json TEXT NOT NULL
                );
                """
            )

    def activate(self, scenario: ScenarioDefinition) -> None:
        with self.connection() as db:
            for table in ("customers", "products", "orders", "shipments", "policies", "refunds", "events", "state"):
                db.execute(f"DELETE FROM {table}")
            db.executemany(
                "INSERT INTO customers VALUES (?, ?, ?, ?, ?)",
                [(x.customer_id, x.name, x.email, x.segment.value, x.country) for x in scenario.customers],
            )
            db.executemany(
                "INSERT INTO products VALUES (?, ?, ?)",
                [(x.product_id, x.name, str(x.price)) for x in scenario.products],
            )
            db.executemany(
                "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)",
                [(x.order_id, x.customer_id, x.product_id, str(x.amount), x.status.value, x.created_at.isoformat()) for x in scenario.orders],
            )
            db.executemany(
                "INSERT INTO shipments VALUES (?, ?, ?, ?, ?, ?)",
                [(x.shipment_id, x.order_id, x.tracking_number, x.status.value, x.expected_delivery_at.isoformat(), x.last_update_at.isoformat()) for x in scenario.shipments],
            )
            db.executemany(
                "INSERT INTO policies VALUES (?, ?, ?, ?)",
                [(x.policy_id, x.topic, x.version, x.text) for x in scenario.policies],
            )
            state = {"active_scenario": scenario.scenario_id, **scenario.service_state}
            db.executemany("INSERT INTO state VALUES (?, ?)", state.items())
        self.emit("scenario.activated", scenario.scenario_id, data={"name": scenario.name})

    def state(self, key: str) -> str | None:
        with self.connection() as db:
            row = db.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def emit(self, event_type: str, scenario_id: str, *, entity_type: str | None = None, entity_id: str | None = None, data: dict[str, object] | None = None) -> BusinessEvent:
        occurred_at = datetime.now(UTC)
        with self.connection() as db:
            cursor = db.execute(
                "INSERT INTO events (event_type, occurred_at, scenario_id, entity_type, entity_id, data_json) VALUES (?, ?, ?, ?, ?, ?)",
                (event_type, occurred_at.isoformat(), scenario_id, entity_type, entity_id, json.dumps(data or {}, default=str)),
            )
            event_id = int(cursor.lastrowid)
        return BusinessEvent(event_id=event_id, event_type=event_type, occurred_at=occurred_at, scenario_id=scenario_id, entity_type=entity_type, entity_id=entity_id, data=data or {})

    def customer(self, customer_id: str) -> Customer | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM customers WHERE customer_id = ?", (customer_id,)).fetchone()
        return None if row is None else Customer(**dict(row))

    def orders_for_customer(self, customer_id: str) -> list[Order]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM orders WHERE customer_id = ? ORDER BY created_at DESC", (customer_id,)).fetchall()
        return [Order(**dict(row)) for row in rows]

    def order(self, order_id: str) -> Order | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
        return None if row is None else Order(**dict(row))

    def shipment_for_order(self, order_id: str) -> Shipment | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM shipments WHERE order_id = ?", (order_id,)).fetchone()
        return None if row is None else Shipment(**dict(row))

    def policy(self, topic: str) -> Policy | None:
        with self.connection() as db:
            row = db.execute("SELECT * FROM policies WHERE topic = ?", (topic,)).fetchone()
        return None if row is None else Policy(**dict(row))

    def save_order(self, order: Order) -> None:
        with self.connection() as db:
            db.execute("UPDATE orders SET status = ? WHERE order_id = ?", (order.status.value, order.order_id))

    def save_refund(self, refund: Refund) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT INTO refunds VALUES (?, ?, ?, ?, ?, ?)",
                (refund.refund_id, refund.order_id, str(refund.amount), refund.status.value, refund.reason, refund.created_at.isoformat()),
            )

    def events(self, after: int = 0) -> list[BusinessEvent]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM events WHERE event_id > ? ORDER BY event_id", (after,)).fetchall()
        return [
            BusinessEvent(event_id=row["event_id"], event_type=row["event_type"], occurred_at=row["occurred_at"], scenario_id=row["scenario_id"], entity_type=row["entity_type"], entity_id=row["entity_id"], data=json.loads(row["data_json"]))
            for row in rows
        ]
