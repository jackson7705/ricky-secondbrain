"""
ClickUp Direct Integration for Second Brain.

Queries the ClickUp REST API. Used by the heartbeat to surface overdue /
due-soon tasks for the authenticated user (Jason) within the Locafy workspace.

Transport (2026-09-13): calls go through `composio proxy --toolkit clickup`,
which injects Jason's managed OAuth credential. The Personal API Token path is
kept as a fallback for machines without the Composio CLI; the PAT in the env
file went 401 on 2026-05-16 and was never replaced, which is why this moved.

Setup:
    1. `composio login` once on the machine (installs to ~/.local/bin).
       Fallback only: a Personal API Token from https://app.clickup.com/settings/apps
    2. Add to .claude/scripts/.env:
           CLICKUP_WORKSPACE_ID=<workspace-id>
           # Optional fallback: CLICKUP_API_TOKEN=pk_...
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
COMPOSIO_TOOLKIT = "clickup"


class ClickUpAPIError(RuntimeError):
    """ClickUp returned an error body ({"err": ..., "ECODE": ...})."""


def _composio_bin() -> str | None:
    import shutil

    found = shutil.which("composio")
    if found:
        return found
    for candidate in (Path.home() / ".local/bin/composio", Path("/opt/homebrew/bin/composio")):
        if candidate.exists():
            return str(candidate)
    return None


def _request(
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    """Single transport for every ClickUp call. Composio proxy first, PAT second.

    Returns the parsed JSON body. Raises ClickUpAPIError on a ClickUp error
    body (the proxy exits 0 even for API errors, so status codes can't be
    trusted; the body's `err` key is the signal).
    """
    import json
    import subprocess
    from urllib.parse import urlencode

    url = f"{CLICKUP_API_BASE}{path}"
    if params:
        url += "?" + urlencode(params, doseq=True)

    composio = _composio_bin()
    if composio:
        cmd = [composio, "proxy", url, "--toolkit", COMPOSIO_TOOLKIT, "-X", method]
        if json_body is not None:
            cmd += ["-H", "content-type: application/json", "-d", json.dumps(json_body)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30)
        raw = proc.stdout.strip()
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise ClickUpAPIError(
                f"composio proxy returned non-JSON for {method} {path}: "
                f"{(raw or proc.stderr)[:300]}"
            ) from exc
        if proc.returncode != 0 and not data:
            raise ClickUpAPIError(f"composio proxy failed: {proc.stderr.strip()[:300]}")
    else:
        import httpx

        if json_body is not None:
            resp = httpx.request(method, url, headers=_headers(), json=json_body, timeout=timeout)
        else:
            resp = httpx.request(method, url, headers=_headers(), timeout=timeout)
        resp.raise_for_status()
        data = resp.json()

    if isinstance(data, dict) and "err" in data:
        raise ClickUpAPIError(f"{data.get('ECODE', 'ERR')}: {data['err']} ({method} {path})")
    return data


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

    data = with_retry(lambda: _request("GET", "/user", timeout=10))
    _CACHED_USER_ID = int(data["user"]["id"])
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

    data = with_retry(
        lambda: _request("GET", f"/team/{workspace}/task", params=params, timeout=15)
    )
    return [_parse_task(t) for t in data.get("tasks", [])]


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
    workspace = _require_workspace()
    target = name_substring.strip().lower()
    if not target:
        return None

    not_archived = {"archived": "false"}
    spaces = with_retry(
        lambda: _request("GET", f"/team/{workspace}/space", params=not_archived, timeout=15)
    )
    for space in spaces.get("spaces", []):
        space_id = space["id"]
        # Folderless lists. A space Jason can't read raises; skip it, don't abort.
        try:
            folderless = with_retry(
                lambda sid=space_id: _request(
                    "GET", f"/space/{sid}/list", params=not_archived, timeout=15
                )
            )
        except ClickUpAPIError:
            folderless = {}
        for lst in folderless.get("lists", []):
            if target in (lst.get("name") or "").lower():
                return lst["id"]
        # Folders → lists
        try:
            folders = with_retry(
                lambda sid=space_id: _request(
                    "GET", f"/space/{sid}/folder", params=not_archived, timeout=15
                )
            )
        except ClickUpAPIError:
            continue
        for folder in folders.get("folders", []):
            for lst in folder.get("lists", []):
                if target in (lst.get("name") or "").lower():
                    return lst["id"]
    return None


def list_task_names(list_id: str, include_closed: bool = True) -> list[str]:
    """Lower-cased names of every task in a list (closed included by default).

    Used by the autonomous jobs (loose_ends, fathom_sweep) for live dedup. The
    Redis mirror lags by hours, so a morning run's task is invisible to the
    evening run unless we ask ClickUp directly. Paginates until last_page.
    """
    names: list[str] = []
    page = 0
    while True:
        params: dict[str, Any] = {"page": page, "subtasks": "true"}
        if include_closed:
            params["include_closed"] = "true"
        data = _request("GET", f"/list/{list_id}/task", params=params)
        tasks = data.get("tasks", []) or []
        names.extend((t.get("name") or "").lower() for t in tasks)
        if data.get("last_page", True) or not tasks:
            break
        page += 1
    return names


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

    data = with_retry(
        lambda: _request("POST", f"/list/{list_id}/task", json_body=body, timeout=20)
    )
    return _parse_task(data)


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
