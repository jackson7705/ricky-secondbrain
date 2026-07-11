"""
Shared Google OAuth token management for all Google integrations.

All Google services (Gmail, Calendar, Sheets, Docs, Drive) share a single OAuth token.
Token is stored as JSON and auto-refreshes when expired.

Setup:
1. Download OAuth credentials from Google Cloud Console → Desktop app
2. Save as .claude/scripts/integrations/google_credentials.json
3. Run: uv run python setup_auth.py
   (on headless machines: uv run python setup_auth.py --headless)
"""

from __future__ import annotations

import json
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Any

# Add parent dir for config imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import GOOGLE_CREDENTIALS_FILE, GOOGLE_SCOPES, google_token_file

# The active Google profile for the current execution context.
# CLI wrappers (query.py) set this based on --account before dispatching
# to a command handler; service helpers read from it when no explicit
# `account` argument is passed. This lets us add multi-profile support
# without modifying every public function signature across all five
# Google integration modules.
_active_account: ContextVar[str | None] = ContextVar("active_google_account", default=None)


def set_active_account(account: str | None) -> None:
    """Set the active Google profile for this execution context."""
    _active_account.set(account)


def get_active_account() -> str | None:
    """Return the active Google profile, if one was set via `set_active_account`."""
    return _active_account.get()


def get_google_credentials(account: str | None = None) -> Any:
    """
    Load Google OAuth credentials for a profile, refreshing if expired.

    Args:
        account: Named profile (e.g. "growthpro"). If omitted, uses
                 `DEFAULT_GOOGLE_ACCOUNT` env var or the legacy
                 single-account token file.

    Returns authenticated Credentials object usable for Gmail and Calendar APIs.
    Raises FileNotFoundError if credentials file is missing.
    Raises RuntimeError if token is invalid and re-auth is needed.
    """
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    # Resolution order: explicit arg > contextvar (set by CLI) > config default.
    resolved = account if account is not None else _active_account.get()
    token_path = google_token_file(resolved)
    creds: Credentials | None = None

    # Load existing token. Use the scopes the token was ACTUALLY granted (read
    # from the file) rather than the current app-wide GOOGLE_SCOPES list —
    # otherwise adding a new scope in config (e.g. drive.file for
    # invoice-router) makes every existing token fail refresh with
    # `invalid_scope` until the user re-auths. setup_auth.py is the right
    # place to expand scopes; runtime should tolerate stale tokens.
    if token_path.exists():
        try:
            granted_scopes = json.loads(token_path.read_text()).get("scopes") or GOOGLE_SCOPES
        except Exception:
            granted_scopes = GOOGLE_SCOPES
        creds = Credentials.from_authorized_user_file(  # type: ignore[no-untyped-call]
            str(token_path), granted_scopes
        )

    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            token_json: str = creds.to_json()  # type: ignore[no-untyped-call]
            token_path.write_text(token_json, encoding="utf-8")
            return creds
        except RefreshError as e:
            raise RuntimeError(
                f"Google token refresh failed for {resolved or 'default'}: {e}\n"
                f"Run 'uv run python setup_auth.py"
                f"{f' --account {resolved}' if resolved else ''}' to re-authenticate."
            ) from e

    # Valid credentials exist
    if creds and creds.valid:
        return creds

    # Need initial auth flow
    raise RuntimeError(
        f"No valid Google OAuth token found for {resolved or 'default'}.\n"
        f"Run 'uv run python setup_auth.py"
        f"{f' --account {resolved}' if resolved else ''}' to authenticate."
    )


def run_initial_auth(headless: bool = False, account: str | None = None) -> Any:
    """
    Run the interactive OAuth flow (one-time setup) for a profile.

    Args:
        headless: If True, use manual copy-paste flow (no browser needed).
                  Prints a URL, user opens it locally, pastes back the auth code.
                  If False, opens a browser and runs a local callback server.
        account:  Named profile. Token is saved to
                  `google_token_<account>.json`. If omitted, uses the
                  default profile (legacy single-token behavior).

    Requires google_credentials.json to be present.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore[import-untyped]

    if not GOOGLE_CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"Google credentials file not found: {GOOGLE_CREDENTIALS_FILE}\n"
            "Download from Google Cloud Console → APIs & Services → Credentials → "
            "OAuth 2.0 Client ID → Desktop app → Download JSON"
        )

    token_path = google_token_file(account)

    flow = InstalledAppFlow.from_client_secrets_file(
        str(GOOGLE_CREDENTIALS_FILE), GOOGLE_SCOPES
    )

    if headless:
        # Manual flow for headless/remote machines:
        # 1. Generate auth URL
        # 2. User opens in local browser, authorizes
        # 3. Google redirects to localhost (which fails — that's fine)
        # 4. User copies the full redirect URL and pastes it back
        flow.redirect_uri = "http://localhost:1"  # Use port 1 (won't actually listen)
        auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")

        print("\n" + "=" * 60)
        label = f" ({account})" if account else ""
        print(f"  HEADLESS GOOGLE OAUTH SETUP{label}")
        print("=" * 60)
        print(f"\n1. Open this URL in your browser:\n\n{auth_url}\n")
        print("2. Authorize the app and grant all requested permissions.")
        print("3. You'll be redirected to a page that FAILS to load (localhost:1).")
        print("   That's expected! Copy the FULL URL from your browser's address bar.")
        print("   It looks like: http://localhost:1/?state=...&code=...&scope=...")
        print()
        redirect_response = input("4. Paste the full redirect URL here: ").strip()

        # Extract the authorization code from the redirect URL
        flow.fetch_token(authorization_response=redirect_response)
        creds = flow.credentials
    else:
        creds = flow.run_local_server(port=0)

    # Save token
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    print(f"\nToken saved to {token_path}")

    return creds


def is_google_authenticated(account: str | None = None) -> bool:
    """Check if a valid Google OAuth token exists for a profile (no auth flow)."""
    token_path = google_token_file(account)
    if not token_path.exists():
        return False

    try:
        from google.oauth2.credentials import Credentials

        creds = Credentials.from_authorized_user_file(  # type: ignore[no-untyped-call]
            str(token_path), GOOGLE_SCOPES
        )
        # Token exists and either valid or has refresh_token to renew
        return creds.valid or bool(creds.refresh_token)
    except Exception:
        return False
