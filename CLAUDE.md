# garmin-strava-mcp

Self-hosted MCP server (Python/FastMCP) bridging Garmin Connect and Strava to Claude.
Single-user, token-auth, deployed to Fly.io. Full plan in `docs/plan.md`.

## Layout

- `src/server.py` — FastMCP entry point and HTTP app.
- `src/auth.py` — `?token=` middleware.
- `src/storage.py` — SQLite + Fernet-encrypted OAuth token storage.
- `src/cache.py` — Per-tool TTL cache (SQLite-backed).
- `src/sync.py` — `/sync` HTTP endpoint and `sync_latest` tool.
- `src/garmin/{client,tools}.py` — Garmin Connect client + MCP tools.
- `src/strava/{client,tools}.py` — Strava client + MCP tools.
- `scripts/` — one-time auth bootstraps and token generation.

## Commands

```bash
uv sync                                  # install deps
uv run python scripts/generate_token.py  # SERVER_TOKEN + FERNET_KEY
uv run python scripts/setup_strava_auth.py
uv run python scripts/setup_garmin_auth.py
uv run python -m src.server              # run locally on :8000
```

## Conventions

- Every tool accepts `refresh: bool = False` to bypass cache.
- Cache TTLs live in `src/cache.py` keyed by tool name — see plan for table.
- Garmin tools must catch auth errors and return the actionable message
  "Garmin session expired — re-run setup_garmin_auth.py to reconnect."
- Never log OAuth tokens or raw credentials.

## Garmin auth caveat

Per plan: `garth` was deprecated 2026-03-28. We try `garth` first in
`setup_garmin_auth.py`; if it fails, the script falls back to the browser-based
token bootstrap inspired by `garmin-givemydata`.
