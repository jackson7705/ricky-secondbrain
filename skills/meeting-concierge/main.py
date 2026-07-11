"""
meeting-concierge orchestrator.

Three subcommands:
  brief   — 15-min-ahead sweep across all three calendars; text Jason a prep brief.
  digest  — pull Fathom action items from recent meetings and stage a proposal.
  apply   — file approved ClickUp tasks + email drafts from the digest queue.

Per Jason's rule, `digest` never writes to ClickUp or sends email directly —
it only stages proposals. `apply` is the explicit confirmation step.

Current status:
- `brief` is live: pulls events, composes a short message, posts to iMessage.
  It intentionally does NOT call the ClickUp API yet for "related tasks" — that
  hop is stubbed because ClickUp live search is better done via the MCP in a
  chat session. Briefs today are calendar + recent email context.
- `digest` and `apply` are scaffolded but skeletal. The Fathom MCP tool names
  aren't known until a Claude Code session loads them; we expose a clean
  queueing interface so the heartbeat/chat can populate it from the Fathom
  side without re-implementing the skill.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_SKILL_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _SKILL_DIR.parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))
sys.path.insert(0, str(_SKILL_DIR))

from meeting_config import (  # noqa: E402
    ACTIVE_HOURS_END,
    ACTIVE_HOURS_START,
    BRIEF_LOOKAHEAD_MINUTES,
    BRIEF_STATE_RETENTION_DAYS,
    CALENDAR_PROFILES,
    EMAIL_LOOKUP_PROFILE,
    IMESSAGE_BRIEF_CHAT_GUID,
    MAX_BRIEF_CHARS,
    PENDING_DIGEST_FILE,
    RECENT_EMAIL_DAYS,
    STATE_FILE,
)


# ── Shared I/O ──────────────────────────────────────────────────────────


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default
    except Exception as e:
        print(f"  [warn] couldn't parse {path.name}: {e} — using default")
        return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def _in_active_hours(now: datetime | None = None) -> bool:
    from zoneinfo import ZoneInfo

    now = now or datetime.now(ZoneInfo("America/Chicago"))
    return ACTIVE_HOURS_START <= now.hour < ACTIVE_HOURS_END


# ── iMessage (outbound brief) ───────────────────────────────────────────


def _post_imessage(text: str) -> bool:
    """Post an iMessage to Jason via the BlueBubbles REST API.

    The chat service polls BlueBubbles for inbound messages; outbound briefs
    don't need to go through the chat engine — a direct REST call is simpler
    and one-shot (no conversational state).
    """
    import urllib.parse
    import urllib.request

    from config import BLUEBUBBLES_PASSWORD, BLUEBUBBLES_URL

    if not BLUEBUBBLES_URL or not BLUEBUBBLES_PASSWORD:
        print("  [skip] BLUEBUBBLES_URL / PASSWORD not set — brief not sent")
        return False

    url = f"{BLUEBUBBLES_URL}/api/v1/message/text?password={urllib.parse.quote(BLUEBUBBLES_PASSWORD)}"
    body = json.dumps(
        {
            "chatGuid": IMESSAGE_BRIEF_CHAT_GUID,
            "message": text[:MAX_BRIEF_CHARS],
            "method": "apple-script",
            "tempGuid": f"brief-{int(datetime.now().timestamp() * 1000)}",
        }
    ).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if 200 <= resp.status < 300:
                return True
            print(f"  [warn] BlueBubbles returned HTTP {resp.status}")
            return False
    except Exception as e:
        print(f"  [warn] failed to send iMessage brief: {e}")
        return False


# ── Calendar sweep ──────────────────────────────────────────────────────


@dataclass
class UpcomingEvent:
    id: str
    profile: str
    title: str
    starts_at: datetime
    attendees: list[str]
    location: str | None
    description: str | None


def _sweep_upcoming() -> list[UpcomingEvent]:
    """Return events starting within BRIEF_LOOKAHEAD_MINUTES across all profiles."""
    from integrations.auth import set_active_account
    from integrations.calendar_api import check_for_upcoming_meetings

    out: list[UpcomingEvent] = []
    cutoff_minutes = BRIEF_LOOKAHEAD_MINUTES
    for profile in CALENDAR_PROFILES:
        set_active_account(profile)
        try:
            events = check_for_upcoming_meetings(hours_ahead=1)
        except Exception as e:
            print(f"  [warn] calendar fetch failed for {profile}: {e}")
            continue
        finally:
            set_active_account(None)

        now = datetime.now(timezone.utc)
        for ev in events:
            minutes_out = (ev.start.astimezone(timezone.utc) - now).total_seconds() / 60.0
            # Lower bound of 1 min filters "already-started" events we can't
            # usefully brief on; upper bound is our 15-min-ahead target.
            if 1 <= minutes_out <= cutoff_minutes:
                out.append(
                    UpcomingEvent(
                        id=ev.id,
                        profile=profile,
                        title=ev.summary or "(no title)",
                        starts_at=ev.start,
                        attendees=ev.attendees or [],
                        location=ev.location,
                        description=ev.description,
                    )
                )
    return out


# ── Email context ───────────────────────────────────────────────────────


def _recent_email_context(attendees: list[str]) -> str:
    """One-liner per recent email thread that involves any of the attendees."""
    from integrations.auth import set_active_account
    from integrations.gmail import list_emails

    if not attendees:
        return ""

    set_active_account(EMAIL_LOOKUP_PROFILE)
    senders = [a for a in attendees if a and "@" in a]
    if not senders:
        return ""

    # Gmail query: any email from OR to one of the attendees in the last N days
    from_query = " OR ".join(f"from:{a}" for a in senders[:8])
    try:
        emails = list_emails(
            max_results=5,
            hours_ago=RECENT_EMAIL_DAYS * 24,
            query=f"({from_query}) in:inbox",
        )
    except Exception as e:
        print(f"  [warn] email context lookup failed: {e}")
        return ""
    finally:
        set_active_account(None)

    if not emails:
        return ""

    lines = []
    for e in emails[:3]:
        subject = (e.subject or "(no subject)").strip()
        lines.append(f"- {subject[:70]}")
    return "\n".join(lines)


# ── Brief composition ───────────────────────────────────────────────────


def _compose_brief(event: UpcomingEvent) -> str:
    from zoneinfo import ZoneInfo

    local_start = event.starts_at.astimezone(ZoneInfo("America/Chicago"))
    starts_label = local_start.strftime("%-I:%M %p")
    attendee_preview = ", ".join(event.attendees[:3]) or "(no other attendees)"
    if len(event.attendees) > 3:
        attendee_preview += f" +{len(event.attendees) - 3} more"

    parts = [
        f"{event.title} at {starts_label}",
        f"[{event.profile}] {attendee_preview}",
    ]

    if event.location:
        parts.append(f"Where: {event.location}")

    email_ctx = _recent_email_context(event.attendees)
    if email_ctx:
        parts.append("Recent email:")
        parts.append(email_ctx)

    if not event.description:
        parts.append("No agenda doc — want me to draft one?")

    return "\n".join(parts)[:MAX_BRIEF_CHARS]


# ── State helpers ───────────────────────────────────────────────────────


def _prune_state(state: dict[str, Any]) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=BRIEF_STATE_RETENTION_DAYS)).isoformat()
    briefed = state.get("briefed_events", {})
    state["briefed_events"] = {k: v for k, v in briefed.items() if v >= cutoff}


# ── Subcommands ─────────────────────────────────────────────────────────


def run_brief() -> int:
    if not _in_active_hours():
        # Quiet exit outside active window — launchd will keep firing.
        return 0

    state = _load_json(STATE_FILE, {"briefed_events": {}, "last_digest": None})
    _prune_state(state)

    events = _sweep_upcoming()
    if not events:
        _save_json(STATE_FILE, state)
        return 0

    sent = 0
    for ev in events:
        key = f"{ev.profile}:{ev.id}"
        if key in state["briefed_events"]:
            continue
        text = _compose_brief(ev)
        if not _post_imessage(text):
            continue
        state["briefed_events"][key] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        sent += 1

    _save_json(STATE_FILE, state)
    if sent:
        print(f"  [brief] sent {sent} brief(s)")
    return 0


def run_digest(fathom_file: Path | None = None) -> int:
    """Stage proposals from a Fathom action-items dump.

    Expected JSON shape (produced by Ricky via Fathom MCP in a chat session,
    or hand-fed for testing):

        {
          "recording_id": "abc-123",
          "meeting_title": "Locafy <> PartnerX kickoff",
          "meeting_date": "2026-04-19",
          "attendees": ["me@locafy.com", "partner@px.com"],
          "action_items": [
            {
              "text": "Send MSA draft to PartnerX",
              "owner": "jason",
              "due": "2026-04-22",
              "needs_followup_email": true,
              "followup_to": "partner@px.com",
              "followup_subject": "MSA draft — PartnerX",
              "followup_body": "Hey — ...",
            }
          ]
        }
    """
    if fathom_file is None:
        print(
            "digest expects a Fathom JSON file. From chat: have Ricky pull the latest "
            "recording via Fathom MCP and write it to "
            f"{PENDING_DIGEST_FILE.parent / 'fathom-dump.json'}, then pass it with --file."
        )
        return 0

    try:
        payload = json.loads(fathom_file.read_text())
    except Exception as e:
        print(f"  [error] couldn't read {fathom_file}: {e}")
        return 1

    pending = _load_json(PENDING_DIGEST_FILE, [])
    seen_ids = {p["action_id"] for p in pending if "action_id" in p}

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meeting_title = payload.get("meeting_title", "(unknown meeting)")
    meeting_date = payload.get("meeting_date", "")
    recording_id = payload.get("recording_id", "")

    added = 0
    for i, item in enumerate(payload.get("action_items", []), start=1):
        action_id = f"{recording_id}:{i}" if recording_id else f"{meeting_title}:{i}"
        if action_id in seen_ids:
            continue
        pending.append(
            {
                "action_id": action_id,
                "meeting_title": meeting_title,
                "meeting_date": meeting_date,
                "text": item.get("text", ""),
                "owner": item.get("owner", "jason"),
                "due": item.get("due"),
                "proposed_list": _pick_clickup_list(meeting_title),
                "needs_followup_email": bool(item.get("needs_followup_email")),
                "followup": {
                    "to": item.get("followup_to", ""),
                    "subject": item.get("followup_subject", ""),
                    "body": item.get("followup_body", ""),
                },
                "status": "awaiting_confirmation",
                "queued_at": now,
            }
        )
        added += 1

    _save_json(PENDING_DIGEST_FILE, pending)
    awaiting = [p for p in pending if p.get("status") == "awaiting_confirmation"]
    print(
        f"Staged {added} action item(s) from {meeting_title!r}. "
        f"Queue: {len(awaiting)} awaiting approval, {len(pending)} total."
    )
    return 0


def _pick_clickup_list(meeting_title: str) -> str:
    """Suggest the ClickUp list name based on the meeting title."""
    from meeting_config import CLICKUP_DEFAULT_LIST_NAME, CLICKUP_LIST_KEYWORDS

    low = (meeting_title or "").lower()
    for keyword, list_name in CLICKUP_LIST_KEYWORDS:
        if keyword.lower() in low:
            return list_name
    return CLICKUP_DEFAULT_LIST_NAME


def run_apply() -> int:
    """File approved entries: create ClickUp tasks, draft follow-up emails.

    Per the "always confirm before filing" rule, only entries whose status is
    "approved" are applied. Each one becomes:
      - a ClickUp task in the resolved list
      - optionally a Gmail draft (never sent — Jason reviews & sends manually)
    """
    from datetime import date as date_type

    from integrations.clickup_api import create_task, find_list_id_by_name
    from integrations.gmail import create_gmail_draft

    pending = _load_json(PENDING_DIGEST_FILE, [])
    approved = [p for p in pending if p.get("status") == "approved"]
    if not approved:
        print("No approved digest entries to apply.")
        return 0

    list_id_cache: dict[str, str | None] = {}
    totals = {"clickup_task": 0, "email_draft": 0, "errors": 0}

    for entry in approved:
        try:
            # Resolve the ClickUp list (cache across entries to save API calls)
            list_name = entry.get("clickup_list") or entry.get("proposed_list")
            if list_name and list_name not in list_id_cache:
                list_id_cache[list_name] = find_list_id_by_name(list_name)
            list_id = list_id_cache.get(list_name) if list_name else None

            # Due date
            due = entry.get("due")
            due_on: date_type | None = None
            if due:
                try:
                    due_on = date_type.fromisoformat(due)
                except Exception:
                    pass  # Leave as None if malformed — task still lands, just no due

            # Create the ClickUp task
            if list_id:
                description = (
                    f"From meeting: {entry.get('meeting_title','')}"
                    f" ({entry.get('meeting_date','')})\n\n"
                    f"Action: {entry.get('text','')}"
                )
                create_task(
                    list_id=list_id,
                    name=entry.get("text", "(untitled action)")[:120],
                    description=description,
                    due_on=due_on,
                )
                totals["clickup_task"] += 1
            else:
                print(f"  [warn] no ClickUp list resolved for entry {entry['action_id']}")

            # Optional follow-up email draft
            followup = entry.get("followup") or {}
            if entry.get("needs_followup_email") and followup.get("to"):
                create_gmail_draft(
                    to=followup["to"],
                    subject=followup.get("subject", f"Follow-up: {entry.get('meeting_title','')}"),
                    body=followup.get("body", ""),
                )
                totals["email_draft"] += 1

            entry["status"] = "applied"
            entry["applied_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        except Exception as e:
            print(f"  [error] applying {entry.get('action_id')}: {e}")
            totals["errors"] += 1

    _save_json(PENDING_DIGEST_FILE, pending)
    print(
        f"Apply complete. ClickUp tasks: {totals['clickup_task']}, "
        f"Gmail drafts: {totals['email_draft']}, errors: {totals['errors']}"
    )
    return 0 if totals["errors"] == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Meeting Concierge")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("brief", help="Pre-meeting sweep; text Jason a brief for the next 15 min.")
    digest_parser = sub.add_parser(
        "digest", help="Stage Fathom action items as proposals awaiting approval."
    )
    digest_parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Fathom JSON dump (action items + meeting metadata). See SKILL.md schema.",
    )
    sub.add_parser("apply", help="File approved digest entries (ClickUp + email drafts).")

    args = parser.parse_args()
    if args.cmd == "digest":
        return run_digest(args.file)
    if args.cmd == "apply":
        return run_apply()
    return run_brief()  # default


if __name__ == "__main__":
    raise SystemExit(main())
