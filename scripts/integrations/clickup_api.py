"""
ClickUp Direct Integration for Second Brain.

Queries the ClickUp REST API with a Personal API Token. Used by the heartbeat
to surface overdue / due-soon tasks for the authenticated user (Jason) within
the Locafy workspace.

Setup:
    1. Get a Personal API Token from https://app.clickup.com/settings/apps
       (look for "API Token" → "Generate"). Token starts with `pk_`.
    2. Add to .claude/scripts/.env:
           CLICKUP_API_TOKEN=pk_...
           CLICKUP_WORKSPACE_ID=<workspace-id>
           # Optional: CLICKUP_LIST_IDS=123,456   (scope queries to these lists)

Usage:
    uv run python -m integrations.clickup_api my-tasks
    uv run python -m integrations.clickup_api overdue
    uv run python -m integrations.clickup_api due-soon --days 3
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Add parent dir for config imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (  # noqa: E402
    CLICKUP_API_TOKEN,
    CLICKUP_LIST_IDS,
    CLICKUP_WORKSPACE_ID,
)
from sanitize import sanitize_external_text  # noqa: E402
from shared import with_retry  # noqa: E402

CLICKUP_API_BASE = "https://api.clickup.com/api/v2"


@dataclass
class ClickUpTask:
    """Represents a ClickUp task."""

    id: str
    name: str
    status: str
    # ClickUp status types: "open", "custom", "done", "closed". Treated as
    # finished work when type is "done" or "closed".
    status_type: str = "open"
    due_on: date | None = None
    list_name: str | None = None
    url: str | None = None

    @property
    def is_finished(self) -> bool:
        return self.status_type in ("done", "closed")


def _headers() -> dict[str, str]:
    """Return auth headers for ClickUp API calls."""
    if not CLICKUP_API_TOKEN:
        raise ValueError(
            "CLICKUP_API_TOKEN not configured.\n"
            "Generate a Personal API Token at https://app.clickup.com/settings/apps "
            "and add `CLICKUP_API_TOKEN=pk_...` to your environment config."
        )
    return {"Authorization": CLICKUP_API_TOKEN}


def _require_workspace() -> str:
    """Return the configured workspace ID or raise with a clear message."""
    if not CLICKUP_WORKSPACE_ID:
        raise ValueError(
            "CLICKUP_WORKSPACE_ID not configured. Add it to your environment "
            "config (the numeric ID from your ClickUp URL)."
        )
    return CLICKUP_WORKSPACE_ID


def _current_user_id() -> int:
    """Resolve the authenticated user's numeric ClickUp ID (cached for session)."""
    global _CACHED_USER_ID
    if _CACHED_USER_ID is not None:
        return _CACHED_USER_ID

    import httpx

    resp = with_retry(
        lambda: httpx.get(
            f"{CLICKUP_API_BASE}/user",
            headers=_headers(),
            timeout=10,
        )
    )
    resp.raise_for_status()
    _CACHED_USER_ID = int(resp.json()["user"]["id"])
    return _CACHED_USER_ID


_CACHED_USER_ID: int | None = None


def _parse_task(raw: dict[str, Any]) -> ClickUpTask:
    """Convert the ClickUp task JSON shape into our ClickUpTask dataclass."""
    due_on: date | None = None
    due_raw = raw.get("due_date")
    if due_raw:
        try:
            # ClickUp due dates are ms-epoch strings.
            due_on = datetime.fromtimestamp(int(due_raw) / 1000, tz=timezone.utc).date()
        except (TypeError, ValueError):
            due_on = None

    status_obj = raw.get("status") or {}
    if isinstance(status_obj, dict):
        status_name = status_obj.get("status") or "unknown"
        status_type = status_obj.get("type") or "open"
    else:
        status_name = str(status_obj) or "unknown"
        status_type = "open"

    list_obj = raw.get("list") or {}
    list_name = list_obj.get("name") if isinstance(list_obj, dict) else None

    return ClickUpTask(
        id=str(raw.get("id", "")),
        name=sanitize_external_text(str(raw.get("name", "")), "clickup"),
        status=status_name,
        status_type=status_type,
        due_on=due_on,
        list_name=list_name,
        url=raw.get("url"),
    )


def get_my_tasks(
    include_closed: bool = False,
    list_ids: list[str] | None = None,
) -> list[ClickUpTask]:
    """
    Return tasks assigned to the authenticated user in the configured workspace.

    Args:
        include_closed: If False (default), skip tasks with a "done/closed" status
                        so the heartbeat doesn't surface already-completed items.
        list_ids:       Optional explicit list scoping. Falls back to
                        `CLICKUP_LIST_IDS` env, or workspace-wide if neither set.
    """
    import httpx

    workspace = _require_workspace()
    user_id = _current_user_id()

    params: dict[str, Any] = {
        "assignees[]": [str(user_id)],
        "include_closed": "true" if include_closed else "false",
        "subtasks": "true",
    }

    target_lists = list_ids if list_ids is not None else CLICKUP_LIST_IDS
    if target_lists:
        params["list_ids[]"] = target_lists

    resp = with_retry(
        lambda: httpx.get(
            f"{CLICKUP_API_BASE}/team/{workspace}/task",
            headers=_headers(),
            params=params,
            timeout=15,
        )
    )
    resp.raise_for_status()

    return [_parse_task(t) for t in resp.json().get("tasks", [])]


