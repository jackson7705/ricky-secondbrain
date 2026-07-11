"""Configuration for daily-brief.

Named `brief_config` (not `config`) to avoid shadowing `scripts/config.py`
when Python resolves imports — same pitfall meeting-concierge hit.
"""

from __future__ import annotations

from pathlib import Path

# ── Timing ──────────────────────────────────────────────────────────────

# All gating is done in America/Chicago regardless of the Mac's timezone.
# If Jason is in Vegas, the brief still fires at 7am Central (= 5am Pacific).
BRIEF_TZ = "America/Chicago"

# Morning brief: Mon–Fri at 07:00 CT.
MORNING_WEEKDAYS = {0, 1, 2, 3, 4}  # Mon=0 .. Fri=4
MORNING_HOUR = 7

# Weekly rollup: Fri at 16:00 CT.
WEEKLY_WEEKDAY = 4  # Friday
WEEKLY_HOUR = 16

# How many minutes past the target hour we'll still consider "on time." Launchd
# fires hourly, so anything inside the target hour counts.
GATE_MINUTE_WINDOW = 59

# ── Accounts ────────────────────────────────────────────────────────────

# All three calendars get swept (per MEMORY: calendar-scan-all-three).
CALENDAR_PROFILES = ["growthpro", "locafy", "wonderly"]

# Inbox signal pulls from growthpro primary inbox only
# (per MEMORY: gmail-primary-inbox-only).
INBOX_PROFILE = "growthpro"

# ── Flagged senders ─────────────────────────────────────────────────────

# Senders whose unread messages always surface in the morning brief's inbox
# section. Match is substring on sender email or display name.
FLAGGED_SENDERS = [
    # Locafy leadership
    "paul.harvell@locafy.com",
    "markd@locafy.com",
    "locafy.com",  # catch-all for other Locafy execs
    # Growth Pro team
    # (add as team identity solidifies)
    # Board / advisors
    # (add when known)
]

# Domains we explicitly DON'T want to flag even if they match above (e.g.
# automated notifications from same domain).
FLAGGED_SENDER_EXCLUDES = [
    "notifications@",
    "no-reply@",
    "noreply@",
    "do-not-reply@",
]

# ── Brief delivery ──────────────────────────────────────────────────────

# Jason's iMessage handle — same as meeting-concierge.
IMESSAGE_BRIEF_CHAT_GUID = "any;-;+16185582424"

# iMessage splits long messages; cap to keep formatting clean.
MAX_BRIEF_CHARS = 2500

# ── ClickUp scoping ─────────────────────────────────────────────────────

# How many days back to count yesterday's "shipped" tasks as recent.
YESTERDAY_LOOKBACK_DAYS = 1

# How many days back to count "shipped this week" for the weekly rollup.
WEEKLY_LOOKBACK_DAYS = 7

# ── Local paths ─────────────────────────────────────────────────────────

SKILL_DIR = Path(__file__).resolve().parent
STATE_FILE = SKILL_DIR / "state.json"
