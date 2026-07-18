"""Strava MCP tool registrations.

Deliberately thin: the official Strava MCP (hosted by Strava) covers
per-activity detail, streams, zones, and gear far better than we can.
We only expose the aggregates it lacks — weekly totals, all-time stats,
and starred segments. Garmin is this server's real job.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from .. import cache
from . import client


def register(mcp: FastMCP) -> None:
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
