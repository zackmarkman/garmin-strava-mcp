"""Centralized env/config access."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _require(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {key}")
    return value


def server_token() -> str:
    return _require("SERVER_TOKEN")


def fernet_key() -> bytes:
    return _require("FERNET_KEY").encode()


def strava_client() -> tuple[str, str]:
    return _require("STRAVA_CLIENT_ID"), _require("STRAVA_CLIENT_SECRET")


def database_path() -> Path:
    raw = os.environ.get("DATABASE_PATH", "data/mcp.db")
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def host() -> str:
    return os.environ.get("HOST", "0.0.0.0")


def port() -> int:
    return int(os.environ.get("PORT", "8000"))
