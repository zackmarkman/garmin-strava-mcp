# Garmin + Strava MCP

A self-hosted [MCP](https://modelcontextprotocol.io) server that exposes your
Garmin Connect and Strava data to Claude. Ask things like:

- "How's my training load this week?"
- "Compare my sleep the last five nights against my HRV."
- "Am I recovered enough for a hard run?"

Single user, self-deployed to [Fly.io](https://fly.io) (free tier is plenty).
Takes ~15 minutes end-to-end. You run your own instance — your tokens and
data never touch anyone else's server.

---

## Contents

1. [Prerequisites](#1-prerequisites)
2. [Clone and install](#2-clone-and-install)
3. [Generate keys and register a Strava app](#3-generate-keys-and-register-a-strava-app)
4. [Authorize Strava](#4-authorize-strava)
5. [Authorize Garmin](#5-authorize-garmin) ← the tricky one
6. [Smoke test locally](#6-smoke-test-locally)
7. [Deploy to Fly.io](#7-deploy-to-flyio)
8. [Connect to Claude](#8-connect-to-claude)
9. [Maintenance](#maintenance)
10. [Troubleshooting](#troubleshooting)

---

## 1. Prerequisites

- macOS or Linux
- A Garmin Connect account with a synced device
- A Strava account
- A [Fly.io](https://fly.io) account (free; card required for verification)
- [Claude](https://claude.ai) (any plan that supports custom connectors)

Install tools:

```bash
# uv (Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# flyctl (Fly.io CLI)
brew install flyctl          # macOS
# or: curl -L https://fly.io/install.sh | sh

fly auth login
```

---

## 2. Clone and install

```bash
git clone https://github.com/zackmarkman/garmin-strava-mcp.git
cd garmin-strava-mcp
uv sync
```

---

## 3. Generate keys and register a Strava app

**Generate a server token and encryption key:**

```bash
cp .env.example .env
uv run python scripts/generate_token.py >> .env
```

That appends `SERVER_TOKEN` and `FERNET_KEY` to `.env`.

- `SERVER_TOKEN` gates every request to your server — treat it like a password.
- `FERNET_KEY` encrypts OAuth tokens on disk. If you lose it, re-run the
  setup scripts. **The trailing `=` is part of the key; keep it.**

**Register a Strava API app:**

1. Go to <https://www.strava.com/settings/api>.
2. Create an application. **Authorization Callback Domain must be `localhost`**
   (not a URL, just `localhost`).
3. Copy the **Client ID** and **Client Secret** into `.env`:

    ```
    STRAVA_CLIENT_ID=12345
    STRAVA_CLIENT_SECRET=abc123...
    ```

---

## 4. Authorize Strava

```bash
uv run python scripts/setup_strava_auth.py
```

A browser tab opens → click **Authorize**. The script captures the redirect,
exchanges the code for tokens, and writes them to `data/mcp.db` encrypted.
Should finish in <10 seconds. If the browser doesn't open, copy the URL the
script prints.

---

## 5. Authorize Garmin

Garmin doesn't offer an OAuth app for third-party tools, so we borrow a
single-use SSO ticket from a browser session where you're already logged in.
This is the **highest-friction step** — plan 2–3 minutes for your first try.

### Method A: Chrome DevTools (recommended)

1. In your **normal Chrome** (the one where you're logged in to Garmin every
   day), confirm you're signed in at <https://connect.garmin.com>.
2. Open DevTools: **Cmd+Opt+I** (macOS) or **Ctrl+Shift+I** (Linux).
   Click the **Network** tab and tick **Preserve log** (top-left of the panel).
3. In a separate terminal, start the setup script — it waits for a ticket:

    ```bash
    uv run python scripts/setup_garmin_auth.py
    ```

4. Back in Chrome, paste this URL into the address bar and press Enter:

    ```
    https://sso.garmin.com/sso/signin?clientId=GCM_ANDROID_DARK&service=https%3A%2F%2Fmobile.integration.garmin.com%2Fgcm%2Fandroid
    ```

5. The page will show a **"can't reach this site"** error. That's expected —
   the redirect target isn't a real web page.
6. In the DevTools **Network** log, find a row whose URL contains
   `ticket=ST-…`. It's the last successful (302) request before the error.
   Right-click → **Copy** → **Copy link address**.
7. Paste into the terminal prompt. **You have ~10 seconds before the ticket
   expires** — if it expires, just reload the URL in step 4 for a fresh one.

The script exchanges the ticket for a long-lived token set and saves them
encrypted. Expected output: `Saved Garmin tokens for <Your Name>.`

### Method B: Address bar only (no DevTools)

Same as Method A, but in step 6 just copy the full URL from Chrome's address
bar **before the error page finishes loading**. The URL briefly shows
`…&ticket=ST-…` while the redirect is in flight. Faster but less reliable —
DevTools lets you look at past requests instead of racing the browser.

### If Garmin auth fails

See [Troubleshooting → Garmin auth](#garmin-auth).

---

## 6. Smoke test locally

```bash
uv run python -m src.server
```

In another terminal:

```bash
curl http://localhost:8000/health
# → {"ok":true}

# Verify a tool works (replace <TOKEN> with your SERVER_TOKEN from .env):
uv run python scripts/smoke_test.py
```

If the smoke test prints activity counts and sleep data, you're ready to
deploy. Ctrl+C the server.

---

## 7. Deploy to Fly.io

**Create the app.** Pick a unique name — the default `garmin-strava-mcp` is
taken by this project.

```bash
fly launch --copy-config --no-deploy --name <your-app-name>
```

If you accept the defaults in the interactive prompts, edit `fly.toml`
afterward to set `app = '<your-app-name>'` and `primary_region = '<your-region>'`
(e.g. `'ewr'`, `'sjc'`).

**Create the persistent volume** (token DB lives here):

```bash
fly volumes create mcp_data --region <your-region> --size 1 --yes
```

**Push secrets.** Use `cut -d= -f2-` (with the trailing `-`) — the `FERNET_KEY`
ends in `=` and gets silently truncated otherwise:

```bash
fly secrets set \
  SERVER_TOKEN="$(grep ^SERVER_TOKEN .env | cut -d= -f2-)" \
  FERNET_KEY="$(grep ^FERNET_KEY .env | cut -d= -f2-)" \
  STRAVA_CLIENT_ID="$(grep ^STRAVA_CLIENT_ID .env | cut -d= -f2-)" \
  STRAVA_CLIENT_SECRET="$(grep ^STRAVA_CLIENT_SECRET .env | cut -d= -f2-)"
```

**Deploy:**

```bash
fly deploy
```

**Upload your local token DB** (the Fly app has no tokens yet):

```bash
fly ssh sftp shell
# at the prompt:
put data/mcp.db /data/mcp.db
# exit the sftp shell with Ctrl+D, then:
fly machine restart
```

**Verify:**

```bash
curl https://<your-app-name>.fly.dev/health
# → {"ok":true}
```

---

## 8. Connect to Claude

1. Open Claude → **Settings → Connectors → Add custom**.
2. URL: `https://<your-app-name>.fly.dev/mcp?token=<your SERVER_TOKEN>`
3. Name: **Garmin + Strava**
4. Tool permissions → **Always allow**.
5. Try: *"What did I do on Strava this week?"* or *"How's my recovery?"*

---

## Maintenance

Tokens expire eventually. Symptoms: Claude returns `Garmin session expired`
or `401 Strava`. To fix:

```bash
# Strava (every few months if ever):
uv run python scripts/setup_strava_auth.py

# Garmin (roughly once a year, or after a password change):
uv run python scripts/setup_garmin_auth.py
```

Then re-upload the DB:

```bash
fly ssh sftp shell
put data/mcp.db /data/mcp.db
# Ctrl+D
fly machine restart
```

---

## Troubleshooting

### Garmin auth

- **"Ticket exchange failed: 401"** — the ticket expired (10-second window) or
  was minted for the wrong audience. Reload the ticket URL in step 4 and
  paste the fresh ticket.
- **Can't find `ticket=ST-…` in DevTools** — make sure you ticked
  **Preserve log** *before* navigating. Without it, Chrome wipes the log on
  the redirect. Also check you're filtering on **All**, not **Fetch/XHR**.
- **Browser loads a normal Garmin login page instead of erroring** — you got
  signed out. Sign in at <https://connect.garmin.com>, then retry step 4.
- **Chrome auto-completes the wrong URL** — paste it into a fresh incognito
  tab where you've first logged in to Garmin, so there's no URL history noise.
- **Still stuck** — the ticket URL works in Firefox and Safari too; any
  browser where you're logged in to Garmin is fine.

### Strava auth

- **"Authorization Callback Domain must be localhost"** — on the Strava app
  settings page, set the field to literally `localhost` (no `http://`, no port).
- **Browser shows "this site can't be reached" on redirect** — check the
  script is still running and listening on port 8721.

### Fly.io deploy

- **`Error: region sea not found`** — `sea` was retired. Pick another region
  like `ewr`, `sjc`, or `lhr` (see `fly platform regions`).
- **Claude connector returns auth errors immediately** — 99% of the time this
  is a truncated `FERNET_KEY`. Re-run the `fly secrets set …` block and make
  sure you used `cut -d= -f2-` (with the dash).
- **`fly ssh sftp shell` doesn't exit on typing `exit`** — use **Ctrl+D**.

---

## What's exposed

**Garmin:** daily summary, sleep, HRV, body battery, VO2 max, training load,
training readiness, recovery time, stress, recent activities, activity
details, data freshness.

**Strava:** recent activities, activity details, streams, athlete stats,
weekly totals, starred segments.

Every tool accepts `refresh: bool = False` to bypass the local cache. TTLs
live in [src/cache.py](src/cache.py).

---

## Security notes

- `SERVER_TOKEN` is the only thing gating access to your data — keep the
  Claude connector URL private.
- OAuth tokens are Fernet-encrypted at rest. Losing `FERNET_KEY` means
  re-running the setup scripts.
- Designed for **single-user** use. There's no multi-tenant auth.
- `.env` and `data/` are gitignored. Don't force-add them.

## License

MIT.
