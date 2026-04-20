# Garmin + Strava MCP Server — Project Plan

## What This Is

A self-hosted MCP (Model Context Protocol) server in Python that connects Garmin Connect and Strava to Claude. Deployed to Fly.io with a public HTTPS URL, added as a Claude Connector so it works from the Claude app on any device — phone, web, desktop.

## Why

- Query recent training data and performance metrics conversationally
- Plan training blocks with real data context (mileage trends, recovery status, race calendar)
- Get feedback and insights on training load, sleep, HRV, pacing, and progression

## Architecture

```
Garmin Watch → Garmin Connect (cloud)
Runs/Rides   → Strava (cloud)
                      │
                      ▼
┌─────────────────────────────────┐
│  Self-Hosted MCP Server         │
│  (Python / FastMCP)             │
│                                 │
│  Garmin client  ← OAuth tokens  │
│  Strava client  ← OAuth tokens  │
│  Token auth     ← your secret   │
│  Encrypted storage (SQLite)     │
│                                 │
│  Deployed on Fly.io             │
│  HTTPS endpoint                 │
└─────────────────────────────────┘
         │ MCP over HTTPS
         ▼
   Claude Connector
   (phone, web, desktop)
```

## Tech Stack

- **Language:** Python 3.12
- **MCP framework:** FastMCP
- **Garmin API:** `garth` + `garminconnect` libraries (see auth caveat below)
- **Strava API:** Strava API v3, OAuth 2.0
- **Storage:** SQLite (single-user, encrypted tokens via Fernet)
- **Deployment:** Fly.io (Dockerfile + fly.toml)
- **Auth:** Single-user token — random 32-byte hex string appended as `?token=...` in the MCP URL

## Critical Caveat: Garmin Auth

The `garth` library (the standard Garmin auth method) was deprecated on March 28, 2026 after Garmin changed their SSO flow. `python-garminconnect` depends on `garth` and is also broken. The current workaround:

