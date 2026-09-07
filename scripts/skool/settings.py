"""Paths + config for the Skool ingest pipeline.

Browser auth state lives OUTSIDE the repo (``~/.secondbrain/skool``) so a
logged-in Skool session can never be committed. Course output lands in
``deliverables/skool/<group>/`` which is gitignored — course material is
someone else's paid IP, it stays local.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"

# --- Credentials / browser state (never in git) ---
STATE_HOME = Path(os.environ.get("SKOOL_STATE_HOME", str(Path.home() / ".secondbrain" / "skool")))
PROFILE_DIR = STATE_HOME / "chrome-profile"
STATE_FILE = STATE_HOME / "storage-state.json"
COOKIES_FILE = STATE_HOME / "cookies.txt"

# --- Output ---
OUTPUT_ROOT = Path(os.environ.get("SKOOL_OUTPUT_ROOT", str(REPO_ROOT / "deliverables" / "skool")))

# --- Browser ---
BASE_URL = "https://www.skool.com"
SESSION = os.environ.get("SKOOL_BROWSER_SESSION", "skool")
NAV_WAIT_MS = int(os.environ.get("SKOOL_NAV_WAIT_MS", "2500"))
POLITE_DELAY_S = float(os.environ.get("SKOOL_POLITE_DELAY_S", "1.5"))

# --- Transcription ---
TRANSCRIBE_MODEL = os.environ.get("SKOOL_TRANSCRIBE_MODEL", "gemini-2.5-flash")
CHUNK_SECONDS = int(os.environ.get("SKOOL_CHUNK_SECONDS", "1200"))  # 20 min
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"

_ENV_FILES = [
    SCRIPTS_DIR / ".env",
    Path.home() / "ai-seo-agent-skills" / ".env",
]

_env_loaded = False


def load_env() -> None:
    """Populate os.environ from the known .env files (existing vars win)."""
    global _env_loaded
    if _env_loaded:
        return
    for path in _ENV_FILES:
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    _env_loaded = True


def gemini_key() -> str | None:
    load_env()
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")


def group_dir(group: str) -> Path:
    return OUTPUT_ROOT / group


def ensure_dirs(group: str) -> Path:
    root = group_dir(group)
    for sub in ("raw", "lessons", "audio", "transcripts", "notes"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    STATE_HOME.mkdir(parents=True, exist_ok=True)
    return root
