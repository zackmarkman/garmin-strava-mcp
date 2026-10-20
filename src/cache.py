"""Per-tool TTL cache, SQLite-backed. See plan docs/plan.md for TTL rationale."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from collections.abc import Callable
from contextlib import closing
from typing import Any

from . import config
from .storage import _schema  # ensures schema exists in any connection

_lock = threading.Lock()

# TTL in seconds, keyed by logical bucket. Tools pass their bucket name.
TTL: dict[str, int] = {
    "activity_list": 4 * 3600,
    "activity_detail": 7 * 24 * 3600,
    "strava_streams": 3600,
    "sleep": 6 * 3600,
    "wellness": 1 * 3600,  # body battery, stress, HRV
    "training": 6 * 3600,  # VO2 max, training load/status
    "athlete_stats": 4 * 3600,
}

# Buckets cleared by /sync — activity lists and aggregate stats.
SYNC_CLEAR_BUCKETS: tuple[str, ...] = ("activity_list", "athlete_stats")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.database_path(), isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_schema)
    return conn


def _key(bucket: str, name: str, args: dict[str, Any]) -> str:
    payload = json.dumps(args, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f"{bucket}:{name}:{digest}"


def get_or_fetch(
    bucket: str,
    name: str,
    args: dict[str, Any],
    fetch: Callable[[], Any],
    refresh: bool = False,
) -> Any:
    if bucket not in TTL:
        raise ValueError(f"Unknown cache bucket: {bucket}")
    key = _key(bucket, name, args)
    now = int(time.time())
    if not refresh:
        with _lock, closing(_connect()) as conn:
            row = conn.execute(
                "SELECT value_json, expires_at FROM cache WHERE key=?", (key,)
            ).fetchone()
        if row and row[1] > now:
            return json.loads(row[0])
    value = fetch()
    expires = now + TTL[bucket]
    with _lock, closing(_connect()) as conn:
        conn.execute("DELETE FROM cache WHERE expires_at <= ?", (now,))
        conn.execute(
            "INSERT INTO cache(key, value_json, expires_at) VALUES(?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, "
            "expires_at=excluded.expires_at",
            (key, json.dumps(value, default=str), expires),
        )
    return value


def clear(buckets: tuple[str, ...] = SYNC_CLEAR_BUCKETS) -> int:
    """Drop cached entries in the given buckets. Returns count deleted."""
    total = 0
    with _lock, closing(_connect()) as conn:
        for bucket in buckets:
            cur = conn.execute("DELETE FROM cache WHERE key LIKE ?", (f"{bucket}:%",))
            total += cur.rowcount or 0
    return total


def stats() -> dict[str, int]:
    with _lock, closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT substr(key, 1, instr(key, ':') - 1) AS bucket, COUNT(*) "
            "FROM cache GROUP BY bucket"
        ).fetchall()
    return {bucket: count for bucket, count in rows}
