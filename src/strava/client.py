"""Strava API client — raw httpx over the v3 REST API.

OAuth tokens are loaded from encrypted storage; we refresh transparently when
expiring within 60 seconds. Tool-shaped output helpers return compact dicts
sized for Claude's context window per the tier strategy in docs/plan.md.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from .. import config, storage

API = "https://www.strava.com/api/v3"
TOKEN_URL = "https://www.strava.com/oauth/token"
TOKENS_KEY = "strava"


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
    tokens = _load_tokens()
    if tokens.get("expires_at", 0) - time.time() < 60:
        tokens = _refresh(tokens)
    return tokens["access_token"]


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    resp = httpx.get(
        f"{API}{path}",
        params=params,
        headers={"Authorization": f"Bearer {_access_token()}"},
        timeout=30,
    )
    if resp.status_code == 401:
        raise StravaAuthError("Strava token rejected — re-run setup_strava_auth.py.")
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


def recent_activities(limit: int = 10) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 50))
    activities = _get("/athlete/activities", {"per_page": limit, "page": 1})
    return [_summarize_activity(a) for a in activities]


def activity_details(activity_id: int) -> dict[str, Any]:
    """Tier 2 — rich single-activity view."""
    a = _get(f"/activities/{activity_id}", {"include_all_efforts": "false"})
    out = _summarize_activity(a)
    out["description"] = a.get("description")
    out["gear"] = (a.get("gear") or {}).get("name")
    out["calories"] = a.get("calories")
    out["avg_cadence"] = a.get("average_cadence")
    out["splits"] = [
        {
            "split": s.get("split"),
            "distance_m": s.get("distance"),
            "elapsed_time_s": s.get("elapsed_time"),
            "moving_time_s": s.get("moving_time"),
            "avg_speed_mps": s.get("average_speed"),
            "avg_hr": s.get("average_heartrate"),
            "elevation_diff_m": s.get("elevation_difference"),
        }
        for s in (a.get("splits_metric") or [])
    ]
    laps = a.get("laps") or []
    out["laps"] = [
        {
            "lap": lap.get("lap_index"),
            "distance_m": lap.get("distance"),
            "moving_time_s": lap.get("moving_time"),
            "avg_hr": lap.get("average_heartrate"),
        }
        for lap in laps
    ]
    return out


def activity_streams(
    activity_id: int, detail_level: str = "summary"
) -> dict[str, Any]:
    """Tier 3 — time-series streams. Truncates to 500 points unless `full`."""
    keys = "time,distance,heartrate,altitude,velocity_smooth,cadence,watts"
    streams = _get(
        f"/activities/{activity_id}/streams",
        {"keys": keys, "key_by_type": "true"},
    )
    if not isinstance(streams, dict):
        return {"error": "no streams available"}
    total = max((s.get("original_size", 0) for s in streams.values()), default=0)
    limit = None if detail_level == "full" else 500
    out: dict[str, Any] = {"total_points": total, "returned_points": total}
    for name, stream in streams.items():
        data = stream.get("data") or []
        if limit and len(data) > limit:
            step = max(1, len(data) // limit)
            data = data[::step][:limit]
            out["returned_points"] = len(data)
        out[name] = data
    if limit and out["returned_points"] < total:
        out["note"] = (
            f"downsampled to {out['returned_points']} of {total} points; "
            "pass detail_level='full' for raw data"
        )
    return out


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


def weekly_totals(weeks: int = 4) -> list[dict[str, Any]]:
    """Sum of distance/time/elevation per week, most recent first."""
    weeks = max(1, min(weeks, 12))
    # Strava has no weekly endpoint — derive from recent activities.
    per_page = 200
    activities = _get("/athlete/activities", {"per_page": per_page, "page": 1})
    buckets: dict[str, dict[str, float]] = {}
    for a in activities:
        start = a.get("start_date_local") or ""
        if not start:
            continue
        # ISO week key
        from datetime import datetime

        dt = datetime.fromisoformat(start.rstrip("Z"))
        iso_year, iso_week, _ = dt.isocalendar()
        key = f"{iso_year}-W{iso_week:02d}"
        b = buckets.setdefault(
            key,
            {"distance_m": 0.0, "moving_time_s": 0.0, "elevation_m": 0.0, "count": 0},
        )
        b["distance_m"] += a.get("distance") or 0
        b["moving_time_s"] += a.get("moving_time") or 0
        b["elevation_m"] += a.get("total_elevation_gain") or 0
        b["count"] += 1
    ordered = sorted(buckets.items(), reverse=True)[:weeks]
    return [
        {
            "week": week,
            "distance_km": round(v["distance_m"] / 1000, 2),
            "moving_time_s": int(v["moving_time_s"]),
            "elevation_gain_m": round(v["elevation_m"], 1),
            "activity_count": int(v["count"]),
        }
        for week, v in ordered
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
