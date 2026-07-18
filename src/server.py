"""FastMCP entry point. Serves the MCP endpoint plus /sync and /health."""

from __future__ import annotations

from fastmcp import FastMCP
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import cache, config
from .auth import TokenAuthMiddleware
from .garmin import tools as garmin_tools
from .strava import tools as strava_tools
from .sync import run_sync


def build_mcp() -> FastMCP:
    mcp = FastMCP(name="garmin-strava")

    garmin_tools.register(mcp)
    strava_tools.register(mcp)

    @mcp.tool
    def sync_latest() -> dict:
        """Clear the activity cache and fetch the most recent workout from Garmin and Strava.

        Use this after you finish a workout and sync your watch.
        Returns the latest activity found in each service plus any errors encountered.
        """
        return run_sync()

    @mcp.tool
    def get_server_status() -> dict:
        """Report whether Garmin and Strava connections are alive, plus cache stats and Garmin session age. If `garmin_session.warning` is present, surface it to the user — the session hard-expires ~90 days after authorization."""
        from datetime import date, timedelta

        from . import storage
        from .garmin.client import latest_activity as garmin_latest
        from .strava.client import latest_activity as strava_latest

        status = {"garmin": "unknown", "strava": "unknown"}
        for name, fn in (("garmin", garmin_latest), ("strava", strava_latest)):
            try:
                fn()
                status[name] = "ok"
            except NotImplementedError:
                status[name] = "not_implemented"
            except Exception as exc:  # noqa: BLE001
                status[name] = f"error: {exc}"

        # Garmin DI refresh tokens hard-expire ~90 days after authorization,
        # regardless of use. Warn from day 75 so re-auth happens before failure.
        garmin_session: dict = {}
        try:
            authorized_at = (storage.load_tokens("garmin") or {}).get("authorized_at")
            if authorized_at:
                auth_date = date.fromisoformat(authorized_at)
                age_days = (date.today() - auth_date).days
                expected_expiry = (auth_date + timedelta(days=90)).isoformat()
                garmin_session = {
                    "authorized_at": authorized_at,
                    "age_days": age_days,
                    "expected_expiry": expected_expiry,
                }
                if age_days >= 75:
                    garmin_session["warning"] = (
                        f"Garmin session is {age_days} days old and hard-expires "
                        f"around {expected_expiry}. Re-run scripts/setup_garmin_auth.py "
                        "and re-upload the DB (see DEPLOY.md) before then."
                    )
        except Exception:  # noqa: BLE001
            pass

        result = {"connections": status, "cache": cache.stats()}
        if garmin_session:
            result["garmin_session"] = garmin_session
        return result

    @mcp.custom_route("/sync", methods=["POST"])
    async def sync_route(_request: Request):
        return JSONResponse(run_sync())

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request):
        return JSONResponse({"ok": True})

    return mcp


def main() -> None:
    import uvicorn

    mcp = build_mcp()
    app = mcp.http_app(
        path="/mcp",
        middleware=[Middleware(TokenAuthMiddleware)],
    )
    uvicorn.run(app, host=config.host(), port=config.port())


if __name__ == "__main__":
    main()
