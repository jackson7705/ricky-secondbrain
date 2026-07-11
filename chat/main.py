"""
Multi-platform chat interface for Second Brain.

Usage:
    cd .claude/scripts && uv run python ../chat/main.py
    cd .claude/scripts && uv run python ../chat/main.py --test  # Dry run (no platform connections)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Add both chat dir and scripts dir to path for imports
_CHAT_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _CHAT_DIR.parent / "scripts"
sys.path.insert(0, str(_CHAT_DIR))
sys.path.insert(0, str(_SCRIPTS_DIR))

from engine import ConversationEngine  # noqa: E402
from router import ChatRouter  # noqa: E402
from session import get_session_store  # noqa: E402

from config import (  # noqa: E402
    BLUEBUBBLES_POLL_INTERVAL,
    BLUEBUBBLES_PASSWORD,
    BLUEBUBBLES_URL,
    CHAT_ALLOWED_USERS,
    CHAT_DB_PATH,
    CHAT_MAX_BUDGET_USD,
    CHAT_MAX_TURNS,
    IMESSAGE_ALLOWED_ADDRESSES,
    IMESSAGE_STATE_PATH,
    PROJECT_ROOT,
    SLACK_APP_TOKEN,
    SLACK_BOT_TOKEN,
)


def _slack_configured() -> bool:
    return bool(SLACK_BOT_TOKEN and SLACK_APP_TOKEN)


def _imessage_configured() -> bool:
    return bool(BLUEBUBBLES_URL and BLUEBUBBLES_PASSWORD and IMESSAGE_ALLOWED_ADDRESSES)


def main() -> None:
    parser = argparse.ArgumentParser(description="Second Brain Chat Interface")
    parser.add_argument("--test", action="store_true", help="Dry run — print config and exit")
    args = parser.parse_args()

    slack_on = _slack_configured()
    imessage_on = _imessage_configured()

    if not (slack_on or imessage_on):
        print("ERROR: no chat platform is configured.")
        print("Set SLACK_BOT_TOKEN + SLACK_APP_TOKEN, or BLUEBUBBLES_URL + "
              "BLUEBUBBLES_PASSWORD + IMESSAGE_ALLOWED_ADDRESSES in .env")
        sys.exit(1)

    # Print startup banner
    print(f"\n{'=' * 60}")
    print("Second Brain Chat Interface")
    print(f"{'=' * 60}")
    print(f"  Project root:  {PROJECT_ROOT}")
    print(f"  Database:      {CHAT_DB_PATH}")
    print(f"  Max turns:     {CHAT_MAX_TURNS}")
    print(f"  Max budget:    ${CHAT_MAX_BUDGET_USD:.2f}")
    if slack_on:
        print(f"  Slack users:   {', '.join(CHAT_ALLOWED_USERS)}")
        print(f"  Slack token:   {SLACK_BOT_TOKEN[:12]}...")
    else:
        print("  Slack:         (disabled — no token)")
    if imessage_on:
        print(f"  iMessage URL:  {BLUEBUBBLES_URL}")
        print(f"  iMessage allowlist: {len(IMESSAGE_ALLOWED_ADDRESSES)} address(es)")
        print(f"  iMessage poll: {BLUEBUBBLES_POLL_INTERVAL}s")
    else:
        print("  iMessage:      (disabled — BlueBubbles not configured)")
    print(f"{'=' * 60}\n")

    if args.test:
        print("Test mode — validating config and exiting.")

        store = get_session_store(CHAT_DB_PATH)
        active = store.list_active()
        print(f"  Session store OK ({len(active)} active sessions)")

        engine = ConversationEngine(store, PROJECT_ROOT, CHAT_MAX_TURNS, CHAT_MAX_BUDGET_USD)
        print("  Engine OK")

        router = ChatRouter(engine)

        if slack_on:
            from adapters.slack import SlackAdapter

            slack = SlackAdapter(SLACK_BOT_TOKEN, SLACK_APP_TOKEN, CHAT_ALLOWED_USERS, session_store=store)
            router.register(slack)
            print("  Slack adapter OK")

        if imessage_on:
            from adapters.imessage import IMessageAdapter

            imessage = IMessageAdapter(
                base_url=BLUEBUBBLES_URL,
                password=BLUEBUBBLES_PASSWORD,
                allowed_addresses=IMESSAGE_ALLOWED_ADDRESSES,
                state_path=IMESSAGE_STATE_PATH,
                poll_interval=BLUEBUBBLES_POLL_INTERVAL,
            )
            router.register(imessage)
            print("  iMessage adapter OK")

        print("\nAll checks passed. Run without --test to start.")
        return

    # Live mode
    store = get_session_store(CHAT_DB_PATH)
    engine = ConversationEngine(store, PROJECT_ROOT, CHAT_MAX_TURNS, CHAT_MAX_BUDGET_USD)
    router = ChatRouter(engine)

    if slack_on:
        from adapters.slack import SlackAdapter

        slack = SlackAdapter(SLACK_BOT_TOKEN, SLACK_APP_TOKEN, CHAT_ALLOWED_USERS, session_store=store)
        router.register(slack)

    if imessage_on:
        from adapters.imessage import IMessageAdapter

        imessage = IMessageAdapter(
            base_url=BLUEBUBBLES_URL,
            password=BLUEBUBBLES_PASSWORD,
            allowed_addresses=IMESSAGE_ALLOWED_ADDRESSES,
            state_path=IMESSAGE_STATE_PATH,
            poll_interval=BLUEBUBBLES_POLL_INTERVAL,
        )
        router.register(imessage)

    print(f"[{datetime.now()}] Starting chat interface...")

    try:
        asyncio.run(router.run())
    except KeyboardInterrupt:
        print(f"\n[{datetime.now()}] Shutting down...")
        asyncio.run(router.shutdown())
        print(f"[{datetime.now()}] Goodbye!")


if __name__ == "__main__":
    main()
