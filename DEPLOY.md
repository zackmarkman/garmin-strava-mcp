# Deploying to Fly.io

Do this AFTER both `scripts/setup_strava_auth.py` and `scripts/setup_garmin_auth.py`
have completed locally — the deployment copies the local SQLite DB up, so the
encrypted tokens need to be saved locally first.

## 1. Create the app

```bash
cd ~/code/garmin-strava-mcp
fly launch --copy-config --no-deploy --name garmin-strava-mcp
```

If the name is taken, pick something unique (e.g. `zm-garmin-mcp`) and update
`app = "..."` in `fly.toml` to match.

## 2. Create the persistent volume

```bash
fly volumes create mcp_data --region sea --size 1 --yes
```

## 3. Set server secrets

Values from your local `.env`:

```bash
# Use `cut -d= -f2-` (NOT -f2) so base64 values with trailing '=' survive.
# FERNET_KEY in particular ends in '=' and will be silently truncated otherwise.
fly secrets set \
  SERVER_TOKEN="$(grep ^SERVER_TOKEN .env | cut -d= -f2-)" \
  FERNET_KEY="$(grep ^FERNET_KEY .env | cut -d= -f2-)" \
  STRAVA_CLIENT_ID="$(grep ^STRAVA_CLIENT_ID .env | cut -d= -f2-)" \
  STRAVA_CLIENT_SECRET="$(grep ^STRAVA_CLIENT_SECRET .env | cut -d= -f2-)"
```

Do NOT push `GARMIN_EMAIL` / `GARMIN_PASSWORD` — the deployed server only uses
the encrypted session tokens in the SQLite DB you're about to upload.

## 4. Deploy

```bash
fly deploy
```

## 5. Upload the local token DB

```bash
fly ssh sftp shell
# in the prompt:
put data/mcp.db /data/mcp.db
exit

fly machine restart
```

## 6. Verify

```bash
# Public health check — no token required
curl https://garmin-strava-mcp.fly.dev/health

# Token-gated — should 401 without, 406 (Not Acceptable, correct for MCP) with
curl -i https://garmin-strava-mcp.fly.dev/mcp
curl -i "https://garmin-strava-mcp.fly.dev/mcp?token=$(grep ^SERVER_TOKEN .env | cut -d= -f2)"
```

## 7. Add to Claude

1. Open Claude (app, web, or desktop) → Settings → Connectors → Add custom.
2. URL: `https://garmin-strava-mcp.fly.dev/mcp?token=YOUR_SERVER_TOKEN`
3. Name it "Garmin + Strava".
4. Tool permissions → "Always allow".
5. Try: *"How's my training load this week?"*

## Rotating tokens or reconnecting

If Garmin or Strava tokens expire and the bootstrap scripts need to re-run:

1. Re-run the relevant `scripts/setup_*.py` locally.
2. Re-upload `data/mcp.db` via the sftp shell in step 5.
3. `fly machine restart`.
