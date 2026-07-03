from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Iterator
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reported_type TEXT NOT NULL,
    ai_type TEXT NOT NULL,
    description TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    location TEXT NOT NULL,
    reporter_name TEXT,
    reporter_contact TEXT,
    urgency TEXT NOT NULL,
    urgency_score INTEGER NOT NULL,
    assessment_reason TEXT NOT NULL,
    assessment_source TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    confirmed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_urgency ON events (urgency_score DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_type ON events (ai_type, urgency_score DESC);
CREATE INDEX IF NOT EXISTS idx_events_status ON events (status, created_at DESC);
"""


SORT_ORDERS = {
    "urgency": "CASE status WHEN 'pending' THEN 0 ELSE 1 END, urgency_score DESC, created_at DESC",
    "type": "ai_type COLLATE NOCASE ASC, urgency_score DESC, created_at DESC",
    "time": "created_at DESC",
    "status": "CASE status WHEN 'pending' THEN 0 ELSE 1 END, created_at DESC",
}


def connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def managed_connection(database_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(database_path)
    try:
        yield connection
    finally:
        connection.close()


def initialize_database(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with managed_connection(database_path) as connection:
        connection.executescript(SCHEMA)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_event(
    database_path: Path, event_payload: dict[str, Any], assessment: dict[str, Any]
) -> dict[str, Any]:
    created_at = utc_now()
    with managed_connection(database_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO events (
                reported_type,
                ai_type,
                description,
                occurred_at,
                location,
                reporter_name,
                reporter_contact,
                urgency,
                urgency_score,
                assessment_reason,
                assessment_source,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_payload["type"],
                assessment["type"],
                event_payload["description"],
                event_payload["occurred_at"],
                event_payload["location"],
                event_payload.get("reporter_name") or None,
                event_payload.get("reporter_contact") or None,
                assessment["urgency"],
                int(assessment["urgency_score"]),
                assessment["reason"],
                assessment["source"],
                created_at,
            ),
        )
        connection.commit()
        return get_event(database_path, int(cursor.lastrowid)) or {}


def list_events(database_path: Path, sort: str = "urgency") -> list[dict[str, Any]]:
    order_by = SORT_ORDERS.get(sort, SORT_ORDERS["urgency"])
    with managed_connection(database_path) as connection:
        rows = connection.execute(f"SELECT * FROM events ORDER BY {order_by}").fetchall()
        return [row_to_dict(row) for row in rows]


def get_event(database_path: Path, event_id: int) -> dict[str, Any] | None:
    with managed_connection(database_path) as connection:
        row = connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            return None
        return row_to_dict(row)


def confirm_event(database_path: Path, event_id: int) -> dict[str, Any] | None:
    confirmed_at = utc_now()
    with managed_connection(database_path) as connection:
        cursor = connection.execute(
            """
            UPDATE events
            SET status = 'confirmed',
                confirmed_at = ?
            WHERE id = ?
            """,
            (confirmed_at, event_id),
        )
        connection.commit()
        if cursor.rowcount == 0:
            return None

    return get_event(database_path, event_id)


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["confirmed"] = data["status"] == "confirmed"
    return data
