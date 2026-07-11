"""daily-brief orchestrator.

Two subcommands:
  morning — Mon–Fri 07:00 CT rundown.
  weekly  — Fri 16:00 CT week-over-week rollup.

Both gather data deterministically from the existing `integrations` modules,
compose a plain-text brief, and deliver via iMessage (BlueBubbles REST, same
path as meeting-concierge). No LLM calls, no hallucinations.

Launchd fires these plists hourly across a wide window; the script gates on
(weekday, CT hour, not-already-sent-today) and silently exits otherwise. The
wide window + in-script gate means this keeps working regardless of whether
Jason's Mac is in Central, Pacific, or anywhere else.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_SKILL_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _SKILL_DIR.parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))
sys.path.insert(0, str(_SKILL_DIR))

from brief_config import (  # noqa: E402
    BRIEF_TZ,
    CALENDAR_PROFILES,
    FLAGGED_SENDER_EXCLUDES,
    FLAGGED_SENDERS,
    GATE_MINUTE_WINDOW,
    IMESSAGE_BRIEF_CHAT_GUID,
    INBOX_PROFILE,
    MAX_BRIEF_CHARS,
    MORNING_HOUR,
    MORNING_WEEKDAYS,
    STATE_FILE,
    WEEKLY_HOUR,
    WEEKLY_LOOKBACK_DAYS,
    WEEKLY_WEEKDAY,
    YESTERDAY_LOOKBACK_DAYS,
)


# ── State ───────────────────────────────────────────────────────────────


def _load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text())
    except FileNotFoundError:
        return {"last_sent": {}}
    except Exception as e:
        print(f"  [warn] couldn't parse state: {e} — using fresh")
        return {"last_sent": {}}


def _save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def _today_ct() -> date:
    return datetime.now(ZoneInfo(BRIEF_TZ)).date()


def _now_ct() -> datetime:
    return datetime.now(ZoneInfo(BRIEF_TZ))


# ── iMessage delivery ───────────────────────────────────────────────────


def _post_imessage(text: str) -> bool:
    """Post an iMessage via BlueBubbles REST — same pattern as meeting-concierge."""
    import urllib.parse
    import urllib.request

    from config import BLUEBUBBLES_PASSWORD, BLUEBUBBLES_URL

    if not BLUEBUBBLES_URL or not BLUEBUBBLES_PASSWORD:
        print("  [skip] BLUEBUBBLES_URL / PASSWORD not set — brief not sent")
        return False

    url = (
        f"{BLUEBUBBLES_URL}/api/v1/message/text"
        f"?password={urllib.parse.quote(BLUEBUBBLES_PASSWORD)}"
    )
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
class TodayEvent:
    profile: str
    title: str
    starts_at: datetime
    attendees: list[str]
    has_description: bool


def _todays_events() -> list[TodayEvent]:
    """Pull today's remaining events across all three calendars."""
    from integrations.auth import set_active_account
    from integrations.calendar_api import get_today_events

    out: list[TodayEvent] = []
    for profile in CALENDAR_PROFILES:
        set_active_account(profile)
        try:
            events = get_today_events()
        except Exception as e:
            print(f"  [warn] calendar fetch failed for {profile}: {e}")
            continue
        finally:
            set_active_account(None)

        for ev in events:
            if ev.is_all_day:
                continue
            out.append(
                TodayEvent(
                    profile=profile,
                    title=(ev.summary or "(no title)").strip(),
                    starts_at=ev.start,
                    attendees=ev.attendees or [],
                    has_description=bool(ev.description),
                )
            )

    out.sort(key=lambda e: e.starts_at)
    return out


# ── Inbox signal ────────────────────────────────────────────────────────


@dataclass
class InboxSignal:
    unread_count: int
    flagged_threads: list[tuple[str, str]] = field(default_factory=list)
    # list of (subject, sender_display)


def _inbox_signal() -> InboxSignal:
    """Unread Primary count + any threads from flagged senders in last 24h."""
    from integrations.auth import set_active_account
    from integrations.gmail import list_emails

    set_active_account(INBOX_PROFILE)
    try:
        unread = list_emails(
            max_results=50,
            unread_only=True,
            query="category:primary in:inbox",
        )
    except Exception as e:
        print(f"  [warn] inbox signal failed: {e}")
        set_active_account(None)
        return InboxSignal(unread_count=0)

    flagged: list[tuple[str, str]] = []
    for e in unread:
        sender_raw = (e.sender or e.sender_email or "").lower()
        if any(exc in sender_raw for exc in FLAGGED_SENDER_EXCLUDES):
            continue
        if any(flag in sender_raw for flag in FLAGGED_SENDERS):
            flagged.append(
                (
                    (e.subject or "(no subject)").strip()[:80],
                    (e.sender or e.sender_email or "unknown").strip()[:50],
                )
            )
    set_active_account(None)
    return InboxSignal(unread_count=len(unread), flagged_threads=flagged[:5])


