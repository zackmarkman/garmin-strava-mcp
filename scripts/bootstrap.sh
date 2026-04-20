#!/usr/bin/env bash
# One-shot local setup: install deps, generate keys, authorize Strava + Garmin.
# Re-run any individual step by copying its command out of this file.
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null; then
  echo "uv not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi

echo "==> Installing dependencies"
uv sync

if [ ! -f .env ]; then
  echo "==> Creating .env from .env.example"
  cp .env.example .env

  echo "==> Generating SERVER_TOKEN + FERNET_KEY"
  uv run python scripts/generate_token.py >> .env

  echo
  echo "Next: open .env and paste your STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET"
  echo "  from https://www.strava.com/settings/api"
  echo "  (Authorization Callback Domain must be 'localhost')"
  echo
  read -rp "Press Enter once .env has both Strava values filled in..."
fi

echo "==> Authorizing Strava (opens browser)"
uv run python scripts/setup_strava_auth.py

echo "==> Authorizing Garmin (interactive ticket paste)"
uv run python scripts/setup_garmin_auth.py

echo
echo "Local setup complete. Test the server with:"
echo "  uv run python -m src.server"
echo "Then deploy to Fly.io by following DEPLOY.md."
