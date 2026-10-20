"""Compact Strava history, detail, telemetry and analysis tools."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from .. import cache
from . import activities, client


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
            lambda: client.weekly_totals(weeks, refresh=refresh),
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

    @mcp.tool
    def strava_search_activities(
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
    ) -> dict[str, Any]:
        """Search activity history by inclusive local dates (default year to date, max 366 days).

        Exact sport names e.g. Run, Ride. Duration bounds use moving seconds.
        Returns compact summaries and IDs, at most 50 per call. Follow next_offset.
        Check complete before claiming whole-year totals; if false, split the date range.
        """
        return activities.search(
            start_date,
            end_date,
            sport,
            min_distance_km,
            max_distance_km,
            min_duration_s,
            max_duration_s,
            offset,
            limit,
            refresh,
        )

    @mcp.tool
    def strava_activity_details(
        activity_id: int,
        section: str = "overview",
        offset: int = 0,
        limit: int = 50,
        refresh: bool = False,
    ) -> dict[str, Any]:
        """Read one activity, including metric splits, recorded laps, or best efforts.

        section: overview, splits, laps, best_efforts. Overview reports available counts.
        Sections are paged (limit <= 100). Native units are documented in the result.
        Recorded laps are not necessarily kilometres. Missing sensor metrics stay null.
        """
        return activities.details(activity_id, section, offset, limit, refresh)

    @mcp.tool
    def strava_activity_streams(
        activity_id: int,
        metrics: str = "time,distance,heartrate,velocity_smooth",
        offset: int = 0,
        limit: int = 200,
        start_time_s: float | None = None,
        end_time_s: float | None = None,
        start_distance_km: float | None = None,
        end_distance_km: float | None = None,
        refresh: bool = False,
    ) -> dict[str, Any]:
        """Read aligned original telemetry, bounded to a time/distance section or page.

        Metrics: time,distance,heartrate,velocity_smooth,altitude,cadence,watts,moving,
        grade_smooth. Time/distance always included. Max 1000 samples per page; follow
        next_offset with identical filters to retrieve every sample. No downsampling.
        Use activity details for splits first; avoid downloading whole streams for summaries.
        """
        return activities.streams(
            activity_id,
            metrics,
            offset,
            limit,
            start_time_s,
            end_time_s,
            start_distance_km,
            end_distance_km,
            refresh,
        )

    @mcp.tool
    def strava_training_summary(
        start_date: str | None = None,
        end_date: str | None = None,
        period: str = "month",
        sport: str | None = None,
        min_distance_km: float | None = None,
        max_distance_km: float | None = None,
        min_hr_bpm: float | None = None,
        max_hr_bpm: float | None = None,
        refresh: bool = False,
    ) -> dict[str, Any]:
        """Weekly/monthly training totals and pace/HR trends across up to 366 days.

        Defaults year to date. Includes empty periods and metric coverage counts.
        Filter exact sport and similar distance/average-HR ranges for comparable cohorts.
        Uses summary cache only, no telemetry downloads. Check complete before conclusions.
        """
        return activities.training_summary(
            start_date,
            end_date,
            period,
            sport,
            refresh,
            min_distance_km,
            max_distance_km,
            min_hr_bpm,
            max_hr_bpm,
        )

    @mcp.tool
    def strava_compare_activities(activity_ids: list[int], refresh: bool = False) -> dict[str, Any]:
        """Compare 2..10 selected activity IDs: distance, pace, HR, elevation and power.

        Returns exact deltas from the first activity. Search for IDs first. Uses cached
        details; retrieve splits separately only if needed. No causal fitness inference.
        """
        return activities.compare(activity_ids, refresh)
