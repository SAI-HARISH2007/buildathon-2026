"""SQLite persistence. Stdlib sqlite3 on purpose: zero setup for anyone cloning
the repo, and the whole state of a demo run lives in one inspectable file."""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "reclaim.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS payments (
    payment_id TEXT PRIMARY KEY,
    order_id TEXT,
    amount INTEGER NOT NULL,          -- paise
    currency TEXT NOT NULL,
    method TEXT NOT NULL,
    failure_reason TEXT NOT NULL,
    category TEXT NOT NULL,
    customer_name TEXT,
    customer_email TEXT,
    customer_contact TEXT,
    failed_at TEXT NOT NULL,
    status TEXT NOT NULL,             -- failed|scheduled|recovered|abandoned|manual_review|merchant_alert
    attempts INTEGER NOT NULL DEFAULT 0,
    recovered_at TEXT
);

CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id TEXT NOT NULL,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,               -- classified|scheduled|retry_attempted|link_created|message_drafted|recovered|abandoned|escalated
    source TEXT NOT NULL,             -- rule|llm|system
    rationale TEXT,
    detail TEXT                       -- JSON
);

CREATE TABLE IF NOT EXISTS schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id TEXT NOT NULL,
    due_at TEXT NOT NULL,
    attempt_no INTEGER NOT NULL,
    done INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS clock (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    now TEXT NOT NULL
);
"""


def connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def log_action(conn, payment_id: str, at: str, kind: str, source: str,
               rationale: str = "", detail: dict | None = None) -> None:
    conn.execute(
        "INSERT INTO actions (payment_id, at, kind, source, rationale, detail) VALUES (?,?,?,?,?,?)",
        (payment_id, at, kind, source, rationale, json.dumps(detail or {})),
    )
