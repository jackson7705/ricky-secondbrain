"""
Split (two-command) Google OAuth flow for re-authorizing a profile from chat.

`setup_auth.py --headless` blocks on `input()` waiting for the redirect URL,
which doesn't work when the request comes in over Slack/iMessage: the URL has
to go out in one message and the redirect URL comes back in a later one.
This script splits that into two independent invocations, persisting the
PKCE code verifier in between (Google rejects the token exchange without it).

    # 1. Print the consent URL — send it to Jason
    uv run python reconnect_google.py begin --account growthpro

    # 2. Jason authorizes, lands on a broken http://localhost:1/?state=...&code=...
    #    page, copies the full address-bar URL, sends it back
    uv run python reconnect_google.py finish --account growthpro --url "http://localhost:1/?state=...&code=..."

    # Alternative when Jason is AT the Mac: opens the Mac's browser and listens on a
    # local port so the redirect completes by itself (no URL copy/paste).
    uv run python reconnect_google.py local --account growthpro --timeout 900

Writes `integrations/google_token_<account>.json` with the CURRENT scope list
from config.py, so this is also the path for picking up newly added scopes
(e.g. the full `drive` scope added 2026-09-12).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import GOOGLE_CREDENTIALS_FILE, GOOGLE_SCOPES, google_token_file  # noqa: E402

REDIRECT_URI = "http://localhost:1"  # never listens — user copies the failed redirect


def _pending_file(account: str | None) -> Path:
    return google_token_file(account).with_name(f".pending_oauth_{account or 'default'}.json")


def begin(account: str | None) -> str:
    """Step 1: build the consent URL and park the flow state on disk."""
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]

    if not GOOGLE_CREDENTIALS_FILE.exists():
        raise FileNotFoundError(f"Google OAuth client file not found: {GOOGLE_CREDENTIALS_FILE}")

    flow = InstalledAppFlow.from_client_secrets_file(str(GOOGLE_CREDENTIALS_FILE), GOOGLE_SCOPES)
    flow.redirect_uri = REDIRECT_URI
    auth_url, state = flow.authorization_url(prompt="consent", access_type="offline")

    _pending_file(account).write_text(
        json.dumps(
            {
                "state": state,
                "code_verifier": flow.code_verifier,
                "redirect_uri": REDIRECT_URI,
                "scopes": GOOGLE_SCOPES,
            }
        ),
        encoding="utf-8",
    )
    return auth_url


def finish(account: str | None, redirect_response: str) -> Any:
    """Step 2: exchange the pasted redirect URL for a token and save it."""
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]

    pending = _pending_file(account)
    if not pending.exists():
        raise RuntimeError(
            f"No pending auth for {account or 'default'} — run `begin` first."
        )
    saved = json.loads(pending.read_text())

    flow = InstalledAppFlow.from_client_secrets_file(
        str(GOOGLE_CREDENTIALS_FILE),
        saved["scopes"],
        state=saved["state"],
        code_verifier=saved["code_verifier"],
        autogenerate_code_verifier=False,
    )
    flow.redirect_uri = saved["redirect_uri"]
    flow.fetch_token(authorization_response=redirect_response.strip())
    creds = flow.credentials

    token_path = google_token_file(account)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    pending.unlink(missing_ok=True)
    return creds


def local(account: str | None, port: int, timeout: int) -> Any:
    """Browser-on-this-Mac flow: opens the consent screen in the default browser
    and catches the redirect on localhost:<port>. Only works when the user is
    physically at this machine (a phone can't reach the Mac's loopback)."""
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]

    flow = InstalledAppFlow.from_client_secrets_file(str(GOOGLE_CREDENTIALS_FILE), GOOGLE_SCOPES)
    creds = flow.run_local_server(
        port=port,
        open_browser=True,
        prompt="consent",
        access_type="offline",
        timeout_seconds=timeout,
        success_message="Ricky is reconnected. You can close this tab.",
    )
    token_path = google_token_file(account)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    _pending_file(account).unlink(missing_ok=True)
    return creds


def _verify(creds: Any) -> str:
    """Confirm the new token actually works and report which account signed in."""
    from googleapiclient.discovery import build  # type: ignore[import-untyped]

    gmail = build("gmail", "v1", credentials=creds)
    email = gmail.users().getProfile(userId="me").execute().get("emailAddress", "?")
    drive = build("drive", "v3", credentials=creds)
    drive.files().list(pageSize=1, fields="files(id)").execute()
    return email


def main() -> int:
    parser = argparse.ArgumentParser(description="Two-step Google OAuth re-authorization")
    sub = parser.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("begin", help="Print the consent URL")
    b.add_argument("--account", default=None, help="Profile name (growthpro|locafy|...)")

    f = sub.add_parser("finish", help="Exchange the pasted redirect URL for a token")
    f.add_argument("--account", default=None, help="Profile name (growthpro|locafy|...)")
    f.add_argument("--url", required=True, help="Full http://localhost:1/?state=...&code=... URL")

    lc = sub.add_parser("local", help="Open the Mac's browser and catch the redirect locally")
    lc.add_argument("--account", default=None, help="Profile name (growthpro|locafy|...)")
    lc.add_argument("--port", type=int, default=8123)
    lc.add_argument("--timeout", type=int, default=900, help="Seconds to wait for the redirect")

    args = parser.parse_args()
    if args.cmd == "begin":
        print(begin(args.account))
        return 0

    if args.cmd == "local":
        creds = local(args.account, args.port, args.timeout)
    else:
        creds = finish(args.account, args.url)
    email = _verify(creds)
    granted = sorted(s.rsplit("/", 1)[-1] for s in (creds.scopes or []))
    print(f"Token saved for {args.account or 'default'} — signed in as {email}")
    print(f"Scopes: {', '.join(granted)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
