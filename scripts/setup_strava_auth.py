"""One-time Strava OAuth bootstrap.

Opens the Strava authorization page in your browser, listens on localhost for
the redirect, exchanges the authorization code for tokens, and stores them
Fernet-encrypted in the MCP SQLite database.

Run once. After this, the server auto-refreshes tokens as needed.
"""

from __future__ import annotations

import http.server
import socketserver
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

import httpx

# Allow running as a script: `python scripts/setup_strava_auth.py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config, storage  # noqa: E402
from src.strava.client import TOKENS_KEY, TOKEN_URL  # noqa: E402

REDIRECT_PORT = 8721
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
SCOPE = "read,activity:read_all,profile:read_all"


class _Handler(http.server.BaseHTTPRequestHandler):
    code: str | None = None
    error: str | None = None

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_error(404)
            return
        params = urllib.parse.parse_qs(parsed.query)
        if "error" in params:
            _Handler.error = params["error"][0]
            self._reply("Authorization denied — close this window and try again.")
            return
        code = params.get("code", [None])[0]
        scope = params.get("scope", [""])[0]
        if not code:
            self._reply("No code in redirect — try again.")
            return
        _Handler.code = code
        _Handler.granted_scope = scope
        self._reply("Strava connected. You can close this tab.")

    def _reply(self, text: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"<h3>{text}</h3>".encode())

    def log_message(self, *_args, **_kwargs):  # silence default stderr logging
        return


def _await_code() -> tuple[str, str]:
    with socketserver.TCPServer(("127.0.0.1", REDIRECT_PORT), _Handler) as server:
        server.timeout = 1
        print(f"Waiting for redirect on {REDIRECT_URI} ...")
        while _Handler.code is None and _Handler.error is None:
            server.handle_request()
    if _Handler.error:
        raise SystemExit(f"Authorization error: {_Handler.error}")
    return _Handler.code, getattr(_Handler, "granted_scope", "")


def main() -> None:
    client_id, client_secret = config.strava_client()
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": SCOPE,
    }
    auth_url = "https://www.strava.com/oauth/authorize?" + urllib.parse.urlencode(params)
    print("Opening browser for Strava authorization ...")
    threading.Thread(target=webbrowser.open, args=(auth_url,), daemon=True).start()
    print(f"If the browser didn't open, visit:\n  {auth_url}\n")

    code, granted_scope = _await_code()
    print("Got authorization code. Exchanging for tokens ...")

    resp = httpx.post(
        TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    storage.save_tokens(
        TOKENS_KEY,
        {
            "access_token": payload["access_token"],
            "refresh_token": payload["refresh_token"],
            "expires_at": payload["expires_at"],
            "scope": granted_scope,
            "athlete_id": (payload.get("athlete") or {}).get("id"),
        },
    )
    print(f"Saved Strava tokens (scope: {granted_scope}).")


if __name__ == "__main__":
    main()
