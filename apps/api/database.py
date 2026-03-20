from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL,
    target_url TEXT NOT NULL,
    target_domain TEXT NOT NULL,
    evidence_path TEXT NOT NULL,
    notes TEXT DEFAULT '',
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_resolutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    provider_key TEXT NOT NULL,
    provider_name TEXT NOT NULL,
    confidence REAL NOT NULL,
    sources_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    FOREIGN KEY(case_id) REFERENCES cases(id)
);

CREATE TABLE IF NOT EXISTS channel_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,
    provider_role TEXT NOT NULL,
    provider_key TEXT NOT NULL,
    provider_name TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    route_type TEXT NOT NULL,
    executor TEXT NOT NULL,
    region TEXT NOT NULL,
    language TEXT NOT NULL,
    status TEXT NOT NULL,
    captcha_strategy TEXT NOT NULL,
    requires_login INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(case_id) REFERENCES cases(id)
);

CREATE TABLE IF NOT EXISTS execution_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id INTEGER NOT NULL,
    executor TEXT NOT NULL,
    result TEXT NOT NULL,
    external_ticket_id TEXT DEFAULT '',
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    error_code TEXT DEFAULT '',
    FOREIGN KEY(action_id) REFERENCES channel_actions(id)
);

CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL,
    notes TEXT DEFAULT '',
    total_urls INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batch_case_map (
    batch_id INTEGER NOT NULL,
    case_id INTEGER NOT NULL,
    PRIMARY KEY (batch_id, case_id),
    FOREIGN KEY(batch_id) REFERENCES batches(id),
    FOREIGN KEY(case_id) REFERENCES cases(id)
);

CREATE TABLE IF NOT EXISTS case_verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL,
    check_url TEXT NOT NULL,
    verdict TEXT NOT NULL,
    http_status TEXT DEFAULT '',
    checked_at TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    FOREIGN KEY(case_id) REFERENCES cases(id)
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def init(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            connection.commit()
