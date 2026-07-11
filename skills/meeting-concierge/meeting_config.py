"""Configuration for meeting-concierge.

Named `meeting_config` (not `config`) to avoid collision with `scripts/config.py`
— same pitfall invoice-router hit on 2026-04-19.
"""

from __future__ import annotations

from pathlib import Path

# ── Timing ──────────────────────────────────────────────────────────────

# How far in the future the pre-meeting brief should look. 15 minutes gives
# Jason enough lead time to grab water and open the right ClickUp task without
# spamming him an hour early.
BRIEF_LOOKAHEAD_MINUTES = 15

# Active hours for the brief. Launchd fires every 5 min regardless; the script
# exits quietly outside this window.
ACTIVE_HOURS_START = 8   # 08:00
ACTIVE_HOURS_END = 22    # 22:00 (10pm)
ACTIVE_TZ = "America/Chicago"

# How recent an email has to be to be considered relevant context.
RECENT_EMAIL_DAYS = 14

# Don't re-brief the same event. Entries expire from state after 3 days so the
# file doesn't grow forever.
BRIEF_STATE_RETENTION_DAYS = 3

# ── Accounts ────────────────────────────────────────────────────────────

# All three calendars are in scope (per MEMORY: calendar-scan-all-three).
CALENDAR_PROFILES = ["growthpro", "locafy", "wonderly"]

# Default email account for "recent emails with this attendee" lookups.
EMAIL_LOOKUP_PROFILE = "growthpro"

# ── ClickUp list mapping ────────────────────────────────────────────────

# When a post-meeting action item needs a ClickUp task, this picks the list.
# Keys are substrings matched against the meeting title; first hit wins.
# Fallback is `default_list_name` if nothing matches.
CLICKUP_LIST_KEYWORDS: list[tuple[str, str]] = [
    # (keyword in meeting title, ClickUp list name)
    ("partner", "Partner Pipeline"),
    ("locafy", "Locafy Ops"),
    ("wonderly", "Wonderly"),
    ("1:1", "1:1s"),
    ("standup", "Locafy Ops"),
]
CLICKUP_DEFAULT_LIST_NAME = "Inbox"

# ── iMessage brief ──────────────────────────────────────────────────────

# Jason's iMessage handle for outbound briefs — same allowlist as the chat
# service. The chat service already polls BlueBubbles; we route briefs through
# a direct REST call since this is one-way notification, not a conversation.
import os as _os  # noqa: E402
from pathlib import Path as _Path  # noqa: E402
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(_Path(__file__).resolve().parents[2] / "scripts" / ".env")
except Exception:  # noqa: BLE001
    pass
IMESSAGE_BRIEF_CHAT_GUID = _os.getenv("OWNER_IMESSAGE_GUID") or (
    f"any;-;+{_os.getenv('OWNER_PHONE', '').strip().lstrip('+')}"
    if _os.getenv("OWNER_PHONE") else "")

# Cap on brief length so iMessage doesn't split it awkwardly.
MAX_BRIEF_CHARS = 600

# ── Local paths ─────────────────────────────────────────────────────────

SKILL_DIR = Path(__file__).resolve().parent
STATE_FILE = SKILL_DIR / "state.json"
PENDING_DIGEST_FILE = SKILL_DIR / "pending-digest.json"
