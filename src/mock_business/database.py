from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from .models import (
    BusinessEvent,
    Customer,
    FulfillmentIssue,
    KnowledgeArticle,
    Order,
    OrderLine,
    Payment,
    Policy,
    Refund,
    Return,
    Shipment,
)
from .scenarios import ScenarioDefinition


SCHEMA_VERSION = "2"


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
            db.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            row = db.execute("SELECT value FROM schema_meta WHERE key = 'version'").fetchone()
            if row is None or row["value"] != SCHEMA_VERSION:
                self._rebuild_schema(db)
                db.execute("INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', ?)", (SCHEMA_VERSION,))
            else:
                self._create_schema(db)

    def _rebuild_schema(self, db: sqlite3.Connection) -> None:
        for table in (
            "events", "refunds", "returns", "fulfillment_issues", "knowledge_articles", "policies",
            "shipments", "payments", "order_lines", "orders", "products", "customers", "state",
        ):
            db.execute(f"DROP TABLE IF EXISTS {table}")
        self._create_schema(db)

    def _create_schema(self, db: sqlite3.Connection) -> None:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS customers (
                customer_id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
                segment TEXT NOT NULL, country TEXT NOT NULL, account_status TEXT NOT NULL,
                lifetime_value TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS products (
                product_id TEXT PRIMARY KEY, sku TEXT NOT NULL UNIQUE, name TEXT NOT NULL, price TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(customer_id),
                amount TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS order_lines (
                line_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(order_id),
                product_id TEXT NOT NULL REFERENCES products(product_id), quantity INTEGER NOT NULL,
                unit_price TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS payments (
                payment_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(order_id),
                amount TEXT NOT NULL, currency TEXT NOT NULL, status TEXT NOT NULL,
                provider_reference TEXT NOT NULL UNIQUE, captured_at TEXT
            );
            CREATE TABLE IF NOT EXISTS shipments (
                shipment_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(order_id),
                tracking_number TEXT NOT NULL UNIQUE, carrier TEXT NOT NULL, status TEXT NOT NULL,
                expected_delivery_at TEXT NOT NULL, last_update_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS fulfillment_issues (
                issue_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(order_id),
                line_id TEXT NOT NULL REFERENCES order_lines(line_id), issue_type TEXT NOT NULL,
                quantity_affected INTEGER NOT NULL, reported_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS returns (
                return_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(order_id),
                line_id TEXT NOT NULL REFERENCES order_lines(line_id), quantity INTEGER NOT NULL,
                reason TEXT NOT NULL, status TEXT NOT NULL, requested_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS refunds (
                refund_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(order_id),
                payment_id TEXT NOT NULL REFERENCES payments(payment_id), amount TEXT NOT NULL,
                status TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL,
                requires_approval INTEGER NOT NULL, decision_reason TEXT
            );
            CREATE TABLE IF NOT EXISTS policies (
                policy_id TEXT PRIMARY KEY, topic TEXT NOT NULL UNIQUE, version TEXT NOT NULL,
                text TEXT NOT NULL, effective_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS knowledge_articles (
                article_id TEXT PRIMARY KEY, topic TEXT NOT NULL, title TEXT NOT NULL,
                body TEXT NOT NULL, version TEXT NOT NULL, effective_at TEXT NOT NULL
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
            for table in (
                "refunds", "returns", "fulfillment_issues", "knowledge_articles", "policies", "shipments",
                "payments", "order_lines", "orders", "products", "customers", "events", "state",
            ):
                db.execute(f"DELETE FROM {table}")
            db.executemany("INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
                (x.customer_id, x.name, x.email, x.segment.value, x.country, x.account_status.value,
                 str(x.lifetime_value), x.created_at.isoformat()) for x in scenario.customers
            ])
            db.executemany("INSERT INTO products VALUES (?, ?, ?, ?)", [
                (x.product_id, x.sku, x.name, str(x.price)) for x in scenario.products
            ])
            db.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", [
                (x.order_id, x.customer_id, str(x.amount), x.status.value, x.created_at.isoformat()) for x in scenario.orders
            ])
            db.executemany("INSERT INTO order_lines VALUES (?, ?, ?, ?, ?)", [
                (x.line_id, x.order_id, x.product_id, x.quantity, str(x.unit_price)) for x in scenario.order_lines
            ])
            db.executemany("INSERT INTO payments VALUES (?, ?, ?, ?, ?, ?, ?)", [
                (x.payment_id, x.order_id, str(x.amount), x.currency, x.status.value, x.provider_reference,
                 None if x.captured_at is None else x.captured_at.isoformat()) for x in scenario.payments
            ])
            db.executemany("INSERT INTO shipments VALUES (?, ?, ?, ?, ?, ?, ?)", [
                (x.shipment_id, x.order_id, x.tracking_number, x.carrier, x.status.value,
                 x.expected_delivery_at.isoformat(), x.last_update_at.isoformat()) for x in scenario.shipments
            ])
            db.executemany("INSERT INTO fulfillment_issues VALUES (?, ?, ?, ?, ?, ?)", [
                (x.issue_id, x.order_id, x.line_id, x.issue_type.value, x.quantity_affected, x.reported_at.isoformat())
                for x in scenario.fulfillment_issues
            ])
            db.executemany("INSERT INTO returns VALUES (?, ?, ?, ?, ?, ?, ?)", [
                (x.return_id, x.order_id, x.line_id, x.quantity, x.reason, x.status.value, x.requested_at.isoformat())
                for x in scenario.returns
            ])
            db.executemany("INSERT INTO policies VALUES (?, ?, ?, ?, ?)", [
                (x.policy_id, x.topic, x.version, x.text, x.effective_at.isoformat()) for x in scenario.policies
            ])
            db.executemany("INSERT INTO knowledge_articles VALUES (?, ?, ?, ?, ?, ?)", [
                (x.article_id, x.topic, x.title, x.body, x.version, x.effective_at.isoformat())
                for x in scenario.knowledge_articles
            ])
            db.executemany("INSERT INTO state VALUES (?, ?)", {"active_scenario": scenario.scenario_id, **scenario.service_state}.items())
        self.emit("scenario.activated", scenario.scenario_id, data={"name": scenario.name})

    def state(self, key: str) -> str | None:
        with self.connection() as db:
            row = db.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def emit(self, event_type: str, scenario_id: str, *, entity_type: str | None = None,
             entity_id: str | None = None, data: dict[str, object] | None = None) -> BusinessEvent:
        occurred_at = datetime.now(UTC)
        with self.connection() as db:
            cursor = db.execute(
                "INSERT INTO events (event_type, occurred_at, scenario_id, entity_type, entity_id, data_json) VALUES (?, ?, ?, ?, ?, ?)",
                (event_type, occurred_at.isoformat(), scenario_id, entity_type, entity_id, json.dumps(data or {}, default=str)),
            )
            event_id = int(cursor.lastrowid)
        return BusinessEvent(event_id=event_id, event_type=event_type, occurred_at=occurred_at,
                             scenario_id=scenario_id, entity_type=entity_type, entity_id=entity_id, data=data or {})

    def _one(self, query: str, params: tuple[object, ...]) -> sqlite3.Row | None:
        with self.connection() as db:
            return db.execute(query, params).fetchone()

    def _many(self, query: str, params: tuple[object, ...]) -> list[sqlite3.Row]:
        with self.connection() as db:
            return db.execute(query, params).fetchall()

    def customer(self, customer_id: str) -> Customer | None:
        row = self._one("SELECT * FROM customers WHERE customer_id = ?", (customer_id,))
        return None if row is None else Customer(**dict(row))

    def orders_for_customer(self, customer_id: str) -> list[Order]:
        return [Order(**dict(row)) for row in self._many("SELECT * FROM orders WHERE customer_id = ? ORDER BY created_at DESC", (customer_id,))]

    def order(self, order_id: str) -> Order | None:
        row = self._one("SELECT * FROM orders WHERE order_id = ?", (order_id,))
        return None if row is None else Order(**dict(row))

    def order_lines(self, order_id: str) -> list[OrderLine]:
        return [OrderLine(**dict(row)) for row in self._many("SELECT * FROM order_lines WHERE order_id = ? ORDER BY line_id", (order_id,))]

    def payments_for_order(self, order_id: str) -> list[Payment]:
        return [Payment(**dict(row)) for row in self._many("SELECT * FROM payments WHERE order_id = ? ORDER BY payment_id", (order_id,))]

    def payment(self, payment_id: str) -> Payment | None:
        row = self._one("SELECT * FROM payments WHERE payment_id = ?", (payment_id,))
        return None if row is None else Payment(**dict(row))

    def shipment_for_order(self, order_id: str) -> Shipment | None:
        row = self._one("SELECT * FROM shipments WHERE order_id = ?", (order_id,))
        return None if row is None else Shipment(**dict(row))

    def fulfillment_issues_for_order(self, order_id: str) -> list[FulfillmentIssue]:
        return [FulfillmentIssue(**dict(row)) for row in self._many("SELECT * FROM fulfillment_issues WHERE order_id = ? ORDER BY issue_id", (order_id,))]

    def returns_for_order(self, order_id: str) -> list[Return]:
        return [Return(**dict(row)) for row in self._many("SELECT * FROM returns WHERE order_id = ? ORDER BY return_id", (order_id,))]

    def policy(self, topic: str) -> Policy | None:
        row = self._one("SELECT * FROM policies WHERE topic = ?", (topic,))
        return None if row is None else Policy(**dict(row))

    def knowledge_for_topic(self, topic: str) -> list[KnowledgeArticle]:
        return [KnowledgeArticle(**dict(row)) for row in self._many("SELECT * FROM knowledge_articles WHERE topic = ? ORDER BY article_id", (topic,))]

    def save_order(self, order: Order) -> None:
        with self.connection() as db:
            db.execute("UPDATE orders SET status = ? WHERE order_id = ?", (order.status.value, order.order_id))

    def save_return(self, item: Return) -> None:
        with self.connection() as db:
            db.execute("INSERT INTO returns VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (item.return_id, item.order_id, item.line_id, item.quantity, item.reason, item.status.value, item.requested_at.isoformat()))

    def save_refund(self, item: Refund) -> None:
        with self.connection() as db:
            db.execute("INSERT INTO refunds VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (item.refund_id, item.order_id, item.payment_id, str(item.amount), item.status.value,
                        item.reason, item.created_at.isoformat(), int(item.requires_approval), item.decision_reason))

    def events(self, after: int = 0) -> list[BusinessEvent]:
        return [BusinessEvent(event_id=row["event_id"], event_type=row["event_type"], occurred_at=row["occurred_at"],
                              scenario_id=row["scenario_id"], entity_type=row["entity_type"], entity_id=row["entity_id"],
                              data=json.loads(row["data_json"]))
                for row in self._many("SELECT * FROM events WHERE event_id > ? ORDER BY event_id", (after,))]
