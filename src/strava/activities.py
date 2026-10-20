"""Bounded activity retrieval and deterministic analysis, without telemetry prefetch."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from .. import cache
from . import client

FIELDS = {
    "id": "id",
    "name": "name",
    "sport": "sport_type",
    "start_local": "start_date_local",
    "start_utc": "start_date",
    "distance_m": "distance",
    "moving_time_s": "moving_time",
    "elapsed_time_s": "elapsed_time",
    "elevation_gain_m": "total_elevation_gain",
    "avg_hr_bpm": "average_heartrate",
    "max_hr_bpm": "max_heartrate",
    "avg_cadence": "average_cadence",
    "avg_power_w": "average_watts",
    "max_power_w": "max_watts",
    "weighted_power_w": "weighted_average_watts",
    "device_watts": "device_watts",
    "trainer": "trainer",
    "manual": "manual",
}
STREAMS = {
    "time",
    "distance",
    "heartrate",
    "cadence",
    "watts",
    "altitude",
    "velocity_smooth",
    "moving",
    "grade_smooth",
}


def window(start_date: str | None, end_date: str | None) -> tuple[date, date]:
    today = date.today()
    start = date.fromisoformat(start_date) if start_date else today.replace(month=1, day=1)
    end = date.fromisoformat(end_date) if end_date else today
    if end < start or (end - start).days > 365:
        raise ValueError("Use an inclusive date range of at most 366 days, end >= start.")
    return start, end


def summary(raw: dict) -> dict:
    result = {key: raw.get(source) for key, source in FIELDS.items()}
    result["sport"] = result["sport"] or raw.get("type")
    distance, moving = result["distance_m"], result["moving_time_s"]
    result["pace_s_per_km"] = (
        round(moving * 1000 / distance, 2) if distance and moving is not None else None
    )
    return result


def history(
    start_date: str | None = None, end_date: str | None = None, refresh: bool = False
) -> dict:
    start, end = window(start_date, end_date)

    def fetch() -> dict:
        after = datetime.combine(start - timedelta(days=2), datetime.min.time(), UTC)
        before = datetime.combine(end + timedelta(days=2), datetime.max.time(), UTC)
        rows: dict[int, dict] = {}
        complete = False
        pages = 0
        for page in range(1, 11):
            raw = client._get(
                "/athlete/activities",
                {
                    "after": int(after.timestamp()),
                    "before": int(before.timestamp()),
                    "per_page": 200,
                    "page": page,
                },
            )
            pages = page
            for activity in raw:
                local = (activity.get("start_date_local") or "")[:10]
                if local and start.isoformat() <= local <= end.isoformat():
                    rows[activity["id"]] = summary(activity)
            if len(raw) < 200:
                complete = True
                break
        return {
            "start_date": str(start),
            "end_date": str(end),
            "complete": complete,
            "api_pages": pages,
            "activity_count": len(rows),
            "warning": None
            if complete
            else ("Reached 10 API pages. Results are partial; query shorter date ranges."),
            "activities": sorted(rows.values(), key=lambda a: a["start_local"], reverse=True),
        }

    return cache.get_or_fetch(
        "activity_list", "strava_history_v1", {"start": str(start), "end": str(end)}, fetch, refresh
    )


def cohort(
    data: dict,
    sport: str | None = None,
    min_distance_km: float | None = None,
    max_distance_km: float | None = None,
    min_duration_s: int | None = None,
    max_duration_s: int | None = None,
    min_hr_bpm: float | None = None,
    max_hr_bpm: float | None = None,
) -> list[dict]:
    for low, high in (
        (min_distance_km, max_distance_km),
        (min_duration_s, max_duration_s),
        (min_hr_bpm, max_hr_bpm),
    ):
        if (low is not None and low < 0) or (high is not None and high < 0):
            raise ValueError("Filter bounds must be nonnegative.")
        if low is not None and high is not None and low > high:
            raise ValueError("Minimum filter must not exceed maximum.")
    rows = data["activities"]
    if sport:
        rows = [a for a in rows if (a["sport"] or "").casefold() == sport.casefold()]
    for key, low, high, scale in (
        ("distance_m", min_distance_km, max_distance_km, 1000),
        ("moving_time_s", min_duration_s, max_duration_s, 1),
        ("avg_hr_bpm", min_hr_bpm, max_hr_bpm, 1),
    ):
        if low is not None:
            rows = [a for a in rows if a[key] is not None and a[key] >= low * scale]
        if high is not None:
            rows = [a for a in rows if a[key] is not None and a[key] <= high * scale]
    return rows


def coverage(data: dict) -> dict:
    return {k: data[k] for k in ("start_date", "end_date", "complete", "warning")}


def search(
    start_date: str | None = None,
    end_date: str | None = None,
    sport: str | None = None,
    min_distance_km: float | None = None,
    max_distance_km: float | None = None,
    min_duration_s: int | None = None,
    max_duration_s: int | None = None,
    offset: int = 0,
    limit: int = 20,
    refresh: bool = False,
) -> dict:
    if offset < 0 or not 1 <= limit <= 50:
        raise ValueError("offset >= 0; limit must be 1..50.")
    data = history(start_date, end_date, refresh)
    rows = cohort(data, sport, min_distance_km, max_distance_km, min_duration_s, max_duration_s)
    stop = offset + limit
    return {
        **coverage(data),
        "matching_count": len(rows),
        "offset": offset,
        "next_offset": stop if stop < len(rows) else None,
        "activities": rows[offset:stop],
    }


def details(
    activity_id: int,
    section: str = "overview",
    offset: int = 0,
    limit: int = 50,
    refresh: bool = False,
) -> dict:
    if activity_id <= 0 or offset < 0 or not 1 <= limit <= 100:
        raise ValueError("Positive activity ID, offset >= 0, limit 1..100 required.")
    sections = {"splits": "splits_metric", "laps": "laps", "best_efforts": "best_efforts"}
    if section not in {"overview", *sections}:
        raise ValueError("section must be overview, splits, laps, or best_efforts.")

    def fetch() -> dict:
        raw = client._get(f"/activities/{activity_id}", {"include_all_efforts": False})
        result = {
            "activity": summary(raw),
            "calories": raw.get("calories"),
            "kilojoules": raw.get("kilojoules"),
            "device_name": raw.get("device_name"),
        }
        fields = (
            "name",
            "split",
            "lap_index",
            "distance",
            "elapsed_time",
            "moving_time",
            "average_speed",
            "average_heartrate",
            "max_heartrate",
            "average_cadence",
            "average_watts",
            "max_watts",
            "total_elevation_gain",
            "elevation_difference",
            "start_index",
            "end_index",
            "pr_rank",
            "achievement_rank",
        )
        for public, native in sections.items():
            result[public] = [
                {key: row[key] for key in fields if key in row} for row in raw.get(native, [])
            ]
        return result

    data = cache.get_or_fetch(
        "activity_detail", "strava_detail_v1", {"id": activity_id}, fetch, refresh
    )
    result = {
        "activity": data["activity"],
        "calories": data["calories"],
        "kilojoules": data["kilojoules"],
        "device_name": data["device_name"],
        "section_counts": {k: len(data[k]) for k in sections},
        "units": "Native Strava: distance/elevation metres, time seconds, speed m/s, "
        "HR bpm, power watts; cadence as recorded (sport dependent). "
        "Metric splits may end with a partial kilometre; laps are recorded laps.",
    }
    if section != "overview":
        rows = data[section]
        result.update(
            section=section,
            items=rows[offset : offset + limit],
            offset=offset,
            next_offset=offset + limit if offset + limit < len(rows) else None,
        )
    return result


def streams(
    activity_id: int,
    metrics: str = "time,distance,heartrate,velocity_smooth",
    offset: int = 0,
    limit: int = 200,
    start_time_s: float | None = None,
    end_time_s: float | None = None,
    start_distance_km: float | None = None,
    end_distance_km: float | None = None,
    refresh: bool = False,
) -> dict:
    selected = set(metrics.split(","))
    if not selected or not selected <= STREAMS:
        raise ValueError(f"Choose comma-separated metrics from {', '.join(sorted(STREAMS))}.")
    if activity_id <= 0 or offset < 0 or not 1 <= limit <= 1000:
        raise ValueError("Positive activity ID, offset >= 0, limit 1..1000 required.")
    for low, high in ((start_time_s, end_time_s), (start_distance_km, end_distance_km)):
        if (low is not None and low < 0) or (high is not None and high < 0):
            raise ValueError("Stream bounds must be nonnegative.")
        if low is not None and high is not None and low > high:
            raise ValueError("Stream start must not exceed end.")
    requested = selected | {"time", "distance"}
    keys = ",".join(sorted(requested))
    raw = cache.get_or_fetch(
        "strava_streams",
        "strava_streams_v1",
        {"id": activity_id, "keys": keys},
        lambda: client._get(
            f"/activities/{activity_id}/streams", {"keys": keys, "key_by_type": True}
        ),
        refresh,
    )
    if not isinstance(raw, dict):
        raise ValueError("Strava returned an unexpected stream format.")
    channels = {k: v.get("data", []) for k, v in raw.items() if k in requested}
    lengths = {len(values) for values in channels.values()}
    if len(lengths) > 1:
        raise ValueError("Strava stream lengths differ; refusing to misalign samples.")
    count = next(iter(lengths), 0)
    if any(v.get("original_size", count) != count for v in raw.values()):
        raise ValueError("Strava returned resampled streams; full-resolution samples unavailable.")
    indices = list(range(count))
    for key, low, high, scale in (
        ("time", start_time_s, end_time_s, 1),
        ("distance", start_distance_km, end_distance_km, 1000),
    ):
        if low is not None or high is not None:
            if key not in channels:
                raise ValueError(f"Cannot filter by {key}: stream unavailable.")
            indices = [
                i
                for i in indices
                if channels[key][i] is not None
                and (low is None or channels[key][i] >= low * scale)
                and (high is None or channels[key][i] <= high * scale)
            ]
    page = indices[offset : offset + limit]
    return {
        "activity_id": activity_id,
        "original_sample_count": count,
        "matching_sample_count": len(indices),
        "returned_sample_count": len(page),
        "sample_indices": page,
        "offset": offset,
        "next_offset": offset + limit if offset + limit < len(indices) else None,
        "missing_metrics": sorted(requested - channels.keys()),
        "units": "time seconds since start; distance/altitude metres; velocity_smooth m/s; "
        "heartrate bpm; watts W; cadence as recorded; grade_smooth percent.",
        "sampling": "Original aligned samples, no client resampling. Intervals may vary.",
        "data": {key: [values[i] for i in page] for key, values in channels.items()},
    }


def aggregate(rows: list[dict]) -> dict:
    result: dict[str, Any] = {"activity_count": len(rows)}
    measured = {}
    for field in ("distance_m", "moving_time_s", "elapsed_time_s", "elevation_gain_m"):
        values = [a[field] for a in rows if a[field] is not None]
        result[field] = round(sum(values), 2) if values or not rows else None
        measured[field] = len(values)
    paced = [a for a in rows if a["distance_m"] and a["moving_time_s"] is not None]
    distance = sum(a["distance_m"] for a in paced)
    sports = {a["sport"] for a in rows}
    result["pace_s_per_km"] = (
        round(sum(a["moving_time_s"] for a in paced) * 1000 / distance, 2)
        if distance and len(sports) == 1
        else None
    )
    hr = [a for a in rows if a["avg_hr_bpm"] is not None and a["moving_time_s"]]
    result["avg_hr_bpm"] = (
        round(
            sum(a["avg_hr_bpm"] * a["moving_time_s"] for a in hr)
            / sum(a["moving_time_s"] for a in hr),
            2,
        )
        if hr
        else None
    )
    measured["avg_hr_bpm"] = len(hr)
    result["measured_activity_counts"] = measured
    return result


def training_summary(
    start_date: str | None = None,
    end_date: str | None = None,
    period: str = "month",
    sport: str | None = None,
    refresh: bool = False,
    min_distance_km: float | None = None,
    max_distance_km: float | None = None,
    min_hr_bpm: float | None = None,
    max_hr_bpm: float | None = None,
) -> dict:
    if period not in {"week", "month"}:
        raise ValueError("period must be week or month.")
    data = history(start_date, end_date, refresh)
    rows = cohort(
        data, sport, min_distance_km, max_distance_km, min_hr_bpm=min_hr_bpm, max_hr_bpm=max_hr_bpm
    )

    def key(day: date) -> str:
        year, week, _ = day.isocalendar()
        return f"{year}-W{week:02d}" if period == "week" else day.strftime("%Y-%m")

    buckets: dict[str, list] = {}
    day = date.fromisoformat(data["start_date"])
    while day <= date.fromisoformat(data["end_date"]):
        buckets.setdefault(key(day), [])
        day += timedelta(days=1)
    for activity in rows:
        buckets[key(date.fromisoformat(activity["start_local"][:10]))].append(activity)
    return {
        **coverage(data),
        "period": period,
        "sport": sport,
        "totals": aggregate(rows),
        "periods": [{"period": k, **aggregate(v)} for k, v in buckets.items()],
        "interpretation": "Partial boundary periods use only requested dates. HR is "
        "moving-time weighted; pace is total moving time / distance for measured activities "
        "of a single sport. Compare similar distance, terrain and conditions; these summaries "
        "do not establish fitness changes or causality.",
    }


def compare(activity_ids: list[int], refresh: bool = False) -> dict:
    ids = list(dict.fromkeys(activity_ids))
    if not 2 <= len(ids) <= 10 or any(i <= 0 for i in ids):
        raise ValueError("Provide 2..10 distinct positive activity IDs.")
    rows = [details(i, refresh=refresh)["activity"] for i in ids]
    baseline = rows[0]
    differences = []
    for row in rows[1:]:
        delta = {}
        for field in (
            "distance_m",
            "moving_time_s",
            "pace_s_per_km",
            "avg_hr_bpm",
            "elevation_gain_m",
            "avg_power_w",
        ):
            left, right = baseline[field], row[field]
            delta[field] = (
                round(right - left, 2) if left is not None and right is not None else None
            )
        differences.append({"activity_id": row["id"], "minus_first_activity": delta})
    return {
        "activities": rows,
        "differences": differences,
        "interpretation": "Negative pace delta means faster. Compare within the same sport; "
        "distance, terrain, weather, stops and sensor availability can explain differences. "
        "No causal or fitness inference is calculated. Use training_summary with distance "
        "and HR bounds for monthly or weekly cohorts.",
    }
