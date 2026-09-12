"""
Configuration for the Second Brain heartbeat system.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Load environment variables from .env in scripts directory.
# `override=True` makes the project's .env the source of truth — it wins over
# any values already present in the shell environment (e.g. stale `export`s in
# ~/.zshrc). Without this, a shell-level var silently masks a fresh .env edit.
load_dotenv(Path(__file__).parent / ".env", override=True)

# === Paths ===
SCRIPTS_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPTS_DIR.parent.parent  # dynamous-engine
CLAUDE_DIR = PROJECT_ROOT / ".claude"
MEMORY_DIR = PROJECT_ROOT / "Dynamous" / "Memory"

# Memory file paths
SOUL_FILE = MEMORY_DIR / "SOUL.md"
USER_FILE = MEMORY_DIR / "USER.md"
MEMORY_FILE = MEMORY_DIR / "MEMORY.md"
HEARTBEAT_FILE = MEMORY_DIR / "HEARTBEAT.md"
DAILY_DIR = MEMORY_DIR / "daily"

# === Owner Identity ===
OWNER_NAME = os.getenv("OWNER_NAME", "")

# === Data Directory (databases, model caches) ===
DATA_DIR = CLAUDE_DIR / "data"
DATABASE_PATH = DATA_DIR / "memory.db"
DATABASE_URL = os.getenv("DATABASE_URL", "")

# State files — per-machine operational data, NOT synced via Obsidian
STATE_DIR = DATA_DIR / "state"
HEARTBEAT_STATE_FILE = STATE_DIR / "heartbeat-state.json"

# === Reflection Configuration ===
REFLECTION_STATE_FILE = STATE_DIR / "reflection-state.json"
REFLECTION_HOUR = int(os.getenv("REFLECTION_HOUR", "8"))

# === Embedding Configuration ===
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384
EMBEDDING_CACHE_DIR = DATA_DIR / "models"

# === Integration Configuration (Phase 5) ===
INTEGRATIONS_DIR = SCRIPTS_DIR / "integrations"

# Google OAuth
GOOGLE_CREDENTIALS_FILE = INTEGRATIONS_DIR / "google_credentials.json"
# Legacy single-account token path (still supported when no profile is specified
# and DEFAULT_GOOGLE_ACCOUNT is unset — keeps stock setups working).
GOOGLE_TOKEN_FILE = INTEGRATIONS_DIR / "google_token.json"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    # drive.file — per-file access for files the app creates/opens.
    # Added 2026-04-19 for `invoice-router` to upload receipt PDFs into the
    # Locafy/Wonderly expense folders without needing full drive access.
    "https://www.googleapis.com/auth/drive.file",
]

# Multi-profile Google support: each profile gets its own token file
# (e.g., google_token_growthpro.json). Default profile used when callers
# don't pass an explicit account.
DEFAULT_GOOGLE_ACCOUNT = os.getenv("DEFAULT_GOOGLE_ACCOUNT", "").strip()


def google_token_file(account: str | None = None) -> Path:
    """
    Resolve the OAuth token file path for a Google profile.

    - If `account` is provided, returns `google_token_<account>.json`.
    - Else if `DEFAULT_GOOGLE_ACCOUNT` is set, uses that profile.
    - Else falls back to the legacy single-account `google_token.json`.
    """
    profile = account or DEFAULT_GOOGLE_ACCOUNT
    if not profile:
        return GOOGLE_TOKEN_FILE
    return INTEGRATIONS_DIR / f"google_token_{profile}.json"


def list_google_profiles() -> list[str]:
    """Return profile names with a saved token file (e.g. ['growthpro', 'locafy'])."""
    if not INTEGRATIONS_DIR.exists():
        return []
    profiles: list[str] = []
    for path in INTEGRATIONS_DIR.glob("google_token_*.json"):
        name = path.stem.removeprefix("google_token_")
        if name:
            profiles.append(name)
    return sorted(profiles)

# ClickUp — Locafy task tracking (Asana removed — not used in this workspace)
CLICKUP_API_TOKEN = os.getenv("CLICKUP_API_TOKEN", "")
CLICKUP_WORKSPACE_ID = os.getenv("CLICKUP_WORKSPACE_ID", "")
# Optional: comma-separated ClickUp list IDs to monitor. If unset, integration
# queries "all tasks assigned to me" across the workspace.
CLICKUP_LIST_IDS = [s.strip() for s in os.getenv("CLICKUP_LIST_IDS", "").split(",") if s.strip()]
# Owner's ClickUp user id (task assignee) + the "Inbox" list where autonomous
# jobs (loose_ends, fathom_sweep) file captured to-dos. Per-owner — set in .env.
CLICKUP_OWNER_UID = os.getenv("CLICKUP_OWNER_UID", "").strip()
CLICKUP_INBOX_LIST_ID = os.getenv("CLICKUP_INBOX_LIST_ID", "").strip()

# LinkedIn (aeo-authority-content publish path)
LINKEDIN_CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "")
LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "")
# `w_member_social` lets us post shares on Jason's behalf. `openid profile`
# gives us his member URN (needed as the post's author field).
LINKEDIN_SCOPES = ["openid", "profile", "w_member_social"]

# Slack
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_NOTIFICATION_CHANNEL = os.getenv("SLACK_NOTIFICATION_CHANNEL", "#second-brain")
SLACK_MONITORED_CHANNELS = os.getenv("SLACK_MONITORED_CHANNELS", "second-brain").split(",")
SLACK_OWNER_USER_ID = os.getenv("SLACK_OWNER_USER_ID", "")

# Multi-workspace Slack support.
# Tokens are read from env vars of the form SLACK_BOT_TOKEN_<WORKSPACE> (uppercase).
# Workspace-scoped settings use the same pattern, e.g.:
#   SLACK_MONITORED_CHANNELS_GROWTHPRO="general,leads"
#   SLACK_OWNER_USER_ID_GROWTHPRO="U12345"
# `SLACK_WORKSPACES` is the map of lower-cased workspace name -> bot token.
# If no workspace-suffixed tokens are set, we fall back to the legacy single
# SLACK_BOT_TOKEN so existing setups keep working.
SLACK_WORKSPACES: dict[str, str] = {}
_SLACK_WORKSPACE_PREFIX = "SLACK_BOT_TOKEN_"
for _env_key, _env_val in os.environ.items():
    if _env_key.startswith(_SLACK_WORKSPACE_PREFIX) and _env_val:
        _ws_name = _env_key.removeprefix(_SLACK_WORKSPACE_PREFIX).lower()
        if _ws_name:
            SLACK_WORKSPACES[_ws_name] = _env_val

DEFAULT_SLACK_WORKSPACE = os.getenv("DEFAULT_SLACK_WORKSPACE", "").strip().lower()


def slack_token_for(workspace: str | None = None) -> str:
    """
    Resolve the Slack bot token for a workspace.

    Lookup order:
    1. Explicit `workspace` arg.
    2. `DEFAULT_SLACK_WORKSPACE` env var.
    3. Legacy single-token `SLACK_BOT_TOKEN`.

    Returns empty string if nothing is configured.
    """
    name = (workspace or DEFAULT_SLACK_WORKSPACE).lower()
    if name and name in SLACK_WORKSPACES:
        return SLACK_WORKSPACES[name]
    if not name and SLACK_WORKSPACES:
        # No default set — fall back to the only workspace if there's exactly one
        if len(SLACK_WORKSPACES) == 1:
            return next(iter(SLACK_WORKSPACES.values()))
    return SLACK_BOT_TOKEN


def slack_workspace_setting(base: str, workspace: str | None, default: str = "") -> str:
    """
    Look up a workspace-scoped env var, falling back to the un-suffixed base var.
    E.g. slack_workspace_setting("SLACK_MONITORED_CHANNELS", "growthpro")
    checks SLACK_MONITORED_CHANNELS_GROWTHPRO first, then SLACK_MONITORED_CHANNELS.
    """
    if workspace:
        scoped = os.getenv(f"{base}_{workspace.upper()}", "").strip()
        if scoped:
            return scoped
    return os.getenv(base, default)


def list_slack_workspaces() -> list[str]:
    """Return configured Slack workspace names (lowercase)."""
    return sorted(SLACK_WORKSPACES.keys())

# Chat Interface
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN", "")
CHAT_DB_PATH = DATA_DIR / "chat.db"
CHAT_MAX_TURNS = int(os.getenv("CHAT_MAX_TURNS", "500"))
CHAT_MAX_BUDGET_USD = float(os.getenv("CHAT_MAX_BUDGET_USD", "100.0"))
CHAT_INACTIVITY_TIMEOUT_SECONDS = float(os.getenv("CHAT_INACTIVITY_TIMEOUT_SECONDS", "600"))
CHAT_HARD_CEILING_SECONDS = float(os.getenv("CHAT_HARD_CEILING_SECONDS", "1800"))
CHAT_LARGE_TASK_INACTIVITY_TIMEOUT_SECONDS = float(
    os.getenv("CHAT_LARGE_TASK_INACTIVITY_TIMEOUT_SECONDS", "3600")
)
CHAT_LARGE_TASK_HARD_CEILING_SECONDS = float(
    os.getenv("CHAT_LARGE_TASK_HARD_CEILING_SECONDS", "14400")
)
CHAT_PROGRESS_INTERVAL_SECONDS = float(os.getenv("CHAT_PROGRESS_INTERVAL_SECONDS", "300"))

# --- Model selection -------------------------------------------------------
# The Agent SDK ships its own `claude` binary and prefers it over the one on
# PATH. That bundled CLI is pinned at 2.1.114, which predates the Claude 5
# family entirely — its newest opus string is claude-opus-4-7. Left alone, the
# `opus[1m]` alias in ~/.claude/settings.json resolved there, so Ricky ran
# claude-opus-4-7 while Jason's own sessions ran Opus 5 (verified 2026-09-12).
# Pointing cli_path at the system binary is what makes the Claude 5 models
# reachable at all; without it CHAT_MODEL below would silently fail to resolve.
_SYSTEM_CLAUDE_CLI = Path.home() / ".local" / "bin" / "claude"
CHAT_CLI_PATH = os.getenv(
    "CHAT_CLI_PATH",
    str(_SYSTEM_CLAUDE_CLI) if _SYSTEM_CLAUDE_CLI.exists() else "",
)

# Default for ordinary chat turns. Opus 5 — 1M context, and roughly half
# Fable's cost per turn.
CHAT_MODEL = os.getenv("CHAT_MODEL", "claude-opus-5")

# Reserved for jobs the engine classifies as large (decks, long multi-step
# builds, code work). Fable 5.1 is the most capable model available and is
# priced accordingly — measured 2026-09-12, a one-word reply cost $1.08 on
# Fable 5.1 vs $0.45 on Opus 5, because the ~44k-token preamble dominates
# every turn regardless of answer length. Set CHAT_HEAVY_MODEL=claude-opus-5
# to collapse the two tiers back into one.
CHAT_HEAVY_MODEL = os.getenv("CHAT_HEAVY_MODEL", "claude-fable-5-1")

# --- Code workspace --------------------------------------------------------
# Repos Ricky may read and write outside the vault. The chat engine keeps
# cwd = ~/SecondBrain (that is what makes .claude/agents, skills, and settings
# discoverable at all) and grants access to these via the SDK's add_dirs, only
# on code-shaped turns or when a message names one by hand.
#
# This list is the boundary for autonomous work — see skills/ship-code/SKILL.md
# → Autonomy. Deliberately excluded as too load-bearing: unify-api, locafy-crm,
# governance. Add them only with a reason.
REPO_WORKSPACE_ROOT = Path(os.getenv("REPO_WORKSPACE_ROOT", str(Path.home() / "Projects")))
CODE_REPO_ALLOWLIST = [
    r.strip()
    for r in os.getenv(
        "CODE_REPO_ALLOWLIST",
        "mission-control,google-ads-platform,locafy-website,locafy-marketing,triton",
    ).split(",")
    if r.strip()
]
CHAT_ALLOWED_USERS = os.getenv("CHAT_ALLOWED_USERS", SLACK_OWNER_USER_ID).split(",")

# Discord chat surface (works on any OS — unlike BlueBubbles)
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_ALLOWED_USER_IDS = [
    u.strip() for u in os.getenv("DISCORD_ALLOWED_USER_IDS", "").split(",") if u.strip()
]

# Telegram chat surface (works on any OS)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ALLOWED_USER_IDS = [
    u.strip() for u in os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").split(",") if u.strip()
]

# === Owner notifications (where autonomous jobs send one-way pings) ===
# Which surface job notifications go to: bluebubbles | telegram | discord | slack.
# Defaults to bluebubbles if OWNER_PHONE is set (Jason), else the first surface
# that's configured. Lets a Mac-less teammate get pings on Telegram/Discord.
OWNER_NOTIFY_CHANNEL = os.getenv("OWNER_NOTIFY_CHANNEL", "").strip().lower()
# Telegram: the chat id to DM (usually the same as the owner's user id).
OWNER_TELEGRAM_CHAT_ID = os.getenv("OWNER_TELEGRAM_CHAT_ID", "").strip()
# Discord: a webhook URL for one-way notifications (simplest; no bot needed).
OWNER_DISCORD_WEBHOOK_URL = os.getenv("OWNER_DISCORD_WEBHOOK_URL", "").strip()
# Slack: channel/DM id to post notifications to (uses SLACK_BOT_TOKEN).
OWNER_SLACK_NOTIFY_CHANNEL = os.getenv("OWNER_SLACK_NOTIFY_CHANNEL", "").strip()

# iMessage / BlueBubbles
BLUEBUBBLES_URL = os.getenv("BLUEBUBBLES_URL", "").rstrip("/")
BLUEBUBBLES_PASSWORD = os.getenv("BLUEBUBBLES_PASSWORD", "")
BLUEBUBBLES_POLL_INTERVAL = float(os.getenv("BLUEBUBBLES_POLL_INTERVAL", "3"))
IMESSAGE_ALLOWED_ADDRESSES = [
    a.strip() for a in os.getenv("IMESSAGE_ALLOWED_ADDRESSES", "").split(",") if a.strip()
]
IMESSAGE_STATE_PATH = DATA_DIR / "state" / "imessage-state.json"

# === Owner identity (per-person — set these in .env when duplicating Ricky) ===
# The owner's mobile number Ricky texts/reads on iMessage (digits only, incl.
# country code, e.g. 16185582424). Autonomous jobs message this number.
OWNER_PHONE = os.getenv("OWNER_PHONE", "").strip().lstrip("+")
# BlueBubbles chat GUID for the owner's 1:1 thread. Defaults to the standard
# "any;-;+<phone>" form; override OWNER_IMESSAGE_GUID directly for group chats.
OWNER_IMESSAGE_GUID = os.getenv(
    "OWNER_IMESSAGE_GUID", f"any;-;+{OWNER_PHONE}" if OWNER_PHONE else ""
)
# The owner's own email addresses (comma-separated) — used to recognize "their"
# action items / self-assigned to-dos vs. other people's.
OWNER_EMAILS = [e.strip().lower() for e in os.getenv("OWNER_EMAILS", "").split(",") if e.strip()]
# Google Drive folder for briefings/deliverables Ricky produces.
DRIVE_BRIEFINGS_FOLDER_ID = os.getenv("DRIVE_BRIEFINGS_FOLDER_ID", "").strip()

# Calendar
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "")

# Circle
CIRCLE_ADMIN_TOKEN = os.getenv("CIRCLE_ADMIN_TOKEN", "")
CIRCLE_HEADLESS_TOKEN = os.getenv("CIRCLE_HEADLESS_TOKEN", "")
CIRCLE_MEMBER_EMAIL = os.getenv("CIRCLE_MEMBER_EMAIL", "")
CIRCLE_COMMUNITY_MEMBER_ID = int(os.getenv("CIRCLE_COMMUNITY_MEMBER_ID", "0"))

# === Drafts & Habits ===
DRAFTS_DIR = MEMORY_DIR / "drafts"
DRAFTS_ACTIVE_DIR = DRAFTS_DIR / "active"
DRAFTS_SENT_DIR = DRAFTS_DIR / "sent"
DRAFTS_EXPIRED_DIR = DRAFTS_DIR / "expired"
HABITS_FILE = MEMORY_DIR / "HABITS.md"
DRAFT_EXPIRY_HOURS = int(os.getenv("DRAFT_EXPIRY_HOURS", "24"))
EXPIRED_DRAFT_RETENTION_DAYS = int(os.getenv("EXPIRED_DRAFT_RETENTION_DAYS", "7"))

# === Security / Guardrail ===
GUARDRAIL_STATE_FILE = STATE_DIR / "guardrail-state.json"

# === Search Configuration ===
SEARCH_CHUNK_MAX_TOKENS = 400
SEARCH_CHUNK_OVERLAP_TOKENS = 80
SEARCH_VECTOR_WEIGHT = 0.7
SEARCH_KEYWORD_WEIGHT = 0.3
SEARCH_DEFAULT_LIMIT = 10
SEARCH_MIN_SCORE = 0.2

# === Authentication ===
# Claude Agent SDK inherits auth from Claude Code CLI automatically.
# No API key needed - uses credentials stored in ~/.claude/.credentials.json
# Task Scheduler runs as your user, so it has access to your credentials.

# === Heartbeat Configuration ===
HEARTBEAT_INTERVAL_MINUTES = int(os.getenv("HEARTBEAT_INTERVAL_MINUTES", "30"))
HEARTBEAT_ACTIVE_START = os.getenv("HEARTBEAT_ACTIVE_HOURS_START", "08:00")
HEARTBEAT_ACTIVE_END = os.getenv("HEARTBEAT_ACTIVE_HOURS_END", "22:00")
HEARTBEAT_TIMEZONE = os.getenv("HEARTBEAT_TIMEZONE", "America/Chicago")

# === Daily Log Template ===
DAILY_LOG_SECTIONS = ["Sessions", "Heartbeats", "Memory Maintenance"]

# Note: Model is determined by the claude_code system prompt preset
# No need to override - uses your subscription's default model


LOCAL_TZ = ZoneInfo(HEARTBEAT_TIMEZONE)


def now_local() -> datetime:
    """Return the current time in the configured timezone (HEARTBEAT_TIMEZONE)."""
    return datetime.now(LOCAL_TZ)


def get_today_log_path() -> Path:
    """Get path to today's daily log (based on local date)."""
    today = now_local().strftime("%Y-%m-%d")
    return DAILY_DIR / f"{today}.md"


def is_within_active_hours() -> bool:
    """Check if current time is within active hours (local timezone)."""
    current_time = now_local().strftime("%H:%M")
    return HEARTBEAT_ACTIVE_START <= current_time <= HEARTBEAT_ACTIVE_END


def ensure_directories() -> None:
    """Ensure all required directories exist."""
    for directory in [MEMORY_DIR, DAILY_DIR, STATE_DIR, DATA_DIR, INTEGRATIONS_DIR,
                       DRAFTS_ACTIVE_DIR, DRAFTS_SENT_DIR, DRAFTS_EXPIRED_DIR]:
        directory.mkdir(parents=True, exist_ok=True)
