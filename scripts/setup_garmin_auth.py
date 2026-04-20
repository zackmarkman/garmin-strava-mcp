"""Manual Garmin auth bootstrap.

No browser automation. You use your normal Chrome (real TLS fingerprint,
real cookies — Cloudflare waves it through) to grab a single-use SSO
service ticket. The script hands it to garminconnect's native DI token
exchange and saves the resulting tokens encrypted.

One-time setup:
    uv run python scripts/setup_garmin_auth_manual.py

You'll be walked through it interactively.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from garminconnect.client import Client as NativeClient  # noqa: E402

from src import storage  # noqa: E402
from src.garmin.client import TOKENS_KEY  # noqa: E402

# Mint ticket with the MOBILE audience garminconnect expects.
# MOBILE_SSO_SERVICE_URL in garminconnect is mobile.integration.garmin.com/gcm/android.
# clientId=GCM_ANDROID_DARK and that service URL must match or the DI token
# exchange at diauth.garmin.com returns 401.
TICKET_URL = (
    "https://sso.garmin.com/sso/signin"
    "?clientId=GCM_ANDROID_DARK"
    "&service=https%3A%2F%2Fmobile.integration.garmin.com%2Fgcm%2Fandroid"
)
TICKET_RE = re.compile(r"ticket=(ST-[A-Za-z0-9\-_]+)")


INSTRUCTIONS = f"""
================================================================
Garmin auth bootstrap — manual ticket capture
================================================================

Do these steps in your NORMAL Chrome (the one you log in to daily):

  1. Make sure you're logged in to Garmin Connect. If not, go to
     https://connect.garmin.com and sign in.

  2. Open Chrome DevTools (Cmd+Opt+I) → Network tab.
     Check "Preserve log" (top-left of the Network panel).

  3. With DevTools still open, paste this URL in the address bar
     and press Enter:

     {TICKET_URL}

     The page will probably show a "can't reach this site" error —
     that's EXPECTED. The redirect target (mobile.integration.garmin.com)
     isn't a real web page. We just need the ticket from the redirect.

  4. In the Network log, find the request whose URL contains
     "ticket=ST-...". It'll be the last successful (302/200) row
     before the error page. Right-click → Copy → Copy link address.
     (Or just grab the ticket=ST-... value from the URL bar itself
     before the error page loads.)

  5. Paste it below. You have ~10 seconds before the ticket
     expires, so do this promptly. If it expires, just repeat
     step 3 — Garmin will mint a fresh one.

================================================================
""".strip()


def _prompt_ticket() -> str:
    print(INSTRUCTIONS)
    print()
    while True:
        raw = input("Paste ticket URL or ST-... value: ").strip()
        if not raw:
            print("  (empty — try again)")
            continue
        match = TICKET_RE.search(raw)
        if match:
            return match.group(1)
        if raw.startswith("ST-"):
            return raw
        print("  (couldn't find a ticket=ST-... in that — try again)")


def main() -> None:
    ticket = _prompt_ticket()
    print(f"\nGot ticket ({ticket[:16]}...). Exchanging for DI tokens ...")

    client = NativeClient()
    try:
        client._exchange_service_ticket(ticket)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            f"Ticket exchange failed: {exc}\n"
            "Tickets are single-use and expire in ~10s. Re-run and paste a fresh one."
        ) from exc

    try:
        profile = client.connectapi("/userprofile-service/socialProfile")
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"Token exchange succeeded but API probe failed: {exc}") from exc
    full_name = (
        (profile or {}).get("displayName")
        or (profile or {}).get("fullName")
        or "unknown"
    )

    token_blob = client.dumps()
    storage.save_tokens(TOKENS_KEY, {"session": token_blob, "full_name": full_name})
    print(f"Saved Garmin tokens for {full_name}.")


if __name__ == "__main__":
    main()
