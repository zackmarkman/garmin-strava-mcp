"""Garmin MCP tool registrations."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from .. import cache
from . import client


def register(mcp: FastMCP) -> None:
    @mcp.tool
    def garmin_daily_summary(date: str | None = None, refresh: bool = False) -> dict[str, Any]:
        """Daily steps, calories, active minutes, floors, distance. `date` is YYYY-MM-DD (today if omitted). Returns null values if the watch hasn't synced for that date yet — use garmin_data_freshness to check."""
        return cache.get_or_fetch(
            "wellness",
            "garmin_daily",
            {"date": date},
            lambda: client.daily_summary(date),
            refresh=refresh,
        )

    @mcp.tool
    def garmin_sleep(date: str | None = None, refresh: bool = False) -> dict[str, Any]:
        """Sleep stages, duration, sleep score, plus bed/wake times for the given date (default: today). `start_local`/`end_local` are ISO-8601 wall-clock strings in the user's local timezone (no offset suffix) — display them as-is, do NOT apply timezone conversion. Returns null if the watch hasn't synced — use garmin_data_freshness."""
        return cache.get_or_fetch(
            "sleep",
            "garmin_sleep",
            {"date": date},
            lambda: client.sleep(date),
            refresh=refresh,
        )

    @mcp.tool
    def garmin_body_battery(days: int = 1, refresh: bool = False) -> list[dict[str, Any]]:
        """Body battery charge/drain per day for the last `days` (1–7)."""
        return cache.get_or_fetch(
            "wellness",
            "garmin_body_battery",
            {"days": days},
            lambda: client.body_battery(days),
            refresh=refresh,
        )

    @mcp.tool
    def garmin_hrv(date: str | None = None, refresh: bool = False) -> dict[str, Any]:
        """HRV status, last-night average, weekly average, and baseline range. `date` is YYYY-MM-DD; if omitted, auto-falls back to the most recent populated day (up to 6 days back). All HRV values are in milliseconds."""
        return cache.get_or_fetch(
            "wellness",
            "garmin_hrv",
            {"date": date},
            lambda: client.hrv(date),
            refresh=refresh,
        )

    @mcp.tool
    def garmin_vo2_max(date: str | None = None, refresh: bool = False) -> dict[str, Any]:
        """VO2 max estimate for run and bike plus fitness age. `date` is YYYY-MM-DD; if omitted, auto-falls back to the most recent populated day."""
        return cache.get_or_fetch(
            "training",
            "garmin_vo2",
            {"date": date},
            lambda: client.vo2_max(date),
            refresh=refresh,
        )

    @mcp.tool
    def garmin_training_load(date: str | None = None, refresh: bool = False) -> dict[str, Any]:
        """Training status (productive/recovery/unproductive/etc.) and monthly aerobic/anaerobic load balance. `date` optional; auto-falls back to latest populated day."""
        return cache.get_or_fetch(
            "training",
            "garmin_training_load",
            {"date": date},
            lambda: client.training_load(date),
            refresh=refresh,
        )

    @mcp.tool
    def garmin_recovery_time(refresh: bool = False) -> dict[str, Any]:
        """Hours until fully recovered, sourced from Garmin's training-readiness algorithm (authoritative). Also includes the most recent activity for context. Auto-uses the latest populated readiness day."""
        return cache.get_or_fetch(
            "training",
            "garmin_recovery",
            {},
            client.recovery_time,
            refresh=refresh,
        )

    @mcp.tool
    def garmin_recent_activities(
        limit: int = 10, refresh: bool = False
    ) -> list[dict[str, Any]]:
        """Recent Garmin activities with distance, duration, pace, HR zones."""
        return cache.get_or_fetch(
            "activity_list",
            "garmin_recent",
            {"limit": limit},
            lambda: client.recent_activities(limit),
            refresh=refresh,
        )

    @mcp.tool
    def garmin_activity_details(
        activity_id: int, refresh: bool = False
    ) -> dict[str, Any]:
        """Detailed data for one Garmin activity: splits and HR-zone breakdown."""
        return cache.get_or_fetch(
            "activity_detail",
            "garmin_detail",
            {"id": activity_id},
            lambda: client.activity_details(activity_id),
            refresh=refresh,
        )

    @mcp.tool
    def garmin_stress(date: str | None = None, refresh: bool = False) -> dict[str, Any]:
        """All-day stress level: average, max, and percent time in rest."""
        return cache.get_or_fetch(
            "wellness",
            "garmin_stress",
            {"date": date},
            lambda: client.stress(date),
            refresh=refresh,
        )

    @mcp.tool
    def garmin_training_readiness(date: str | None = None, refresh: bool = False) -> dict[str, Any]:
        """Training readiness score (0–100), level, factor breakdown, recovery hours. `date` optional; auto-falls back to the latest populated day. Requires compatible Garmin device."""
        return cache.get_or_fetch(
            "training",
            "garmin_readiness",
            {"date": date},
            lambda: client.training_readiness(date),
            refresh=refresh,
        )

    @mcp.tool
    def garmin_data_freshness(refresh: bool = False) -> dict[str, Any]:
        """Most recent date with populated data for each Garmin metric (sleep, HRV, training readiness, daily summary, activity). Call this first if you suspect the watch hasn't synced today — it tells you what data is actually available before you interpret nulls."""
        return cache.get_or_fetch(
            "wellness",
            "garmin_freshness",
            {},
            client.data_freshness,
            refresh=refresh,
        )
