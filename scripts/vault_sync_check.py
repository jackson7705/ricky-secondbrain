#!/usr/bin/env python3
"""vault_sync_check.py — tell the owner when the memory vault stops backing up.

git-sync runs every two minutes and fails quietly: a rejected push or a repo
state it refuses to touch just writes to a log nobody reads. This looks at the
vault itself rather than at the sync job, so it catches every way sync can stop
— including the job not running at all.

Unhealthy means either:
  - commits have been waiting to reach the remote longer than the threshold, or
  - files have been changed but uncommitted longer than the threshold.

Deterministic: no LLM in the loop. Alerts at most once a day while the problem
lasts, and once more when it clears.

    uv run python vault_sync_check.py              # check, notify if unhealthy
    uv run python vault_sync_check.py --dry-run    # check, never notify
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
from shared import load_state, save_state  # noqa: E402

VAULT_DIR = config.MEMORY_DIR.parent
STATE_FILE = config.STATE_DIR / "vault-sync-check-state.json"

STALE_AFTER_HOURS = 6
REALERT_AFTER_HOURS = 24


def _git(vault: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(vault), *args], capture_output=True, text=True, timeout=60
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _age_hours(epoch: str, now: float) -> float:
    return (now - int(epoch)) / 3600 if epoch.isdigit() else 0.0


def inspect(vault: Path, now: float | None = None) -> dict:
    """The vault's backup state, read straight from git. Makes no network call:
    `unpushed` is measured against the last state fetched from the remote."""
    now = now or time.time()
    upstream = _git(vault, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    unpushed = _git(vault, "log", "--format=%ct", "@{u}..HEAD").splitlines() if upstream else []
    dirty = [
        line[3:] for line in _git(vault, "status", "--porcelain").splitlines() if line.strip()
    ]
    # How long uncommitted work has been waiting: age of the oldest changed file
    # that still exists (deleted files have no mtime to read).
    mtimes = [p.stat().st_mtime for name in dirty if (p := vault / name.strip('"')).is_file()]
    return {
        "upstream": upstream,
        "unpushed": len(unpushed),
        "unpushed_hours": _age_hours(unpushed[-1], now) if unpushed else 0.0,
        "dirty": len(dirty),
        "dirty_hours": (now - min(mtimes)) / 3600 if mtimes else 0.0,
        "last_commit_hours": _age_hours(_git(vault, "log", "-1", "--format=%ct"), now),
    }


def problems(state: dict, stale_after: float = STALE_AFTER_HOURS) -> list[str]:
    found: list[str] = []
    if not state["upstream"]:
        found.append("the vault branch has no remote to back up to")
    if state["unpushed"] and state["unpushed_hours"] >= stale_after:
        found.append(
            f"{state['unpushed']} commits have not reached the remote "
            f"(oldest waiting {_span(state['unpushed_hours'])})"
        )
    if state["dirty"] and state["dirty_hours"] >= stale_after:
        found.append(
            f"{state['dirty']} changed files are uncommitted "
            f"(oldest waiting {_span(state['dirty_hours'])})"
        )
    return found


def _span(hours: float) -> str:
    return f"{hours / 24:.0f} days" if hours >= 48 else f"{hours:.0f} hours"


def build_message(found: list[str]) -> str:
    lines = ["Vault backup has stopped.", ""] + [f"- {p}" for p in found]
    lines += ["", "Until this is fixed, recent memory exists only on this Mac."]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Memory vault backup watchdog")
    ap.add_argument("--dry-run", action="store_true", help="check, never notify")
    args = ap.parse_args()

    if not (VAULT_DIR / ".git").exists():
        print(f"{VAULT_DIR} is not a git repository — nothing to check")
        return 0

    found = problems(inspect(VAULT_DIR))
    saved = load_state(STATE_FILE)
    now = time.time()

    if not found:
        print("vault backup healthy")
        if saved.get("alerted_at") and not args.dry_run:
            from notify_owner import notify_owner

            notify_owner("Vault backup is working again.")
            save_state({}, STATE_FILE)
        return 0

    message = build_message(found)
    print(message)
    due = now - saved.get("alerted_at", 0) >= REALERT_AFTER_HOURS * 3600
    if args.dry_run or not due:
        return 1

    from notify_owner import notify_owner

    if notify_owner(message):
        save_state({"alerted_at": now, "problems": found}, STATE_FILE)
    return 1


if __name__ == "__main__":
    sys.exit(main())
