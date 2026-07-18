"""Garmin Connect client — wraps `garminconnect` with token persistence.

Session token blob is stored encrypted via src.storage. On each call we lazily
restore the session, let `garminconnect` handle DI-token refresh, and re-persist
the (potentially refreshed) blob. Auth errors raise GarminAuthError with an
actionable message.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any

from garminconnect import Garmin, GarminConnectAuthenticationError

from .. import storage

TOKENS_KEY = "garmin"
_AUTH_MSG = "Garmin session expired — re-run scripts/setup_garmin_auth.py to reconnect."

_lock = threading.Lock()
_client: Garmin | None = None


class GarminAuthError(RuntimeError):
    """Raised when Garmin tokens are missing, expired, or refresh fails."""


def _load_client() -> Garmin:
    global _client
    if _client is not None:
        return _client
    tokens = storage.load_tokens(TOKENS_KEY)
    if not tokens or not tokens.get("session"):
        raise GarminAuthError(
            "Garmin not connected — run scripts/setup_garmin_auth.py to authorize."
        )
    g = Garmin()
    try:
        g.login(tokenstore=tokens["session"])
    except GarminConnectAuthenticationError as exc:
        raise GarminAuthError(_AUTH_MSG) from exc
    _client = g
    return g


def _persist_session() -> None:
    if _client is None:
        return
    tokens = storage.load_tokens(TOKENS_KEY) or {}
    tokens["session"] = _client.client.dumps()
    storage.save_tokens(TOKENS_KEY, tokens)


def _call(fn, *args, **kwargs):
    with _lock:
        g = _load_client()
        try:
            result = fn(g, *args, **kwargs)
        except GarminConnectAuthenticationError as exc:
            raise GarminAuthError(_AUTH_MSG) from exc
        _persist_session()
        return result


def _today() -> str:
    return datetime.now().date().isoformat()


def _date_offset(days_ago: int) -> str:
    return (datetime.now().date() - timedelta(days=days_ago)).isoformat()


def _find_latest(fetcher, is_populated, max_days_back: int = 6) -> tuple[str, Any]:
    """Walk back from today until `is_populated(data)` is truthy.

    Returns (date_iso, data) of the most recent populated day, or (today, None)
    if nothing in the window has data. Used to make "today-is-empty" degrade
    gracefully to the freshest available reading.
    """
    last_date = _today()
    last_data: Any = None
    for days_ago in range(max_days_back + 1):
        d = _date_offset(days_ago)
        data = fetcher(d)
        last_date, last_data = d, data
        if is_populated(data):
            return d, data
    return last_date, last_data


# ----- Shaping helpers ----------------------------------------------------

def _summarize_activity(a: dict[str, Any]) -> dict[str, Any]:
    duration_s = a.get("duration") or 0
    distance_m = a.get("distance") or 0
    pace = (duration_s / (distance_m / 1000)) if distance_m else None
    return {
        "id": a.get("activityId"),
        "name": a.get("activityName"),
        "type": (a.get("activityType") or {}).get("typeKey"),
        "start": a.get("startTimeLocal"),
        "distance_km": round(distance_m / 1000, 2),
        "duration_s": int(duration_s),
        "avg_pace_s_per_km": round(pace, 1) if pace else None,
        "elevation_gain_m": a.get("elevationGain"),
        "avg_hr": a.get("averageHR"),
        "max_hr": a.get("maxHR"),
    }


# ----- Public API ---------------------------------------------------------

def latest_activity() -> dict[str, Any] | None:
    activities = _call(lambda g: g.get_activities(0, 1))
    if not activities:
        return None
    return _summarize_activity(activities[0])


def recent_activities(limit: int = 10) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 50))
    activities = _call(lambda g, n=limit: g.get_activities(0, n))
    return [_summarize_activity(a) for a in activities]


def activity_details(activity_id: int) -> dict[str, Any]:
    summary = _call(lambda g, i=activity_id: g.get_activity(i))
    out = _summarize_activity(summary) if summary else {}
    try:
        splits = _call(lambda g, i=activity_id: g.get_activity_splits(i))
        out["splits"] = splits.get("lapDTOs") if isinstance(splits, dict) else splits
    except Exception:  # noqa: BLE001
        pass
    try:
        hr_zones = _call(lambda g, i=activity_id: g.get_activity_hr_in_timezones(i))
        out["hr_zones"] = hr_zones
    except Exception:  # noqa: BLE001
        pass
    return out


def daily_summary(date: str | None = None) -> dict[str, Any]:
    date = date or _today()
    data = _call(lambda g, d=date: g.get_stats(d))
    return {
        "date": date,
        "steps": data.get("totalSteps"),
        "step_goal": data.get("dailyStepGoal"),
        "calories_total": data.get("totalKilocalories"),
        "calories_active": data.get("activeKilocalories"),
        "active_minutes": (data.get("activeSeconds") or 0) // 60,
        "floors_climbed": data.get("floorsAscended"),
        "distance_m": data.get("totalDistanceMeters"),
        "resting_hr": data.get("restingHeartRate"),
    }


def _ms_local_to_iso(ms: int | None) -> str | None:
    # Garmin's *_TimestampLocal fields are epoch ms whose UTC interpretation
    # equals the user's local wall-clock time. Read as UTC → strip tz → ISO.
    if ms is None:
        return None
    return datetime.utcfromtimestamp(ms / 1000).isoformat(timespec="seconds")


def sleep(date: str | None = None) -> dict[str, Any]:
    date = date or _today()
    data = _call(lambda g, d=date: g.get_sleep_data(d))
    dto = (data or {}).get("dailySleepDTO") or {}
    return {
        "date": date,
        "sleep_score": (dto.get("sleepScores") or {}).get("overall", {}).get("value"),
        "duration_s": dto.get("sleepTimeSeconds"),
        "deep_s": dto.get("deepSleepSeconds"),
        "light_s": dto.get("lightSleepSeconds"),
        "rem_s": dto.get("remSleepSeconds"),
        "awake_s": dto.get("awakeSleepSeconds"),
        "start_local": _ms_local_to_iso(dto.get("sleepStartTimestampLocal")),
        "end_local": _ms_local_to_iso(dto.get("sleepEndTimestampLocal")),
    }


def body_battery(days: int = 1) -> list[dict[str, Any]]:
    days = max(1, min(days, 7))
    end = datetime.now().date()
    start = end - timedelta(days=days - 1)
    start_iso, end_iso = start.isoformat(), end.isoformat()
    data = _call(lambda g, s=start_iso, e=end_iso: g.get_body_battery(s, e))
    out = []
    for day in data or []:
        out.append(
            {
                "date": day.get("date"),
                "charged": day.get("charged"),
                "drained": day.get("drained"),
                "max": day.get("max"),
                "min": day.get("min"),
            }
        )
    return out


def _hrv_populated(data: Any) -> bool:
    return bool((data or {}).get("hrvSummary", {}).get("status"))


def _shape_hrv(date: str, data: Any) -> dict[str, Any]:
    summary = (data or {}).get("hrvSummary") or {}
    baseline = summary.get("baseline") or {}
    return {
        "date": date,
        "status": summary.get("status"),
        "last_night_avg_ms": summary.get("lastNightAvg"),
        "weekly_avg_ms": summary.get("weeklyAvg"),
        "baseline_low_ms": baseline.get("lowUpper"),
        "baseline_balanced_low_ms": baseline.get("balancedLow"),
        "baseline_balanced_upper_ms": baseline.get("balancedUpper"),
    }


def hrv(date: str | None = None) -> dict[str, Any]:
    """HRV for a date, or auto-fallback to most recent day with data (up to 6 days back)."""
    if date:
        data = _call(lambda g, d=date: g.get_hrv_data(d))
        return _shape_hrv(date, data)
    resolved, data = _find_latest(
        lambda d: _call(lambda g, dd=d: g.get_hrv_data(dd)),
        _hrv_populated,
    )
    return _shape_hrv(resolved, data)


def _vo2_populated(data: Any) -> bool:
    if isinstance(data, list) and data:
        data = data[0]
    generic = (data or {}).get("generic") or {}
    return generic.get("vo2MaxPreciseValue") is not None or generic.get("vo2MaxValue") is not None


def _shape_vo2(date: str, data: Any) -> dict[str, Any]:
    if isinstance(data, list) and data:
        data = data[0]
    generic = (data or {}).get("generic") or {}
    cycling = (data or {}).get("cycling") or {}
    return {
        "date": date,
        "run_vo2_max": generic.get("vo2MaxPreciseValue") or generic.get("vo2MaxValue"),
        "bike_vo2_max": cycling.get("vo2MaxPreciseValue") or cycling.get("vo2MaxValue"),
        "fitness_age": generic.get("fitnessAge"),
    }


def vo2_max(date: str | None = None) -> dict[str, Any]:
    """VO2 max for a date, or auto-fallback to most recent day with data."""
    if date:
        data = _call(lambda g, d=date: g.get_max_metrics(d))
        return _shape_vo2(date, data)
    resolved, data = _find_latest(
        lambda d: _call(lambda g, dd=d: g.get_max_metrics(dd)),
        _vo2_populated,
    )
    return _shape_vo2(resolved, data)


def _load_populated(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    return bool(data.get("mostRecentTrainingStatus") or data.get("mostRecentTrainingLoadBalance"))


def _shape_load(date: str, data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        data = {}
    status = data.get("mostRecentTrainingStatus") or {}
    # mostRecentTrainingStatus has a nested device-id map — flatten to a list.
    device_map = (status.get("latestTrainingStatusData") or {}) if isinstance(status, dict) else {}
    device_entries = []
    if isinstance(device_map, dict):
        for device_id, entry in device_map.items():
            if isinstance(entry, dict):
                device_entries.append(
                    {
                        "device_id": device_id,
                        "training_status": entry.get("trainingStatus"),
                        "feedback_phrase": entry.get("trainingStatusFeedbackPhrase"),
                        "fitness_trend": entry.get("fitnessTrend"),
                        "load_tunnel_min": entry.get("loadTunnelMin"),
                        "load_tunnel_max": entry.get("loadTunnelMax"),
                        "acute_load": entry.get("acuteTrainingLoadDTO", {}).get("acwrPercent")
                        if isinstance(entry.get("acuteTrainingLoadDTO"), dict)
                        else None,
                    }
                )
    balance = data.get("mostRecentTrainingLoadBalance") or {}
    balance_map = balance.get("metricsTrainingLoadBalanceDTOMap") or {}
    balance_entries = []
    if isinstance(balance_map, dict):
        for device_id, entry in balance_map.items():
            if isinstance(entry, dict):
                balance_entries.append(
                    {
                        "device_id": device_id,
                        "monthly_aerobic_low": entry.get("monthlyLoadAerobicLow"),
                        "monthly_aerobic_high": entry.get("monthlyLoadAerobicHigh"),
                        "monthly_anaerobic": entry.get("monthlyLoadAnaerobic"),
                        "training_balance_feedback": entry.get("trainingBalanceFeedbackPhrase"),
                    }
                )
    return {
        "date": date,
        "devices": device_entries,
        "load_balance": balance_entries,
    }


def training_load(date: str | None = None) -> dict[str, Any]:
    """Training status and 4-week load balance. Auto-fallback if `date` omitted."""
    if date:
        try:
            data = _call(lambda g, d=date: g.get_training_status(d))
        except Exception:  # noqa: BLE001
            data = {}
        return _shape_load(date, data)
    resolved, data = _find_latest(
        lambda d: _safe_call(lambda g, dd=d: g.get_training_status(dd)),
        _load_populated,
    )
    return _shape_load(resolved, data)


def _safe_call(fn):
    try:
        return _call(fn)
    except Exception:  # noqa: BLE001
        return {}


def _readiness_populated(data: Any) -> bool:
    if isinstance(data, list) and data:
        data = data[0]
    return isinstance(data, dict) and data.get("score") is not None


def _shape_readiness(date: str, data: Any) -> dict[str, Any]:
    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict) or data.get("score") is None:
        return {"date": date, "available": False}
    recovery_min = data.get("recoveryTime")
    return {
        "date": date,
        "available": True,
        "score": data.get("score"),
        "level": data.get("level"),
        "feedback": data.get("feedbackLong") or data.get("feedbackShort"),
        "recovery_hours": round(recovery_min / 60, 1) if recovery_min else None,
        "sleep_score": data.get("sleepScore"),
        "hrv_weekly_avg_ms": data.get("hrvWeeklyAverage"),
        "acute_load": data.get("acuteLoad"),
        "factor_feedback": {
            "sleep": data.get("sleepScoreFactorFeedback"),
            "recovery_time": data.get("recoveryTimeFactorFeedback"),
            "hrv": data.get("hrvFactorFeedback"),
            "stress_history": data.get("stressHistoryFactorFeedback"),
            "acwr": data.get("acwrFactorFeedback"),
        },
    }


def training_readiness(date: str | None = None) -> dict[str, Any]:
    """Training readiness score for a date, or auto-fallback to most recent populated day."""
    if date:
        data = _safe_call(lambda g, d=date: g.get_training_readiness(d))
        return _shape_readiness(date, data)
    resolved, data = _find_latest(
        lambda d: _safe_call(lambda g, dd=d: g.get_training_readiness(dd)),
        _readiness_populated,
    )
    return _shape_readiness(resolved, data)


def recovery_time() -> dict[str, Any]:
    """Hours until recovered, sourced from training_readiness.recoveryTime (NOT body battery).

    Auto-falls back to the most recent populated readiness day, which is the
    source of truth Garmin uses for this metric.
    """
    resolved_date, readiness = _find_latest(
        lambda d: _safe_call(lambda g, dd=d: g.get_training_readiness(dd)),
        _readiness_populated,
    )
    if isinstance(readiness, list) and readiness:
        readiness = readiness[0]
    latest_activity_raw = _safe_call(lambda g: g.get_activities(0, 1))
    from_activity = None
    if isinstance(latest_activity_raw, list) and latest_activity_raw:
        from_activity = _summarize_activity(latest_activity_raw[0])
    recovery_min = (
        (readiness or {}).get("recoveryTime") if isinstance(readiness, dict) else None
    )
    if recovery_min is None:
        return {
            "date": resolved_date,
            "hours_until_recovered": None,
            "note": "Garmin has not computed a recovery estimate for this date.",
            "from_activity": from_activity,
        }
    return {
        "date": resolved_date,
        "hours_until_recovered": round(recovery_min / 60, 1),
        "fully_recovered": recovery_min <= 0,
        "from_activity": from_activity,
    }


def stress(date: str | None = None) -> dict[str, Any]:
    date = date or _today()
    data = _call(lambda g, d=date: g.get_all_day_stress(d))
    return {
        "date": date,
        "avg_stress": data.get("avgStressLevel") if isinstance(data, dict) else None,
        "max_stress": data.get("maxStressLevel") if isinstance(data, dict) else None,
        "rest_stress_percentage": data.get("restStressPercentage")
        if isinstance(data, dict)
        else None,
    }


def data_freshness() -> dict[str, Any]:
    """Walk back up to 7 days per metric and report the most recent populated date.

    Lets the LLM ground its queries — "your last synced sleep is from 2026-04-18"
    prevents hallucinating interpretations of null/stale data.
    """
    out: dict[str, Any] = {}

    def _probe(label: str, fetcher, is_populated):
        for days_ago in range(7):
            d = _date_offset(days_ago)
            try:
                data = fetcher(d)
            except Exception:  # noqa: BLE001
                data = None
            if is_populated(data):
                out[label] = d
                return
        out[label] = None

    _probe(
        "sleep",
        lambda d: _call(lambda g, dd=d: g.get_sleep_data(dd)),
        lambda data: bool((data or {}).get("dailySleepDTO", {}).get("sleepTimeSeconds")),
    )
    _probe(
        "hrv",
        lambda d: _call(lambda g, dd=d: g.get_hrv_data(dd)),
        _hrv_populated,
    )
    _probe(
        "training_readiness",
        lambda d: _safe_call(lambda g, dd=d: g.get_training_readiness(dd)),
        _readiness_populated,
    )
    _probe(
        "daily_summary",
        lambda d: _call(lambda g, dd=d: g.get_stats(dd)),
        lambda data: isinstance(data, dict) and data.get("totalSteps") is not None,
    )

    latest_activity_raw = _safe_call(lambda g: g.get_activities(0, 1))
    if isinstance(latest_activity_raw, list) and latest_activity_raw:
        start = latest_activity_raw[0].get("startTimeLocal", "")
        out["activity"] = start.split(" ")[0] if start else None
    else:
        out["activity"] = None

    return {"as_of": _today(), "last_populated": out}
