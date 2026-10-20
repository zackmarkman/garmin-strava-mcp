"""Strava API client — raw httpx over the v3 REST API.

OAuth tokens are loaded from encrypted storage; we refresh transparently when
expiring within 60 seconds. Tool-shaped output helpers return compact dicts
sized for Claude's context window per the tier strategy in docs/plan.md.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx

from .. import config, storage

API = "https://www.strava.com/api/v3"
TOKEN_URL = "https://www.strava.com/oauth/token"
TOKENS_KEY = "strava"
_token_lock = threading.Lock()
_http = httpx.Client(timeout=30)


class StravaAuthError(RuntimeError):
    """Raised when Strava tokens are missing or refresh fails."""


def _load_tokens() -> dict[str, Any]:
    tokens = storage.load_tokens(TOKENS_KEY)
    if not tokens:
        raise StravaAuthError(
            "Strava not connected — run scripts/setup_strava_auth.py to authorize."
        )
    return tokens


def _save_tokens(tokens: dict[str, Any]) -> None:
    storage.save_tokens(TOKENS_KEY, tokens)


def _refresh(tokens: dict[str, Any]) -> dict[str, Any]:
    client_id, client_secret = config.strava_client()
    resp = httpx.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
        },
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    tokens.update(
        access_token=payload["access_token"],
        refresh_token=payload["refresh_token"],
        expires_at=payload["expires_at"],
    )
    _save_tokens(tokens)
    return tokens


def _access_token() -> str:
    with _token_lock:
        tokens = _load_tokens()
        if tokens.get("expires_at", 0) - time.time() < 60:
            tokens = _refresh(tokens)
        return tokens["access_token"]


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    resp = _http.get(
        f"{API}{path}",
        params=params,
        headers={"Authorization": f"Bearer {_access_token()}"},
        timeout=30,
    )
    if resp.status_code == 401:
        raise StravaAuthError("Strava token rejected — re-run setup_strava_auth.py.")
    if resp.status_code == 429:
        raise RuntimeError(
            "Strava API rate limit reached. Retry later; cached results remain available."
        )
    if resp.status_code == 403:
        raise StravaAuthError(
            "Strava denied access. Check activity visibility and activity:read_all scope."
        )
    if resp.status_code == 404:
        raise ValueError("Strava activity not found or not accessible to this account.")
    resp.raise_for_status()
    return resp.json()


# ----- Shaping helpers ----------------------------------------------------


def _summarize_activity(a: dict[str, Any]) -> dict[str, Any]:
    """Tier 1 compact summary — see docs/plan.md."""
    moving_s = a.get("moving_time") or 0
    distance_m = a.get("distance") or 0
    pace_s_per_km = (moving_s / (distance_m / 1000)) if distance_m else None
    return {
        "id": a.get("id"),
        "name": a.get("name"),
        "type": a.get("sport_type") or a.get("type"),
        "start": a.get("start_date_local"),
        "distance_km": round(distance_m / 1000, 2),
        "moving_time_s": moving_s,
        "avg_pace_s_per_km": round(pace_s_per_km, 1) if pace_s_per_km else None,
        "elevation_gain_m": a.get("total_elevation_gain"),
        "avg_hr": a.get("average_heartrate"),
        "max_hr": a.get("max_heartrate"),
    }


# ----- Public API ---------------------------------------------------------


def latest_activity() -> dict[str, Any] | None:
    activities = _get("/athlete/activities", {"per_page": 1, "page": 1})
    if not activities:
        return None
    return _summarize_activity(activities[0])


def athlete_stats() -> dict[str, Any]:
    me = _get("/athlete")
    s = _get(f"/athletes/{me['id']}/stats")
    return {
        "athlete_id": me.get("id"),
        "all_time_run": s.get("all_run_totals"),
        "all_time_ride": s.get("all_ride_totals"),
        "ytd_run": s.get("ytd_run_totals"),
        "ytd_ride": s.get("ytd_ride_totals"),
        "recent_run": s.get("recent_run_totals"),
        "recent_ride": s.get("recent_ride_totals"),
    }


def weekly_totals(weeks: int = 4, refresh: bool = False) -> list[dict[str, Any]]:
    """Current calendar week and preceding weeks, including empty weeks."""
    from datetime import date, timedelta

    from .activities import training_summary

    weeks = max(1, min(weeks, 52))
    end = date.today()
    start = end - timedelta(days=end.weekday() + 7 * (weeks - 1))
    data = training_summary(str(start), str(end), "week", refresh=refresh)
    if not data["complete"]:
        raise RuntimeError(data["warning"])
    return [
        {
            "week": row["period"],
            "distance_km": round(row["distance_m"] / 1000, 2)
            if row["distance_m"] is not None
            else None,
            "moving_time_s": row["moving_time_s"],
            "elevation_gain_m": row["elevation_gain_m"],
            "activity_count": row["activity_count"],
        }
        for row in reversed(data["periods"])
    ]


def starred_segments() -> list[dict[str, Any]]:
    segments = _get("/segments/starred", {"per_page": 30})
    return [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "activity_type": s.get("activity_type"),
            "distance_m": s.get("distance"),
            "avg_grade": s.get("average_grade"),
            "elevation_high": s.get("elevation_high"),
            "elevation_low": s.get("elevation_low"),
            "pr_time_s": s.get("pr_time"),
        }
        for s in segments
    ]