# ── ClickUp ─────────────────────────────────────────────────────────────


@dataclass
class TaskBuckets:
    overdue: list[str] = field(default_factory=list)
    due_today: list[str] = field(default_factory=list)
    shipped_yesterday: list[str] = field(default_factory=list)


def _task_buckets() -> TaskBuckets:
    """Overdue, due-today, and yesterday's closed tasks."""
    from integrations.clickup_api import get_my_tasks, get_overdue_tasks

    buckets = TaskBuckets()
    today = _today_ct()
    yesterday = today - timedelta(days=YESTERDAY_LOOKBACK_DAYS)

    try:
        overdue = get_overdue_tasks()
    except Exception as e:
        print(f"  [warn] overdue fetch failed: {e}")
        overdue = []

    try:
        active = get_my_tasks(include_closed=False)
    except Exception as e:
        print(f"  [warn] active task fetch failed: {e}")
        active = []

    # For "shipped yesterday" we need closed tasks.
    try:
        with_closed = get_my_tasks(include_closed=True)
    except Exception as e:
        print(f"  [warn] closed task fetch failed: {e}")
        with_closed = []

    for t in overdue:
        days_over = (today - t.due_on).days if t.due_on else 0
        suffix = f" ({days_over}d over)" if days_over > 0 else ""
        buckets.overdue.append(f"{t.name}{suffix}")

    for t in active:
        if t.due_on == today:
            buckets.due_today.append(t.name)

    for t in with_closed:
        if not t.is_finished:
            continue
        # Prefer date_closed if available; fall back to due_on.
        closed_on = getattr(t, "date_closed", None) or t.due_on
        if closed_on == yesterday:
            buckets.shipped_yesterday.append(t.name)

    return buckets


# ── Morning brief composition ───────────────────────────────────────────


def _pick_one_thing(events: list[TodayEvent], tasks: TaskBuckets) -> str:
    """Heuristic pick of today's priority. Falsifiable by design so Jason
    can push back. No LLM — just a clear rule set."""
    # Rule 1: the highest-stakes calendar event wins. Prioritize keywords.
    STAKES = [
        ("earnings", "earnings call"),
        ("board", "board meeting"),
        ("investor", "investor meeting"),
        ("pitch", "pitch"),
        ("press", "press"),
        ("interview", "interview"),
        ("close", "closing call"),
    ]
    for ev in events:
        low = ev.title.lower()
        for needle, label in STAKES:
            if needle in low:
                local = ev.starts_at.astimezone(ZoneInfo(BRIEF_TZ))
                return f"The {label} at {local.strftime('%-I:%M %p')} — prep first."

    # Rule 2: oldest overdue task if nothing high-stakes on calendar
    if tasks.overdue:
        return f"Clear the oldest overdue — {tasks.overdue[0]}."

    # Rule 3: first meeting of the day
    if events:
        ev = events[0]
        local = ev.starts_at.astimezone(ZoneInfo(BRIEF_TZ))
        return f"Run {ev.title} well at {local.strftime('%-I:%M %p')}. Everything else is downstream."

    # Rule 4: no meetings, no overdue → deep work day
    return "No meetings, no overdue. Pick one hard problem and close it."


