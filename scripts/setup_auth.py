"""
One-time auth setup for all direct platform integrations.

Walks through Google OAuth and Slack bot token validation.

Usage:
    uv run python setup_auth.py          # Full interactive setup
    uv run python setup_auth.py --check  # Status check only (no auth flows)
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from config import (
    DEFAULT_GOOGLE_ACCOUNT,
    GOOGLE_CREDENTIALS_FILE,
    SLACK_BOT_TOKEN,
    SLACK_WORKSPACES,
    ensure_directories,
    list_google_profiles,
    list_slack_workspaces,
)


def print_header(title: str) -> None:
    """Print a section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


def print_status(name: str, ok: bool, detail: str = "") -> None:
    """Print a status line."""
    icon = "[OK]" if ok else "[--]"
    suffix = f" - {detail}" if detail else ""
    print(f"  {icon} {name}{suffix}")


def check_google(
    check_only: bool = False,
    headless: bool = False,
    account: str | None = None,
) -> bool:
    """Check/setup Google OAuth for a single profile (Gmail + Calendar + Sheets + Docs + Drive)."""
    label = f" — {account}" if account else ""
    print_header(f"Google OAuth{label} (Gmail + Calendar + Sheets + Docs + Drive)")

    from integrations.auth import is_google_authenticated

    if is_google_authenticated(account=account):
        print_status(
            f"Google OAuth{label}",
            True,
            "Token exists and is valid/refreshable",
        )

        # Quick validation - try building a service
        try:
            from integrations.auth import get_google_credentials

            creds = get_google_credentials(account=account)
            from googleapiclient.discovery import build  # type: ignore[import-untyped]

            # Test Gmail
            gmail = build("gmail", "v1", credentials=creds)
            profile = gmail.users().getProfile(userId="me").execute()
            print_status("Gmail", True, f"Connected as {profile.get('emailAddress', '?')}")

            # Test Calendar
            calendar = build("calendar", "v3", credentials=creds)
            cal_list = calendar.calendarList().list(maxResults=1).execute()
            num_cals = len(cal_list.get("items", []))
            print_status("Calendar", True, f"Access confirmed ({num_cals} calendars visible)")

            return True
        except Exception as e:
            print_status("API validation", False, str(e))
            return False

    if check_only:
        print_status(f"Google OAuth{label}", False, "Not authenticated")
        if not GOOGLE_CREDENTIALS_FILE.exists():
            print(f"\n  Missing: {GOOGLE_CREDENTIALS_FILE}")
            print("  Download from Google Cloud Console:")
            print("    1. Go to https://console.cloud.google.com")
            print("    2. Select/create project, enable Gmail + Calendar APIs")
            print("    3. Create OAuth 2.0 Client ID (Desktop app)")
            print("    4. Download JSON, save as google_credentials.json in:")
            print(f"       {GOOGLE_CREDENTIALS_FILE.parent}")
        else:
            print("\n  Credentials file found but no token yet.")
            cmd_suffix = f" --account {account}" if account else ""
            print(f"  Run `uv run python setup_auth.py{cmd_suffix}` to authenticate.")
        return False

    # Interactive setup
    if not GOOGLE_CREDENTIALS_FILE.exists():
        print(f"  Google credentials file not found: {GOOGLE_CREDENTIALS_FILE}")
        print()
        print("  To set up Google OAuth:")
        print("    1. Go to https://console.cloud.google.com")
        print("    2. Create/select project, enable Gmail API + Calendar API")
        print("    3. Configure OAuth consent screen:")
        print('       - User type: "External" (custom domain)')
        print('       - Publish to "Production" (non-sensitive scopes, no verification needed)')
        print("    4. Create OAuth 2.0 Client ID -> Desktop application")
        print("    5. Download JSON -> save as:")
        print(f"       {GOOGLE_CREDENTIALS_FILE}")
        print()
        input("  Press Enter when ready (or Ctrl+C to skip)...")

        if not GOOGLE_CREDENTIALS_FILE.exists():
            print_status(f"Google OAuth{label}", False, "Credentials file still not found")
            return False

    # Run OAuth flow
    mode = "headless (manual URL)" if headless else "browser-based"
    profile_desc = f" for profile '{account}'" if account else ""
    print(f"  Starting {mode} OAuth flow{profile_desc}...")
    if account:
        print(
            f"  When the browser opens, sign in with the Google account that maps "
            f"to '{account}'. The token will be saved as google_token_{account}.json."
        )
    try:
        from integrations.auth import run_initial_auth

        creds = run_initial_auth(headless=headless, account=account)
        print_status(f"Google OAuth{label}", True, "Authenticated successfully!")

        # Validate
        from googleapiclient.discovery import build

        gmail = build("gmail", "v1", credentials=creds)
        profile = gmail.users().getProfile(userId="me").execute()
        print_status("Gmail", True, f"Connected as {profile.get('emailAddress', '?')}")

        calendar = build("calendar", "v3", credentials=creds)
        cal_list = calendar.calendarList().list(maxResults=1).execute()
        print_status("Calendar", True, "Access confirmed")

        return True
    except Exception as e:
        print_status(f"Google OAuth{label}", False, str(e))
        return False


