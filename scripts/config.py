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
CHAT_ALLOWED_USERS = os.getenv("CHAT_ALLOWED_USERS", SLACK_OWNER_USER_ID).split(",")

# iMessage / BlueBubbles
BLUEBUBBLES_URL = os.getenv("BLUEBUBBLES_URL", "").rstrip("/")
BLUEBUBBLES_PASSWORD = os.getenv("BLUEBUBBLES_PASSWORD", "")
BLUEBUBBLES_POLL_INTERVAL = float(os.getenv("BLUEBUBBLES_POLL_INTERVAL", "3"))
IMESSAGE_ALLOWED_ADDRESSES = [
    a.strip() for a in os.getenv("IMESSAGE_ALLOWED_ADDRESSES", "").split(",") if a.strip()
]
IMESSAGE_STATE_PATH = DATA_DIR / "state" / "imessage-state.json"

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
