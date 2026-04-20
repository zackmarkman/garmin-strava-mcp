"""Manual sync — clears volatile caches and fetches the latest activity from both services."""

from __future__ import annotations

from typing import Any

from . import cache


def run_sync() -> dict[str, Any]:
    """Clear volatile caches and return a summary of the latest activity.

    Kept framework-agnostic so both the HTTP `/sync` route and the `sync_latest`
    MCP tool can call it. Imports clients lazily to avoid circular imports and to
    keep startup fast when only one service is used.
    """
    cleared = cache.clear(cache.SYNC_CLEAR_BUCKETS)

    latest: dict[str, Any] = {}
    errors: dict[str, str] = {}

    try:
        from .strava.client import latest_activity as strava_latest

        latest["strava"] = strava_latest()
    except Exception as exc:  # noqa: BLE001
        errors["strava"] = str(exc)

    try:
        from .garmin.client import latest_activity as garmin_latest

        latest["garmin"] = garmin_latest()
    except Exception as exc:  # noqa: BLE001
        errors["garmin"] = str(exc)

    return {"cleared": cleared, "latest": latest, "errors": errors}