def run_linkedin_auth() -> None:
    """Interactive LinkedIn OAuth flow. Writes `linkedin_token.json`.

    One-time setup steps (if the client credentials aren't yet in .env) are
    documented at `.claude/skills/aeo-authority-content/LINKEDIN_SETUP.md`.
    """
    import http.server
    import secrets
    import threading
    import webbrowser
    from urllib.parse import parse_qs, urlparse

    from config import LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET
    from integrations.linkedin_api import (
        build_authorization_url,
        exchange_code_for_token,
        get_member_urn,
    )

    print_header("LinkedIn OAuth (publish on Jason's behalf)")
    if not LINKEDIN_CLIENT_ID or not LINKEDIN_CLIENT_SECRET:
        print_status(
            "LinkedIn OAuth",
            False,
            "Client credentials not configured in .env — see "
            ".claude/skills/aeo-authority-content/LINKEDIN_SETUP.md for the "
            "one-time app creation flow.",
        )
        sys.exit(1)

    redirect_port = 8765
    redirect_uri = f"http://localhost:{redirect_port}/callback"
    state = secrets.token_urlsafe(16)
    auth_url = build_authorization_url(redirect_uri, state)

    received: dict[str, str] = {}

    class _Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):  # silence default logging
            return

        def do_GET(self):
            query = parse_qs(urlparse(self.path).query)
            code = query.get("code", [""])[0]
            returned_state = query.get("state", [""])[0]
            err = query.get("error", [""])[0]
            err_desc = query.get("error_description", [""])[0]
            received["code"] = code
            received["state"] = returned_state
            if err:
                received["error"] = err
                received["error_description"] = err_desc
            msg = (
                f"<html><body><h1>Auth error from LinkedIn</h1>"
                f"<p><b>{err}:</b> {err_desc}</p></body></html>"
            ).encode() if err else (
                b"<html><body><h1>You can close this tab.</h1>"
                b"<p>LinkedIn auth complete, returning to setup_auth.py.</p>"
                b"</body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)

    server = http.server.HTTPServer(("127.0.0.1", redirect_port), _Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    print("  Opening LinkedIn authorization page in your browser…")
    print(f"  (fallback URL if nothing opens: {auth_url})")
    webbrowser.open(auth_url)

    # Wait for either a code or an error from LinkedIn.
    try:
        while "code" not in received and "error" not in received:
            pass
    finally:
        server.shutdown()

    if received.get("error"):
        print_status(
            "LinkedIn OAuth",
            False,
            f"LinkedIn returned {received['error']}: {received.get('error_description', '')}",
        )
        sys.exit(2)

    if not received.get("code"):
        print_status("LinkedIn OAuth", False, "no code in callback — LinkedIn redirect was empty")
        sys.exit(2)

    if received.get("state") != state:
        print_status("LinkedIn OAuth", False, "state mismatch — aborting")
        sys.exit(2)

    try:
        exchange_code_for_token(received["code"], redirect_uri)
        urn = get_member_urn()
        print_status("LinkedIn OAuth", True, f"Authenticated as {urn}")
    except Exception as e:
        print_status("LinkedIn OAuth", False, str(e))
        sys.exit(2)


def _validate_slack_token(label: str, bot_token: str) -> bool:
    """Validate a Slack bot token by calling auth_test."""
    try:
        from slack_sdk import WebClient
        from slack_sdk.errors import SlackApiError

        client = WebClient(token=bot_token)
        auth = client.auth_test()

        bot_name = auth.get("user", "?")
        team = auth.get("team", "?")
        print_status(label, True, f"Connected as {bot_name} in {team}")
        return True
    except SlackApiError as e:
        print_status(label, False, f"API error: {e.response['error']}")
        return False
    except Exception as e:
        print_status(label, False, str(e))
        return False


def check_slack(check_only: bool = False) -> bool:
    """Validate every configured Slack bot token.

    Reads `SLACK_WORKSPACES` (parsed from `SLACK_BOT_TOKEN_<NAME>` vars) when
    available, falling back to the legacy single `SLACK_BOT_TOKEN`.
    """
    print_header("Slack (Bot Tokens)")

    workspaces = list_slack_workspaces()

    if not workspaces and not SLACK_BOT_TOKEN:
        print_status("Slack", False, "no Slack bot tokens configured")
        instructions = [
            "  To set up Slack:",
            "    1. Go to https://api.slack.com/apps -> Create New App -> From Scratch",
            '    2. Name: "Second Brain", select your workspace',
            "    3. OAuth & Permissions -> Add Bot Token Scopes:",
            "       channels:read, channels:history, chat:write, chat:write.public, users:read",
            "    4. Install to Workspace -> Copy Bot User OAuth Token",
            "    5. Add a line per workspace to your environment config,",
            "       e.g. SLACK_BOT_TOKEN_<WORKSPACE>=<bot-token>",
            "       (or the legacy single-workspace SLACK_BOT_TOKEN variable).",
        ]
        for line in instructions:
            print(line)
        return False

    all_ok = True
    if workspaces:
        for ws in workspaces:
            bot_token = SLACK_WORKSPACES[ws]
            if not _validate_slack_token(f"Slack [{ws}]", bot_token):
                all_ok = False
    else:
        all_ok = _validate_slack_token("Slack", SLACK_BOT_TOKEN) and all_ok

    return all_ok


def main() -> None:
    """Run auth setup."""
    parser = argparse.ArgumentParser(description="Set up direct platform integrations")
    parser.add_argument("--check", action="store_true", help="Check status only (no auth flows)")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Use manual URL copy-paste flow (for remote/headless machines)",
    )
    parser.add_argument(
        "--account",
        default=None,
        help="Google profile to authenticate (e.g. growthpro, locafy, wonderly). "
        "Only affects the Google OAuth step. If omitted, uses the default profile "
        "from config (DEFAULT_GOOGLE_ACCOUNT).",
    )
    parser.add_argument(
        "--all-accounts",
        dest="all_accounts",
        action="store_true",
        help="Run the Google OAuth step for every profile that already has a "
        "saved token (useful with --check to validate all accounts at once).",
    )
    parser.add_argument(
        "--linkedin",
        action="store_true",
        help="Run the LinkedIn OAuth flow (needed before aeo-authority-content "
        "can publish posts on Jason's behalf). Requires LINKEDIN_CLIENT_ID and "
        "LINKEDIN_CLIENT_SECRET in .env.",
    )
    args = parser.parse_args()

    if args.linkedin:
        return run_linkedin_auth()

    ensure_directories()

    print_header("Second Brain - Direct Integrations Setup")
    print(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    mode = "Status Check" if args.check else ("Headless Setup" if args.headless else "Interactive Setup")
    print(f"  Mode: {mode}")

    # Decide which Google profiles to process.
    if args.all_accounts:
        google_profiles: list[str | None] = list(list_google_profiles())
        if not google_profiles:
            google_profiles = [None]  # nothing authenticated yet, use default
    elif args.account:
        google_profiles = [args.account]
    else:
        # If there's a DEFAULT_GOOGLE_ACCOUNT set, use it explicitly so status
        # output labels the profile by name. Otherwise fall back to unnamed.
        google_profiles = [DEFAULT_GOOGLE_ACCOUNT or None]

    google_results: list[tuple[str, bool]] = []
    for profile in google_profiles:
        label = f"Google ({profile})" if profile else "Google"
        ok = check_google(
            check_only=args.check,
            headless=args.headless,
            account=profile,
        )
        google_results.append((label, ok))

    slack_ok = check_slack(check_only=args.check)

    print_header("Summary")
    for label, ok in google_results:
        print_status(label, ok)
    print_status("Slack", slack_ok)

    all_oks = [ok for _, ok in google_results] + [slack_ok]
    configured = sum(1 for ok in all_oks if ok)
    total = len(all_oks)
    print(f"\n  {configured}/{total} integration checks passed")

    if configured < total and not args.check:
        print("\n  Re-run with --check to see what's still needed.")

    sys.exit(0 if configured == total else 1)


if __name__ == "__main__":
    main()
