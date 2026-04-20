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
        """Report whether Garmin and Strava connections are alive, plus cache stats."""
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
        return {"connections": status, "cache": cache.stats()}

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