def _compose_morning(
    events: list[TodayEvent],
    inbox: InboxSignal,
    tasks: TaskBuckets,
    now: datetime,
) -> str:
    day_label = now.strftime("%A, %B %-d")
    meeting_count = len(events)
    overdue_count = len(tasks.overdue)
    one_thing = _pick_one_thing(events, tasks)

    lines: list[str] = []
    lines.append(f"Good morning, Jason. {day_label}.")
    lines.append("")
    summary_bits = []
    if meeting_count:
        summary_bits.append(f"{meeting_count} meeting{'s' if meeting_count != 1 else ''}")
    if overdue_count:
        summary_bits.append(f"{overdue_count} overdue")
    summary_bits.append(f"{inbox.unread_count} unread")
    lines.append("Today: " + ", ".join(summary_bits) + ".")
    lines.append("")

    # Schedule
    if events:
        lines.append("Schedule")
        for ev in events:
            local = ev.starts_at.astimezone(ZoneInfo(BRIEF_TZ))
            tag = f"[{ev.profile}]"
            ext = "" if ev.has_description else " — no agenda"
            lines.append(f"• {local.strftime('%-I:%M %p')} {tag} {ev.title}{ext}")
        lines.append("")
    else:
        lines.append("Schedule: nothing on the calendar.")
        lines.append("")

    # Inbox
    lines.append("Inbox (growthpro primary)")
    if inbox.unread_count == 0:
        lines.append("• Zero unread — clean.")
    else:
        lines.append(f"• {inbox.unread_count} unread"
                     + (f" · {len(inbox.flagged_threads)} flagged" if inbox.flagged_threads else ""))
        for subj, sender in inbox.flagged_threads:
            sender_short = sender.split("<")[0].strip().strip('"') or sender
            lines.append(f"  - {subj} — {sender_short}")
    lines.append("")

    # ClickUp
    lines.append("ClickUp")
    if tasks.overdue:
        lines.append(f"• Overdue ({len(tasks.overdue)}): " + "; ".join(tasks.overdue[:5]))
    else:
        lines.append("• Overdue: none.")
    if tasks.due_today:
        lines.append(f"• Due today ({len(tasks.due_today)}): " + "; ".join(tasks.due_today[:5]))
    lines.append("")

    # Yesterday
    if tasks.shipped_yesterday:
        lines.append("Yesterday shipped")
        for t in tasks.shipped_yesterday[:4]:
            lines.append(f"• {t}")
        lines.append("")

    # One thing
    lines.append(f"The one thing: {one_thing}")

    return "\n".join(lines)[:MAX_BRIEF_CHARS]


# ── Weekly rollup composition ───────────────────────────────────────────


@dataclass
class WeekRollup:
    shipped: list[str] = field(default_factory=list)
    slipped: list[str] = field(default_factory=list)
    next_week_events: list[TodayEvent] = field(default_factory=list)


def _gather_weekly() -> WeekRollup:
    from integrations.auth import set_active_account
    from integrations.calendar_api import get_upcoming_events
    from integrations.clickup_api import get_my_tasks

    roll = WeekRollup()
    today = _today_ct()
    week_start = today - timedelta(days=WEEKLY_LOOKBACK_DAYS - 1)

    try:
        with_closed = get_my_tasks(include_closed=True)
    except Exception as e:
        print(f"  [warn] closed task fetch failed: {e}")
        with_closed = []

    try:
        active = get_my_tasks(include_closed=False)
    except Exception as e:
        print(f"  [warn] active task fetch failed: {e}")
        active = []

    for t in with_closed:
        if not t.is_finished:
            continue
        closed_on = getattr(t, "date_closed", None) or t.due_on
        if closed_on and week_start <= closed_on <= today:
            roll.shipped.append(t.name)

    for t in active:
        if t.due_on and week_start <= t.due_on < today:
            roll.slipped.append(t.name)

    # Mon/Tue preview across all calendars
    for profile in CALENDAR_PROFILES:
        set_active_account(profile)
        try:
            events = get_upcoming_events(hours_ahead=96, max_results=20)
        except Exception as e:
            print(f"  [warn] next-week calendar fetch failed for {profile}: {e}")
            continue
        finally:
            set_active_account(None)

        for ev in events:
            if ev.is_all_day:
                continue
            local = ev.start.astimezone(ZoneInfo(BRIEF_TZ))
            # Only Mon and Tue of next week
            if local.weekday() in (0, 1) and local.date() > today:
                roll.next_week_events.append(
                    TodayEvent(
                        profile=profile,
                        title=(ev.summary or "(no title)").strip(),
                        starts_at=ev.start,
                        attendees=ev.attendees or [],
                        has_description=bool(ev.description),
                    )
                )

    roll.next_week_events.sort(key=lambda e: e.starts_at)
    return roll


