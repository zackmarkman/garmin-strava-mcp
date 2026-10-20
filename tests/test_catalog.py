import unittest

from src.server import build_mcp


class CatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_tools_registered_with_refresh_and_original_tools_preserved(self):
        tools = await build_mcp().list_tools()
        catalog = {tool.name: tool for tool in tools}
        expected = {
            "strava_search_activities",
            "strava_activity_details",
            "strava_activity_streams",
            "strava_training_summary",
            "strava_compare_activities",
            "strava_weekly_totals",
            "strava_athlete_stats",
            "strava_starred_segments",
            "get_server_status",
            "garmin_sleep",
        }
        self.assertTrue(expected <= catalog.keys())
        for name in expected - {"get_server_status"}:
            self.assertIn("refresh", catalog[name].parameters["properties"])
