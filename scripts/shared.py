"""
Shared utilities for Second Brain scripts.

Centralizes code that was duplicated across heartbeat.py, memory_reflect.py,
and memory_flush.py: security patterns, state management, daily log helpers,
and file locking.
"""

from __future__ import annotations

import contextlib
import json
import re
import sys
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from config import STATE_DIR, get_today_log_path, now_local

if TYPE_CHECKING:
    from claude_agent_sdk import HookContext, HookInput
    from claude_agent_sdk.types import SyncHookJSONOutput


# =============================================================================
# DANGEROUS COMMAND PATTERNS - Block these in PreToolUse hook
# =============================================================================

DANGEROUS_BASH_PATTERNS: list[str] = [
    # Destructive file operations
    "rm -rf /",
    "rm -rf ~",
    "rm -rf /*",
    "rm -rf .",
    "rm -rf *",
    # Disk operations
    "> /dev/sda",
    "> /dev/hda",
    "dd if=/dev/zero",
    "dd if=/dev/random",
    "mkfs.",
    # Fork bombs and system attacks
    ":(){:|:&};:",
    ":(){ :|:& };:",
    # Dangerous downloads and execution
    "curl | sh",
    "curl | bash",
    "wget | sh",
    "wget | bash",
    # Permission disasters
    "chmod -R 777 /",
    "chmod -R 000 /",
    "chown -R",
    # History and credential theft
    "history -c",
    # Network attacks
    "> /dev/tcp",
    # Data destruction
    "truncate -s 0",
    "shred",
]


async def validate_bash_command(
    input_data: HookInput,
    tool_use_id: str | None,
    context: HookContext,
) -> SyncHookJSONOutput:
    """PreToolUse hook to validate bash commands and block dangerous ones."""
    tool_input = input_data.get("tool_input")
    command: str = tool_input.get("command", "") if isinstance(tool_input, dict) else ""

    # Normalize: collapse whitespace
    normalized = " ".join(command.split())

    # Also check inside subshell constructs
    commands_to_check = [normalized]
    # Extract $(...) content
    subshells = re.findall(r'\$\(([^)]+)\)', normalized)
    commands_to_check.extend(subshells)
    # Extract backtick content
    backticks = re.findall(r'`([^`]+)`', normalized)
    commands_to_check.extend(backticks)

    for cmd in commands_to_check:
        # Strip common binary path prefixes
        stripped = re.sub(r'(?:/usr)?/s?bin/', '', cmd)

        for pattern in DANGEROUS_BASH_PATTERNS:
            if pattern in stripped:
                print(f"[SECURITY] Blocked dangerous command: {pattern}")
                return {"decision": "block", "reason": f"Blocked dangerous command pattern: {pattern}"}

    return {}


# =============================================================================
# STATE MANAGEMENT
# =============================================================================


def load_state(state_file: Path) -> dict[str, Any]:
    """Load state from a JSON file with error handling."""
    if state_file.exists():
        try:
            data: dict[str, Any] = json.loads(state_file.read_text(encoding="utf-8"))
            return data
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(state: dict[str, Any], state_file: Path) -> None:
    """Save state to a JSON file."""
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


# =============================================================================
# RETRY UTILITY
# =============================================================================


def with_retry(
    func: Any,
    max_retries: int = 3,
    backoff: float = 1.0,
) -> Any:
    """Call func(), retry on transient errors with exponential backoff.

    Retries on: ConnectionError, TimeoutError, HTTP 429/500/502/503.
    """
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            # Check for retryable HTTP errors
            retryable = isinstance(e, (ConnectionError, TimeoutError))
            if hasattr(e, "resp") and hasattr(e.resp, "status"):
                retryable = e.resp.status in (429, 500, 502, 503)
            if hasattr(e, "status_code"):
                retryable = e.status_code in (429, 500, 502, 503)
            if not retryable:
                raise
            time.sleep(backoff * (2 ** attempt))


# =============================================================================
# DAILY LOG HELPERS
# =============================================================================


def _create_daily_log(log_path: Path) -> None:
    """Create a new daily log with YAML frontmatter and standardized sections."""
    from config import DAILY_LOG_SECTIONS
    from vault_linker import daily_frontmatter

    date_str = now_local().strftime("%Y-%m-%d")
    header = daily_frontmatter(date_str)
    header += f"# Daily Log: {date_str}\n\n"
    for section in DAILY_LOG_SECTIONS:
        header += f"## {section}\n\n"
    log_path.write_text(header, encoding="utf-8")


def append_to_daily_log(content: str, section_name: str = "Entry") -> None:
    """Append content to today's daily log under a named section.

    Wraps known entities (people, projects, vendors, concepts) in [[wikilinks]]
    so each entry contributes to Obsidian's graph view instead of producing
    isolated nodes.
    """
    from vault_linker import wrap_entities

    log_path = get_today_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Prevent external data from breaking daily log structure, then wikilink.
    safe_content = content.replace("</external_data>", "&lt;/external_data&gt;")
    linked_content = wrap_entities(safe_content)

    with file_lock(log_path, timeout=5.0):
        timestamp = now_local().strftime("%H:%M")

        if not log_path.exists():
            _create_daily_log(log_path)

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"### {section_name} ({timestamp})\n\n{linked_content}\n\n")


# =============================================================================
# HOOK EXECUTION LOGGING
# =============================================================================

HOOK_LOG_FILE = STATE_DIR / "hook-execution.log"
HOOK_LOG_MAX_LINES = 1000
HOOK_LOG_KEEP_LINES = 500


def log_hook_execution(
    hook_name: str,
    trigger: str,
    status: str,
    duration_s: float,
    detail: str = "",
) -> None:
    """Append a line to the hook execution log with simple rotation."""
    timestamp = now_local().isoformat()
    line = f"{timestamp} | {hook_name} | {trigger} | {status} | {duration_s:.1f}s"
    if detail:
        line += f" | {detail}"

    try:
        HOOK_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Rotate if too large
        if HOOK_LOG_FILE.exists():
            lines = HOOK_LOG_FILE.read_text(encoding="utf-8").splitlines()
            if len(lines) >= HOOK_LOG_MAX_LINES:
                HOOK_LOG_FILE.write_text(
                    "\n".join(lines[-HOOK_LOG_KEEP_LINES:]) + "\n",
                    encoding="utf-8",
                )

        with open(HOOK_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass  # Hook logging must never crash the hook itself


# =============================================================================
# FILE LOCKING (cross-platform)
# =============================================================================


@contextlib.contextmanager
def file_lock(lock_path: Path, timeout: float = 30.0) -> Iterator[None]:
    """Cross-platform file lock using a .lock file.

    Uses msvcrt on Windows, fcntl on Unix.
    Raises TimeoutError if the lock cannot be acquired within timeout seconds.
    """
    lock_file = lock_path.with_suffix(lock_path.suffix + ".lock")
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock_file, "w", encoding="utf-8")  # noqa: SIM115
    acquired = False
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Could not acquire lock on {lock_file} within {timeout}s"
                    )
                time.sleep(0.1)
        yield
    finally:
        if acquired:
            if sys.platform == "win32":
                import msvcrt

                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        f.close()
