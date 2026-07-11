#!/usr/bin/env python3
"""fathom_sweep.py — pull action items from recent Fathom meetings and file them
as ClickUp tasks so meeting to-dos never slip. Fathom already extracts the action
items (structured), so no LLM needed here. Dedupes; reports via iMessage.

DRY-RUN by default. `--apply` auto-creates the tasks + texts Jason.

    uv run python fathom_sweep.py --dry-run
    uv run python fathom_sweep.py --apply
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent / ".env")

FATHOM_BASE = "https://api.fathom.ai/external/v1"
DATA = Path(__file__).resolve().parent.parent / "data" / "state"
STATE = DATA / "fathom-sweep-state.json"
from config import CLICKUP_INBOX_LIST_ID as INBOX_LIST_ID  # noqa: E402
from config import CLICKUP_OWNER_UID as OWNER_UID  # noqa: E402
from config import OWNER_EMAILS  # noqa: E402
LOOKBACK_DAYS = 3


def _fetch_meetings() -> list[dict]:
    import os
    import httpx
    key = os.environ.get("FATHOM_API_KEY")
    if not key:
        print("  [fathom] FATHOM_API_KEY not set")
        return []
    r = httpx.get(f"{FATHOM_BASE}/meetings", headers={"X-Api-Key": key},
                  params={"limit": 25, "include_action_items": "true"}, timeout=30)
    r.raise_for_status()
    return r.json().get("items", [])


def _existing_task_names() -> list[str]:
    import os
    try:
        import redis
        r = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
        return [json.loads(r.execute_command("JSON.GET", k, "$.name"))[0].lower()
                for k in r.scan_iter("task:*", count=2000)]
    except Exception:  # noqa: BLE001
        return []


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def _is_dupe(title: str, existing: list[str], sigs: set[str]) -> bool:
    n = _norm(title)
    if n in sigs:
        return True
    return any(difflib.SequenceMatcher(None, n, name).ratio() >= 0.72 or n in name or name in n
               for name in existing)


def _load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except ValueError:
            pass
    return {"created_signatures": [], "last_run": None}


def main(dry_run: bool) -> int:
    st = _load_state()
    sigs = set(st.get("created_signatures", []))
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)

    items = []
    for m in _fetch_meetings():
        start = m.get("recording_start_time") or ""
        try:
            if start and datetime.fromisoformat(start.replace("Z", "+00:00")) < cutoff:
                continue
        except ValueError:
            pass
        for a in (m.get("action_items") or []):
            if a.get("completed"):
                continue
            desc = (a.get("description") or "").strip()
            if not desc:
                continue
            asg = a.get("assignee") or {}
            name = (asg.get("name") or "").strip()
            email = (asg.get("email") or "").lower()
            first_name = OWNER_EMAILS[0].split("@")[0].split(".")[0] if OWNER_EMAILS else ""
            is_owner = (first_name and first_name in name.lower()) or (email and email in OWNER_EMAILS)
            # File only the owner's own action items + unassigned ones (their to-dos).
            # Others' items belong on their plates — skip to avoid noise.
            if name and not is_owner:
                continue
            items.append({"desc": desc, "meeting": m.get("meeting_title") or m.get("title") or "meeting",
                          "date": start[:10], "ts": a.get("recording_timestamp") or "",
                          "url": a.get("recording_playback_url") or "", "assignee": name})

    existing = _existing_task_names()
    fresh = [it for it in items if not _is_dupe(it["desc"], existing, sigs)]
    print(f"pulled {len(items)} open action item(s) from meetings (last {LOOKBACK_DAYS}d); "
          f"{len(fresh)} new after dedup:\n")
    for it in fresh:
        who = f" [{it['assignee']}]" if it["assignee"] else ""
        print(f"  • {it['desc']}{who}\n      ({it['meeting']}, {it['date']} @ {it['ts']})")

    if dry_run:
        print("\n(DRY-RUN — no tasks created.)")
        return 0

    from integrations.clickup_api import create_task
    created = []
    for it in fresh:
        note = f"From meeting '{it['meeting']}' ({it['date']} @ {it['ts']})"
        if it["url"]:
            note += f"\n{it['url']}"
        if it["assignee"]:
            note += f"\nFathom assignee: {it['assignee']}"
        try:
            create_task(INBOX_LIST_ID, it["desc"][:120], description=note,
                        assignees=[int(OWNER_UID)] if OWNER_UID else [])
            created.append(it)
            sigs.add(_norm(it["desc"]))
        except Exception as exc:  # noqa: BLE001
            print(f"  [error] create '{it['desc'][:40]}': {str(exc)[:60]}")

    DATA.mkdir(parents=True, exist_ok=True)
    st["created_signatures"] = list(sigs)[-2000:]
    st["last_run"] = datetime.now().isoformat(timespec="seconds")
    STATE.write_text(json.dumps(st, indent=2))
    print(f"\ncreated {len(created)} ClickUp task(s) from meeting action items")
    if created:
        _report(created)
    return 0


def _report(created: list[dict]) -> None:
    from notify_owner import notify_owner
    lines = [f"🎙️ Meeting action items — filed {len(created)} task(s) from Fathom:"]
    for it in created:
        lines.append(f"• {it['desc'][:80]} ({it['meeting'][:30]})")
    lines.append("\nAll in your ClickUp Inbox. Reply if any shouldn't be there.")
    notify_owner("\n".join(lines)[:1400])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--apply", dest="dry_run", action="store_false")
    sys.exit(main(ap.parse_args().dry_run))
