"""Smoke test Garmin + Strava clients against live APIs.

Calls a representative sample of functions on both clients to verify:
  - tokens load and decrypt from SQLite
  - auto-refresh works
  - response-shaping logic handles real payloads

Run: uv run python scripts/smoke_test.py
"""

from __future__ import annotations

import json
import sys
import traceback
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.garmin import client as garmin  # noqa: E402
from src.strava import client as strava  # noqa: E402


def _run(label: str, fn):
    print(f"\n=== {label} ===")
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return None
    preview = json.dumps(result, default=str, indent=2)
    if len(preview) > 800:
        preview = preview[:800] + "\n... (truncated)"
    print(preview)
    return result


def main() -> None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    _run("Strava: latest_activity", strava.latest_activity)
    _run("Strava: weekly_totals(4)", lambda: strava.weekly_totals(weeks=4))

    _run("Garmin: latest_activity", garmin.latest_activity)
    _run("Garmin: recent_activities(5)", lambda: garmin.recent_activities(limit=5))
    _run(f"Garmin: daily_summary({yesterday})", lambda: garmin.daily_summary(yesterday))
    _run(f"Garmin: sleep({yesterday})", lambda: garmin.sleep(yesterday))
    _run("Garmin: body_battery(days=3)", lambda: garmin.body_battery(days=3))
    _run("Garmin: hrv", garmin.hrv)
    _run("Garmin: training_readiness", garmin.training_readiness)
    _run("Garmin: training_load", garmin.training_load)
    _run("Garmin: vo2_max", garmin.vo2_max)
    _run("Garmin: recovery_time", garmin.recovery_time)


if __name__ == "__main__":
    main()
