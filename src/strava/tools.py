"""Strava MCP tool registrations."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from .. import cache
from . import client


def register(mcp: FastMCP) -> None:
    @mcp.tool
    def strava_recent_activities(limit: int = 10, refresh: bool = False) -> list[dict[str, Any]]:
        """Tier 1: Compact list of recent Strava activities.

        Returns per activity: id, name, type, start, distance_km, moving_time_s,
        avg_pace_s_per_km, elevation_gain_m, avg_hr, max_hr.
        """
        return cache.get_or_fetch(
            "activity_list",
            "strava_recent",
            {"limit": limit},
            lambda: client.recent_activities(limit),
            refresh=refresh,
        )

    @mcp.tool
    def strava_activity_details(activity_id: int, refresh: bool = False) -> dict[str, Any]:
        """Tier 2: Rich details for one Strava activity — splits, laps, HR, gear, calories."""
        return cache.get_or_fetch(
            "activity_detail",
            "strava_detail",
            {"id": activity_id},
            lambda: client.activity_details(activity_id),
            refresh=refresh,
        )

    @mcp.tool
    def strava_activity_streams(
        activity_id: int, detail_level: str = "summary", refresh: bool = False
    ) -> dict[str, Any]:
        """Tier 3: Time-series streams for one activity.

        `detail_level="summary"` (default) downsamples to ~500 points.
        `detail_level="full"` returns every sample (50-500KB).
        """
        return cache.get_or_fetch(
            "activity_stream",
            "strava_stream",
            {"id": activity_id, "detail": detail_level},
            lambda: client.activity_streams(activity_id, detail_level),
            refresh=refresh,
        )

    @mcp.tool
    def strava_athlete_stats(refresh: bool = False) -> dict[str, Any]:
        """All-time, YTD, and recent (4-week) totals for run and ride."""
        return cache.get_or_fetch(
            "athlete_stats",
            "strava_athlete_stats",
            {},
            client.athlete_stats,
            refresh=refresh,
        )

    @mcp.tool
    def strava_weekly_totals(weeks: int = 4, refresh: bool = False) -> list[dict[str, Any]]:
        """Distance, moving time, and elevation per ISO week, most recent first."""
        return cache.get_or_fetch(
            "athlete_stats",
            "strava_weekly",
            {"weeks": weeks},
            lambda: client.weekly_totals(weeks),
            refresh=refresh,
        )

    @mcp.tool
    def strava_starred_segments(refresh: bool = False) -> list[dict[str, Any]]:
        """List your starred segments with distance, grade, and PR time."""
        return cache.get_or_fetch(
            "athlete_stats",
            "strava_segments",
            {},
            client.starred_segments,
            refresh=refresh,
        )