1. Use browser-based auth (Selenium/Chrome) to authenticate once locally — the `garmin-givemydata` project (https://github.com/nrvim/garmin-givemydata) has a working implementation of this.
2. Save the resulting OAuth tokens.
3. Have the MCP server use those saved tokens for ongoing API access, refreshing them on each request.

**Before building**, test whether `garth` works again. If it does, use it directly — it's simpler. If not, implement the browser-based token bootstrap flow.

## MCP Tools to Expose

### From Garmin (physiological / recovery data)

| Tool | Description |
|------|-------------|
| `get_daily_summary` | Steps, calories, active minutes, floors, distance |
| `get_sleep` | Sleep stages, duration, sleep score |
| `get_body_battery` | Current body battery level and trend |
| `get_hrv` | Heart rate variability status and 7-day trend |
| `get_vo2_max` | Current VO2 max estimate |
| `get_training_load` | 7-day training load and training status (productive, recovery, etc.) |
| `get_recovery_time` | Hours until recovered |
| `get_recent_activities` | Last N activities with type, distance, duration, avg/max HR, HR zones |
| `get_activity_details` | Detailed data for a specific activity (splits, HR zones, pace) |
| `get_stress` | All-day stress level |
| `get_training_readiness` | Training readiness score (requires compatible device) |

### From Strava (activity / performance data)

| Tool | Description |
|------|-------------|
| `get_recent_activities` | Last N activities with distance, pace, elevation, moving time |
| `get_activity_details` | Full activity with laps, splits, segment efforts |
| `get_activity_streams` | Time-series data: pace, HR, elevation, cadence, power |
| `get_athlete_stats` | All-time and YTD totals (distance, elevation, count) |
| `get_weekly_totals` | Distance, time, elevation gain for current and recent weeks |
| `get_segments` | Starred segments and recent segment efforts |

### Server Tools

| Tool | Description |
|------|-------------|
| `sync_latest` | Clears activity cache and fetches latest data from both Garmin and Strava. Use after logging a new workout. Returns a summary of the most recent activity found. |
| `get_server_status` | Reports whether Garmin and Strava connections are alive, cache stats, and last successful sync time. |

### Data Overlap Note

Garmin syncs activities to Strava, so basic activity data (distance, pace, HR) exists in both. Use Strava for activity queries and Garmin specifically for the physiological metrics that don't sync: training load, body battery, HRV, sleep, stress, VO2 max, training readiness.

## Auth & Security

- **Server auth:** Every MCP request must include `?token=YOUR_TOKEN` in the URL. Requests without a valid token are rejected.
- **Token generation:** On first setup, generate a random 32-byte hex token. Store it in a `.env` file and also use it when adding the connector to Claude.
- **Garmin/Strava credentials:** OAuth tokens encrypted at rest with Fernet symmetric encryption, stored in a local SQLite database. Credentials are never stored — only the resulting tokens.
- **HTTPS:** Fly.io provides automatic TLS. All traffic is encrypted.

## Caching Strategy

All API responses are cached in SQLite to reduce API calls, speed up responses, and protect against flaky upstream APIs. Every tool accepts an optional `refresh=true` parameter to bypass the cache on demand.

| Data type | Cache TTL | Rationale |
|---|---|---|
| Activity lists | 4 hours | Only changes when a new activity syncs |
| Activity details | 7 days | Immutable once synced |
| Activity streams | 7 days | Immutable once synced |
| Sleep | 6 hours | Finalizes in the morning |
| Body battery / stress / HRV | 1 hour | Updates throughout the day, but not decision-critical at minute resolution |
| VO2 max / training load / training status | 6 hours | Updates after activities, not continuously |
| Athlete stats / weekly totals | 4 hours | Only shifts when new activities sync |

### Manual Sync After Logging an Activity

After finishing a run or workout and syncing your watch, you can force the server to pull your latest data immediately instead of waiting for the cache to expire. Two ways to do this:

**From the terminal (anywhere with curl):**
```bash
curl -X POST "https://your-app.fly.dev/sync?token=YOUR_TOKEN"
```

**As a shortcut on your phone:** Create an iOS Shortcut or Android Tasker action that hits the same URL. One tap after you finish a workout and your data is fresh before you even open Claude.

The `/sync` endpoint clears the cache for activity lists, athlete stats, and weekly totals, then fetches the latest from both Garmin and Strava. It returns a summary of what it found (e.g., "Synced. Latest activity: Easy Run, 6.2 mi, 52:14").

There is also a `sync_latest` MCP tool exposed to Claude, so you can just say "sync my latest activity" in the chat and it does the same thing.

## Project Structure

```
garmin-strava-mcp/
├── CLAUDE.md                  # Project context for Claude Code
├── README.md
├── pyproject.toml             # Dependencies and project metadata
├── Dockerfile
├── fly.toml                   # Fly.io deployment config
├── .env.example               # Template for secrets
├── src/
│   ├── server.py              # FastMCP server entry point
│   ├── auth.py                # Token validation middleware
│   ├── storage.py             # SQLite + Fernet encrypted token storage
│   ├── cache.py               # Cache layer with per-data-type TTLs
│   ├── sync.py                # Manual sync endpoint and MCP tool
│   ├── garmin/
│   │   ├── client.py          # Garmin Connect API client
│   │   └── tools.py           # MCP tool definitions for Garmin
│   └── strava/
│       ├── client.py          # Strava API client
│       └── tools.py           # MCP tool definitions for Strava
└── scripts/
    ├── setup_garmin_auth.py   # One-time Garmin OAuth bootstrap
    ├── setup_strava_auth.py   # One-time Strava OAuth flow
    └── generate_token.py      # Generate server access token
```

## Setup Flow

### 1. Create Strava API App

Go to https://www.strava.com/settings/api and create an application. Note the Client ID and Client Secret.

### 2. Bootstrap Auth Tokens

```bash
# Generate your server access token
python scripts/generate_token.py

# Authenticate with Garmin (opens browser)
python scripts/setup_garmin_auth.py

# Authenticate with Strava (opens browser for OAuth)
python scripts/setup_strava_auth.py
```

### 3. Test Locally

```bash
# Run the MCP server locally
python src/server.py

# Test with MCP Inspector
npx @modelcontextprotocol/inspector http://localhost:8000/mcp/?token=YOUR_TOKEN
```

### 4. Deploy to Fly.io

```bash
# Install Fly CLI if needed
curl -L https://fly.io/install.sh | sh

# Launch the app
fly launch

# Set secrets
fly secrets set SERVER_TOKEN=your_token
fly secrets set FERNET_KEY=your_fernet_key
fly secrets set STRAVA_CLIENT_ID=your_id
fly secrets set STRAVA_CLIENT_SECRET=your_secret

# Deploy
fly deploy
```

### 5. Add to Claude

1. Open Claude app (phone or web)
2. Go to Settings → Connectors
3. Add Connector, paste: `https://your-app.fly.dev/mcp/?token=YOUR_TOKEN`
4. Name it "Garmin + Strava"
5. Set tool permissions to "Always allow"
6. Start chatting: "How did I sleep last night?" or "Show me my runs from the past two weeks"

## Practical Constraints & Mitigations

### 1. Strava Rate Limits

100 requests per 15 minutes, 1,000 per day. Mitigated by the caching layer — with 4-hour activity cache and 7-day detail cache, you'll rarely hit more than a handful of live API calls per session.

### 2. Context Window Management

Tools are designed in three tiers to keep payloads right-sized for the question being asked:

**Tier 1 — `get_recent_activities` (list view, ~1-2KB)**
Compact summaries for browsing. Returns: date, type, distance, pace, duration, avg HR per activity. Used for "show me my runs this week" or "how much did I run last month."

**Tier 2 — `get_activity_details` (single activity, ~5-10KB)**
The workhorse for "how did my last run go?" Returns rich, analysis-ready data for one activity:
- Per-km (or per-mile) splits with pace and avg HR per split
- Elevation profile: total gain/loss, steepest segment
- HR zone distribution (time and % in each zone)
- Cadence average
- Garmin extras when available: training effect, running power, performance condition

This is the tier that enables Claude to say: "You ran negative splits — first 5K at 5:12/km, last 5K at 4:48/km. HR spiked to 165 at km 8 where you gained 45m of elevation."

**Tier 3 — `get_activity_streams` (raw time-series, 50-500KB)**
Second-by-second GPS, HR, pace, elevation, cadence. Only called when explicitly needed: "plot my heart rate over the whole run" or "show me the GPS track." Truncates to 500 data points by default with a note that more exist. Pass `detail_level=full` for everything.

Claude naturally calls Tier 1 for list questions, Tier 2 for single-activity analysis, and Tier 3 only when raw data is explicitly requested.

### 3. Garmin Auth Fragility

Every Garmin API call is wrapped in error handling. Auth failures return a clear, actionable message ("Garmin session expired — re-run `setup_garmin_auth.py` to reconnect") instead of a stack trace or silent failure. The `get_server_status` tool reports whether Garmin and Strava connections are alive, so you can check health at any time by asking Claude "is my Garmin connected?"

### 4. Stale Data After a Workout

Use the `sync_latest` tool in chat ("sync my latest activity"), the `/sync` HTTP endpoint via curl, or an iOS Shortcut to force a refresh after syncing your watch.

## Reference Projects

- **Rod Trent's Garmin Chat Connector:** https://github.com/rod-trent/GarminChatLocal — cloud-hosted Garmin MCP, good reference for the server architecture and tool design
- **garmin-givemydata:** https://github.com/nrvim/garmin-givemydata — browser-based Garmin auth that works post-March 2026, local SQLite storage, 44 MCP tools
- **r-huijts/strava-mcp:** https://github.com/r-huijts/strava-mcp — 25 Strava tools, compact data format, good reference for Strava tool design
- **eddmann/garmin-connect-mcp:** https://github.com/eddmann/garmin-connect-mcp — 22 Garmin tools organized into 8 categories, Docker support, prompt templates
- **Edd Mann's blog post:** https://eddmann.com/posts/running-mcps-everywhere-chatting-with-my-workouts/ — excellent writeup on MCP tool design patterns for fitness data