def get_overdue_tasks() -> list[ClickUpTask]:
    """Return unfinished tasks whose due date is before today."""
    today = date.today()
    return [
        t for t in get_my_tasks()
        if t.due_on and t.due_on < today and not t.is_finished
    ]


def get_due_soon_tasks(days: int = 3) -> list[ClickUpTask]:
    """Return unfinished tasks due within the next `days` days (inclusive)."""
    today = date.today()
    cutoff = today + timedelta(days=days)
    return [
        t for t in get_my_tasks()
        if t.due_on and today <= t.due_on <= cutoff and not t.is_finished
    ]


def find_list_id_by_name(name_substring: str) -> str | None:
    """Return the first ClickUp list whose name matches `name_substring`.

    Walks spaces → folders → lists in the configured workspace. Match is
    case-insensitive substring on the list name. Used by meeting-concierge
    to route action items to a list without Jason hand-typing GIDs.
    """
    import httpx

    workspace = _require_workspace()
    target = name_substring.strip().lower()
    if not target:
        return None

    # Spaces in workspace
    spaces = with_retry(
        lambda: httpx.get(
            f"{CLICKUP_API_BASE}/team/{workspace}/space",
            headers=_headers(),
            params={"archived": "false"},
            timeout=15,
        )
    )
    spaces.raise_for_status()
    for space in spaces.json().get("spaces", []):
        space_id = space["id"]
        # Folderless lists
        folderless = with_retry(
            lambda sid=space_id: httpx.get(
                f"{CLICKUP_API_BASE}/space/{sid}/list",
                headers=_headers(),
                params={"archived": "false"},
                timeout=15,
            )
        )
        if folderless.status_code == 200:
            for lst in folderless.json().get("lists", []):
                if target in (lst.get("name") or "").lower():
                    return lst["id"]
        # Folders → lists
        folders = with_retry(
            lambda sid=space_id: httpx.get(
                f"{CLICKUP_API_BASE}/space/{sid}/folder",
                headers=_headers(),
                params={"archived": "false"},
                timeout=15,
            )
        )
        if folders.status_code != 200:
            continue
        for folder in folders.json().get("folders", []):
            for lst in folder.get("lists", []):
                if target in (lst.get("name") or "").lower():
                    return lst["id"]
    return None


def create_task(
    list_id: str,
    name: str,
    description: str = "",
    due_on: date | None = None,
    assignees: list[int] | None = None,
    priority: int | None = None,
) -> ClickUpTask:
    """Create a ClickUp task in the given list.

    Priority: 1=urgent, 2=high, 3=normal, 4=low.
    Due is a date (not datetime) — converted to end-of-day UTC ms internally.
    """
    import httpx

    body: dict[str, Any] = {"name": name}
    if description:
        body["description"] = description
    if assignees:
        body["assignees"] = assignees
    if priority:
        body["priority"] = priority
    if due_on:
        # ClickUp wants ms since epoch; use end-of-day UTC so tasks don't fall
        # off the due-date boundary in Jason's timezone edge cases.
        dt = datetime(due_on.year, due_on.month, due_on.day, 23, 59, 59)
        body["due_date"] = int(dt.timestamp() * 1000)
        body["due_date_time"] = True

    resp = with_retry(
        lambda: httpx.post(
            f"{CLICKUP_API_BASE}/list/{list_id}/task",
            headers=_headers(),
            json=body,
            timeout=20,
        )
    )
    resp.raise_for_status()
    return _parse_task(resp.json())


def format_tasks_for_context(tasks: list[ClickUpTask], max_chars: int = 2000) -> str:
    """Format tasks for inclusion in Claude's context prompt."""
    if not tasks:
        return "No tasks."

    output: list[str] = []
    chars = 0
    for t in tasks:
        due = t.due_on.isoformat() if t.due_on else "no due date"
        list_tag = f" [{t.list_name}]" if t.list_name else ""
        entry = f"- **{t.name}**{list_tag} — due {due} (status: {t.status})"
        if chars + len(entry) > max_chars:
            output.append(f"\n... and {len(tasks) - len(output)} more tasks")
            break
        output.append(entry)
        chars += len(entry)
    return "\n".join(output)


# CLI for testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="ClickUp integration")
    parser.add_argument("command", choices=["my-tasks", "overdue", "due-soon", "whoami"])
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--include-closed", action="store_true")
    args = parser.parse_args()

    if args.command == "whoami":
        print(f"Authenticated user ID: {_current_user_id()}")
    elif args.command == "my-tasks":
        tasks = get_my_tasks(include_closed=args.include_closed)
        print(f"{len(tasks)} tasks assigned to you\n")
        print(format_tasks_for_context(tasks))
    elif args.command == "overdue":
        tasks = get_overdue_tasks()
        print(f"{len(tasks)} overdue tasks\n")
        print(format_tasks_for_context(tasks))
    elif args.command == "due-soon":
        tasks = get_due_soon_tasks(days=args.days)
        print(f"{len(tasks)} tasks due within {args.days} days\n")
        print(format_tasks_for_context(tasks))
