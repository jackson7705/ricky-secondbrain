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
from typing import Any

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
    DISCORD_ALLOWED_USER_IDS,
    DISCORD_BOT_TOKEN,
    IMESSAGE_ALLOWED_ADDRESSES,
    IMESSAGE_STATE_PATH,
    PROJECT_ROOT,
    SLACK_APP_TOKEN,
    SLACK_BOT_TOKEN,
    TELEGRAM_ALLOWED_USER_IDS,
    TELEGRAM_BOT_TOKEN,
)


def _slack_configured() -> bool:
    return bool(SLACK_BOT_TOKEN and SLACK_APP_TOKEN)


def _imessage_configured() -> bool:
    return bool(BLUEBUBBLES_URL and BLUEBUBBLES_PASSWORD and IMESSAGE_ALLOWED_ADDRESSES)


def _discord_configured() -> bool:
    return bool(DISCORD_BOT_TOKEN and DISCORD_ALLOWED_USER_IDS)


def _telegram_configured() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_ALLOWED_USER_IDS)


def _build_adapters(router: "ChatRouter", store: Any, verbose: bool = False) -> int:
    """Register every configured chat surface. Returns the count registered."""
    n = 0
    if _slack_configured():
        from adapters.slack import SlackAdapter
        router.register(SlackAdapter(SLACK_BOT_TOKEN, SLACK_APP_TOKEN,
                                     CHAT_ALLOWED_USERS, session_store=store))
        n += 1
        if verbose:
            print("  Slack adapter OK")
    if _imessage_configured():
        from adapters.imessage import IMessageAdapter
        router.register(IMessageAdapter(
            base_url=BLUEBUBBLES_URL, password=BLUEBUBBLES_PASSWORD,
            allowed_addresses=IMESSAGE_ALLOWED_ADDRESSES,
            state_path=IMESSAGE_STATE_PATH, poll_interval=BLUEBUBBLES_POLL_INTERVAL))
        n += 1
        if verbose:
            print("  iMessage adapter OK")
    if _discord_configured():
        from adapters.discord_adapter import DiscordAdapter
        router.register(DiscordAdapter(DISCORD_BOT_TOKEN, DISCORD_ALLOWED_USER_IDS,
                                       session_store=store))
        n += 1
        if verbose:
            print("  Discord adapter OK")
    if _telegram_configured():
        from adapters.telegram import TelegramAdapter
        router.register(TelegramAdapter(TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USER_IDS,
                                        session_store=store))
        n += 1
        if verbose:
            print("  Telegram adapter OK")
    return n


def main() -> None:
    parser = argparse.ArgumentParser(description="Second Brain Chat Interface")
    parser.add_argument("--test", action="store_true", help="Dry run — print config and exit")
    args = parser.parse_args()

    surfaces = []
    if _slack_configured():
        surfaces.append("Slack")
    if _imessage_configured():
        surfaces.append("iMessage")
    if _discord_configured():
        surfaces.append("Discord")
    if _telegram_configured():
        surfaces.append("Telegram")

    if not surfaces:
        print("ERROR: no chat platform is configured. Set one of:")
        print("  • SLACK_BOT_TOKEN + SLACK_APP_TOKEN")
        print("  • BLUEBUBBLES_URL + BLUEBUBBLES_PASSWORD + IMESSAGE_ALLOWED_ADDRESSES")
        print("  • DISCORD_BOT_TOKEN + DISCORD_ALLOWED_USER_IDS")
        print("  • TELEGRAM_BOT_TOKEN + TELEGRAM_ALLOWED_USER_IDS")
        sys.exit(1)

    # Print startup banner
    print(f"\n{'=' * 60}")
    print("Second Brain Chat Interface")
    print(f"{'=' * 60}")
    print(f"  Project root:  {PROJECT_ROOT}")
    print(f"  Database:      {CHAT_DB_PATH}")
    print(f"  Max turns:     {CHAT_MAX_TURNS}")
    print(f"  Max budget:    ${CHAT_MAX_BUDGET_USD:.2f}")
    print(f"  Chat surfaces: {', '.join(surfaces)}")
    print(f"{'=' * 60}\n")

    if args.test:
        print("Test mode — validating config and exiting.")
        store = get_session_store(CHAT_DB_PATH)
        active = store.list_active()
        print(f"  Session store OK ({len(active)} active sessions)")
        engine = ConversationEngine(store, PROJECT_ROOT, CHAT_MAX_TURNS, CHAT_MAX_BUDGET_USD)
        print("  Engine OK")
        router = ChatRouter(engine)
        _build_adapters(router, store, verbose=True)
        print("\nAll checks passed. Run without --test to start.")
        return

    # Live mode
    store = get_session_store(CHAT_DB_PATH)
    engine = ConversationEngine(store, PROJECT_ROOT, CHAT_MAX_TURNS, CHAT_MAX_BUDGET_USD)
    router = ChatRouter(engine)
    _build_adapters(router, store)

    print(f"[{datetime.now()}] Starting chat interface...")

    try:
        asyncio.run(router.run())
    except KeyboardInterrupt:
        print(f"\n[{datetime.now()}] Shutting down...")
        asyncio.run(router.shutdown())
        print(f"[{datetime.now()}] Goodbye!")


if __name__ == "__main__":
    main()
