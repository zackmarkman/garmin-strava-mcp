"""SQLite-backed storage for encrypted OAuth tokens and cached responses.

Two logical stores share one DB file:
- `tokens` (key, ciphertext) — Fernet-encrypted JSON blobs for Garmin/Strava
- `cache`  (key, value_json, expires_at) — see src/cache.py
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

from cryptography.fernet import Fernet

from . import config

_lock = threading.Lock()
_schema = """
CREATE TABLE IF NOT EXISTS tokens (
    key        TEXT PRIMARY KEY,
    ciphertext BLOB NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS cache (
    key        TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache(expires_at);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.database_path(), isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_schema)
    return conn


def _fernet() -> Fernet:
    return Fernet(config.fernet_key())


def save_tokens(key: str, data: dict[str, Any]) -> None:
    blob = _fernet().encrypt(json.dumps(data).encode())
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO tokens(key, ciphertext, updated_at) VALUES(?, ?, strftime('%s','now')) "
            "ON CONFLICT(key) DO UPDATE SET ciphertext=excluded.ciphertext, updated_at=excluded.updated_at",
            (key, blob),
        )


def load_tokens(key: str) -> dict[str, Any] | None:
    with _lock, _connect() as conn:
        row = conn.execute("SELECT ciphertext FROM tokens WHERE key=?", (key,)).fetchone()
    if row is None:
        return None
    return json.loads(_fernet().decrypt(row[0]).decode())


def clear_tokens(key: str) -> None:
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM tokens WHERE key=?", (key,))
