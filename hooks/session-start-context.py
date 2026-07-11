"""
Session Start Context Injection Hook

Called by Claude Code when a session starts. Reads key memory files and
outputs a context summary as JSON on stdout, which Claude Code injects
into the assistant's context.

This hook does NO API calls — pure local file reads for speed (<15s).
"""

from __future__ import annotations

import json
import re
import sys
import time as _time
from datetime import datetime
from pathlib import Path

# Add scripts directory to path for config imports
_scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_scripts_dir))

from config import DAILY_DIR, MEMORY_DIR, now_local  # noqa: E402
from shared import log_hook_execution  # noqa: E402

# === Constants ===
MAX_DAILY_LOG_LINES = 30
MAX_CONTEXT_CHARS = 20_000  # ~5,000 tokens — 2.5% of 200K context window
RESUME_MAX_CHARS = 20_000  # Full context for all session types


def read_file_safe(path: Path) -> str:
    """Read a file, returning empty string if it doesn't exist."""
    try:
        if path.exists():
            return path.read_text(encoding="utf-8")
    except Exception:
        pass
    return ""


def get_recent_daily_log(max_lines: int = MAX_DAILY_LOG_LINES) -> str:
    """Read the tail of today's daily log, falling back to yesterday's."""
    today = now_local().strftime("%Y-%m-%d")
    today_log = DAILY_DIR / f"{today}.md"

    content = read_file_safe(today_log)
    if content:
        lines = content.strip().splitlines()
        if len(lines) > max_lines:
            lines = lines[-max_lines:]
        return "\n".join(lines)

    # Fall back to yesterday
    from datetime import timedelta

    yesterday = (now_local() - timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday_log = DAILY_DIR / f"{yesterday}.md"
    content = read_file_safe(yesterday_log)
    if content:
        lines = content.strip().splitlines()
        if len(lines) > max_lines:
            lines = lines[-max_lines:]
        return "(Yesterday's log)\n" + "\n".join(lines)

    return ""


def build_context(source: str) -> str:
    """Build the context string to inject into Claude's session.

    Args:
        source: The session start source (startup, resume, clear, compact)
    """
    parts: list[str] = []

    # Inject day of week + date so Claude always knows what day it is
    today = now_local()
    parts.append(f"## Today\n{today.strftime('%A, %B')} {today.day}, {today.strftime('%Y')}")

    # First-run onboarding — if BOOTSTRAP.md exists, inject it as the first section
    bootstrap = read_file_safe(MEMORY_DIR / "BOOTSTRAP.md")
    if bootstrap:
        parts.append("## BOOTSTRAP (First-Run Onboarding)\n" + bootstrap.strip())

    # Core personality and behavioral guidelines
    soul = read_file_safe(MEMORY_DIR / "SOUL.md")
    if soul:
        parts.append("## Soul\n" + soul.strip())

    # Who the user is — preferences, schedule, team, integrations
    user = read_file_safe(MEMORY_DIR / "USER.md")
    if user:
        parts.append("## User\n" + user.strip())

    # Active projects and key decisions from MEMORY.md
    memory = read_file_safe(MEMORY_DIR / "MEMORY.md")
    if memory:
        parts.append("## Long-Term Memory\n" + memory.strip())

    # Recent daily log entries
    daily = get_recent_daily_log()
    if daily:
        parts.append("## Recent Daily Log\n" + daily.strip())

    context = "\n\n---\n\n".join(parts)

    # Truncate based on source — resume/compact already have context
    max_chars = RESUME_MAX_CHARS if source in ("resume", "compact") else MAX_CONTEXT_CHARS
    if len(context) > max_chars:
        context = context[:max_chars]
        # Truncate at last complete line
        last_newline = context.rfind("\n")
        if last_newline > 0:
            context = context[:last_newline]

    return context


def main() -> None:
    """Main hook entry point. Reads stdin, builds context, outputs JSON on stdout."""
    _start = _time.time()

    # Read hook input from stdin
    # Claude Code on Windows may pass paths with unescaped backslashes (e.g. C:\Users\...)
    # which are invalid JSON. Try normal parse first; on failure, escape lone backslashes.
    try:
        raw_input = sys.stdin.read()
        try:
            hook_input: dict[str, object] = json.loads(raw_input)
        except json.JSONDecodeError:
            fixed_input = re.sub(r'(?<!\\)\\(?!["\\])', r'\\\\', raw_input)
            hook_input = json.loads(fixed_input)
    except (json.JSONDecodeError, ValueError) as e:
        # If we can't parse input, output empty context and exit cleanly
        log_hook_execution("session-start", "unknown", "ERROR", _time.time() - _start, str(e))
        sys.exit(0)

    source = hook_input.get("source", "startup")
    if not isinstance(source, str):
        source = "startup"

    # Build context from memory files
    context = build_context(source)

    if not context.strip():
        log_hook_execution("session-start", source, "SKIP", _time.time() - _start, "empty context")
        sys.exit(0)

    # Output JSON for Claude Code to inject as context
    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }

    # CRITICAL: Only valid JSON on stdout. No other output.
    json.dump(output, sys.stdout)
    log_hook_execution("session-start", source, "OK", _time.time() - _start, f"{len(context)} chars")


if __name__ == "__main__":
    main()