def _compose_weekly(roll: WeekRollup, now: datetime) -> str:
    week_of = (now - timedelta(days=now.weekday())).strftime("%b %-d")
    lines: list[str] = []
    lines.append(f"Friday wrap, week of {week_of}.")
    lines.append("")

    lines.append(f"Shipped this week ({len(roll.shipped)})")
    if roll.shipped:
        for name in roll.shipped[:10]:
            lines.append(f"• {name}")
    else:
        lines.append("• Nothing closed in ClickUp this week.")
    lines.append("")

    if roll.slipped:
        lines.append(f"Slipped / rolled ({len(roll.slipped)})")
        for name in roll.slipped[:6]:
            lines.append(f"• {name}")
        lines.append("")

    lines.append("Weekend setup — Mon/Tue preview")
    if roll.next_week_events:
        for ev in roll.next_week_events[:8]:
            local = ev.starts_at.astimezone(ZoneInfo(BRIEF_TZ))
            lines.append(f"• {local.strftime('%a %-I:%M %p')} [{ev.profile}] {ev.title}")
    else:
        lines.append("• Clean start — nothing on the books yet.")
    lines.append("")

    lines.append(
        "One question for the weekend: "
        "what's the one bet you'd double down on if next quarter started Monday?"
    )
    return "\n".join(lines)[:MAX_BRIEF_CHARS]


# ── Gates ───────────────────────────────────────────────────────────────


def _morning_gate(now: datetime) -> str | None:
    """Return None if we should send; else a reason string for the skip log."""
    if now.weekday() not in MORNING_WEEKDAYS:
        return f"not a weekday (weekday={now.weekday()})"
    if now.hour != MORNING_HOUR:
        return f"wrong hour ({now.hour:02d}:00 CT, target {MORNING_HOUR:02d}:00)"
    if now.minute > GATE_MINUTE_WINDOW:
        return f"past the minute window ({now.minute})"
    return None


def _weekly_gate(now: datetime) -> str | None:
    if now.weekday() != WEEKLY_WEEKDAY:
        return f"not Friday (weekday={now.weekday()})"
    if now.hour != WEEKLY_HOUR:
        return f"wrong hour ({now.hour:02d}:00 CT, target {WEEKLY_HOUR:02d}:00)"
    if now.minute > GATE_MINUTE_WINDOW:
        return f"past the minute window ({now.minute})"
    return None


# ── Subcommands ─────────────────────────────────────────────────────────


def run_morning(args: argparse.Namespace) -> int:
    now = _now_ct()
    today_key = now.date().isoformat()

    if not args.force and not args.dry_run:
        reason = _morning_gate(now)
        if reason:
            print(f"  [skip] morning gate: {reason}")
            return 0

    state = _load_state()
    last_sent = state.get("last_sent", {}).get("morning")
    if last_sent == today_key and not args.force and not args.dry_run:
        print(f"  [skip] morning brief already sent today ({today_key})")
        return 0

    events = _todays_events()
    inbox = _inbox_signal()
    tasks = _task_buckets()
    text = _compose_morning(events, inbox, tasks, now)

    if args.dry_run:
        print("=== MORNING BRIEF (dry-run) ===")
        print(text)
        return 0

    sent = _post_imessage(text)
    if sent:
        state.setdefault("last_sent", {})["morning"] = today_key
        _save_state(state)
        print(f"  [sent] morning brief for {today_key}")
        return 0
    print("  [error] morning brief send failed")
    return 1


def run_weekly(args: argparse.Namespace) -> int:
    now = _now_ct()
    today_key = now.date().isoformat()

    if not args.force and not args.dry_run:
        reason = _weekly_gate(now)
        if reason:
            print(f"  [skip] weekly gate: {reason}")
            return 0

    state = _load_state()
    last_sent = state.get("last_sent", {}).get("weekly")
    if last_sent == today_key and not args.force and not args.dry_run:
        print(f"  [skip] weekly brief already sent today ({today_key})")
        return 0

    roll = _gather_weekly()
    text = _compose_weekly(roll, now)

    if args.dry_run:
        print("=== WEEKLY ROLLUP (dry-run) ===")
        print(text)
        return 0

    sent = _post_imessage(text)
    if sent:
        state.setdefault("last_sent", {})["weekly"] = today_key
        _save_state(state)
        print(f"  [sent] weekly rollup for {today_key}")
        return 0
    print("  [error] weekly rollup send failed")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Jason's daily executive brief. morning (Mon–Fri 7am CT) or weekly (Fri 4pm CT)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name in ("morning", "weekly"):
        p = sub.add_parser(name, help=f"Run the {name} brief")
        p.add_argument("--dry-run", action="store_true", help="Print to stdout, don't send.")
        p.add_argument("--force", action="store_true", help="Bypass time-window and dedup gates.")

    args = parser.parse_args()
    if args.cmd == "morning":
        return run_morning(args)
    if args.cmd == "weekly":
        return run_weekly(args)
    parser.error(f"unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
