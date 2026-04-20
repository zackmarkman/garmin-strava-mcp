"""Direct probe of raw garminconnect responses for yesterday.

If these return non-null data, our client's today-only hardcoding is the issue
(fix: add date params). If they return null for yesterday too, Garmin simply
doesn't have that metric and our shaping is fine.

Run: uv run python scripts/smoke_probe_yesterday.py
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.garmin.client import _call  # noqa: E402


def _probe(label: str, fn):
    print(f"\n=== {label} ===")
    try:
        data = _call(fn)
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {type(exc).__name__}: {exc}")
        return
    preview = json.dumps(data, default=str, indent=2)
    if len(preview) > 1500:
        preview = preview[:1500] + "\n... (truncated)"
    print(preview)


def main() -> None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    two_days_ago = (date.today() - timedelta(days=2)).isoformat()

    _probe(
        f"get_hrv_data({yesterday})",
        lambda g, d=yesterday: g.get_hrv_data(d),
    )
    _probe(
        f"get_max_metrics({yesterday})",
        lambda g, d=yesterday: g.get_max_metrics(d),
    )
    _probe(
        f"get_training_status({yesterday})",
        lambda g, d=yesterday: g.get_training_status(d),
    )
    _probe(
        f"get_training_readiness({yesterday})",
        lambda g, d=yesterday: g.get_training_readiness(d),
    )
    _probe(
        f"get_training_readiness({two_days_ago})",
        lambda g, d=two_days_ago: g.get_training_readiness(d),
    )


if __name__ == "__main__":
    main()
