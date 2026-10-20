import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import httpx

from src import cache
from src.strava import activities as a
from src.strava import client


def raw(i=1, day="2026-01-01", **values):
    return {
        "id": i,
        "sport_type": "Run",
        "start_date_local": f"{day}T23:30:00Z",
        "distance": 1000.5,
        "moving_time": 300,
        "elapsed_time": 330,
        "total_elevation_gain": 0,
        **values,
    }


class ActivitiesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = patch("src.config.database_path", return_value=Path(self.temp.name) / "test.db")
        self.db.start()

    def tearDown(self):
        self.db.stop()
        self.temp.cleanup()

    def test_history_pagination_dates_cache_and_refresh(self):
        pages = [
            [raw(i) for i in range(200)],
            [raw(201), raw(202, "2025-12-31"), raw(203, "2026-01-02")],
        ]
        with patch.object(client, "_get", side_effect=pages + pages) as get:
            result = a.search("2026-01-01", "2026-01-01", offset=190, limit=20)
            self.assertTrue(result["complete"])
            self.assertEqual(result["matching_count"], 201)
            self.assertEqual(len(result["activities"]), 11)
            self.assertIsNone(result["next_offset"])
            a.training_summary("2026-01-01", "2026-01-01")
            self.assertEqual(get.call_count, 2)
            a.search("2026-01-01", "2026-01-01", refresh=True)
            self.assertEqual(get.call_count, 4)

    def test_page_cap_explicitly_incomplete(self):
        with patch.object(client, "_get", return_value=[raw(i) for i in range(200)]):
            result = a.training_summary("2026-01-01", "2026-12-31")
        self.assertFalse(result["complete"])
        self.assertIn("partial", result["warning"])

    def test_empty_periods_null_zero_and_weighted_pace(self):
        rows = [
            raw(),
            raw(2, distance=2000, moving_time=1000),
            raw(3, "2026-03-01", distance=None, moving_time=None),
        ]
        with patch.object(client, "_get", return_value=rows):
            result = a.training_summary("2026-01-01", "2026-03-31", sport="Run")
        self.assertEqual(len(result["periods"]), 3)
        self.assertEqual(result["periods"][1]["distance_m"], 0)
        self.assertIsNone(result["periods"][2]["distance_m"])
        self.assertEqual(result["totals"]["pace_s_per_km"], round(1300 * 1000 / 3000.5, 2))
        self.assertEqual(result["totals"]["measured_activity_counts"]["distance_m"], 2)
        self.assertIsNone(result["totals"]["avg_hr_bpm"])

    def test_leap_year_and_iso_week_boundaries(self):
        with patch.object(client, "_get", return_value=[]):
            result = a.training_summary("2024-01-01", "2024-12-31", "week")
        self.assertEqual(len(result["periods"]), 53)
        self.assertEqual(result["periods"][-1]["period"], "2025-W01")
        with self.assertRaises(ValueError):
            a.window("2024-01-01", "2025-01-01")

    def test_details_native_partial_split_and_paging(self):
        payload = {
            **raw(),
            "splits_metric": [{"split": 1, "distance": 1000}, {"split": 2, "distance": 43.4}],
            "laps": [{"distance": 1609.34, "average_watts": 0}],
        }
        with patch.object(client, "_get", return_value=payload) as get:
            result = a.details(1, "splits", limit=1)
            self.assertEqual(result["next_offset"], 1)
            last = a.details(1, "splits", offset=1)
            self.assertEqual(last["items"][0]["distance"], 43.4)
            self.assertEqual(a.details(1, "laps")["items"][0]["distance"], 1609.34)
            self.assertEqual(get.call_count, 1)
            self.assertIsNone(result["activity"]["avg_hr_bpm"])

    def test_stream_alignment_filter_and_tail(self):
        raw_streams = {
            k: {"data": list(v), "original_size": 1003}
            for k, v in {
                "time": range(1003),
                "distance": range(1003),
                "heartrate": range(1003),
            }.items()
        }
        with patch.object(client, "_get", return_value=raw_streams) as get:
            first = a.streams(1, "heartrate", limit=1000)
            last = a.streams(1, "heartrate", offset=first["next_offset"], limit=1000)
            self.assertEqual(last["sample_indices"], [1000, 1001, 1002])
            self.assertEqual(last["data"]["heartrate"], last["data"]["time"])
            segment = a.streams(1, "heartrate", start_distance_km=0.999, end_time_s=1001)
            self.assertEqual(segment["sample_indices"], [999, 1000, 1001])
            self.assertEqual(get.call_count, 1)
            self.assertLess(len(json.dumps(first)), 25000)

    def test_stream_rejects_misalignment_and_resampling(self):
        with patch.object(
            client, "_get", return_value={"time": {"data": [1, 2]}, "heartrate": {"data": [100]}}
        ):
            with self.assertRaisesRegex(ValueError, "lengths"):
                a.streams(1)
        with patch.object(
            client, "_get", return_value={"time": {"data": [1, 2], "original_size": 100}}
        ):
            with self.assertRaisesRegex(ValueError, "resampled"):
                a.streams(2)

    def test_filters_and_comparison_missing_metrics(self):
        with patch.object(client, "_get", return_value=[raw(), raw(2, sport_type="Ride")]):
            result = a.search("2026-01-01", "2026-01-01", sport="run", min_distance_km=1)
        self.assertEqual(result["matching_count"], 1)
        with patch.object(client, "_get", side_effect=[raw(), raw(2, moving_time=250)]):
            result = a.compare([1, 2])
        delta = result["differences"][0]["minus_first_activity"]
        self.assertLess(delta["pace_s_per_km"], 0)
        self.assertIsNone(delta["avg_hr_bpm"])
        with self.assertRaises(ValueError):
            a.search(limit=51)
        with self.assertRaises(ValueError):
            a.cohort({"activities": []}, min_distance_km=10, max_distance_km=1)

    def test_expired_cache_purged(self):
        with patch("src.cache.time.time", return_value=100):
            cache.get_or_fetch("strava_streams", "old", {}, lambda: [1])
        with patch("src.cache.time.time", return_value=10000):
            cache.get_or_fetch("activity_list", "new", {}, lambda: [])
        self.assertNotIn("strava_streams", cache.stats())

    def test_rate_limit_actionable_and_no_retry(self):
        response = httpx.Response(429, request=httpx.Request("GET", "https://example.com"))
        with (
            patch.object(client, "_access_token", return_value="test"),
            patch.object(client._http, "get", return_value=response) as get,
        ):
            with self.assertRaisesRegex(RuntimeError, "rate limit"):
                client._get("/athlete")
            get.assert_called_once()

    def test_refresh_token_rotation_serialized(self):
        saved = {"expires_at": 0, "access_token": "old"}

        def refresh(tokens):
            saved.update(expires_at=10**12, access_token="new")
            return saved.copy()

        with (
            patch.object(client, "_load_tokens", side_effect=lambda: saved.copy()),
            patch.object(client, "_refresh", side_effect=refresh) as refresh_mock,
        ):
            with ThreadPoolExecutor(max_workers=4) as pool:
                result = list(pool.map(lambda _: client._access_token(), range(4)))
        self.assertEqual(result, ["new"] * 4)
        self.assertEqual(refresh_mock.call_count, 1)


if __name__ == "__main__":
    unittest.main()
