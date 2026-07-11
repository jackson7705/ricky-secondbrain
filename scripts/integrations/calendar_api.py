"""
Google Calendar Direct Integration for Second Brain.

Read-only access to Google Calendar. Shares OAuth token with Gmail.

Usage:
    uv run python -m integrations.calendar_api today
    uv run python -m integrations.calendar_api upcoming --hours 48
    uv run python -m integrations.calendar_api soon
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Add parent dir for config imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import LOCAL_TZ, GOOGLE_CALENDAR_ID  # noqa: E402
from sanitize import sanitize_external_text  # noqa: E402
from shared import with_retry  # noqa: E402


@dataclass
class CalendarEvent:
    """Represents a calendar event."""

    id: str
    summary: str
    start: datetime
    end: datetime
    location: str | None = None
    description: str | None = None
    attendees: list[str] = field(default_factory=list)
    is_all_day: bool = False


def get_calendar_service() -> Any:
    """Build authenticated Calendar API service."""
    from googleapiclient.discovery import build  # type: ignore[import-untyped]

    from integrations.auth import get_google_credentials

    creds = get_google_credentials()
    service: Any = build("calendar", "v3", credentials=creds)
    return service


def create_event(
    summary: str,
    start: str,
    end: str,
    *,
    calendar_id: str = "primary",
    location: str | None = None,
    description: str | None = None,
    attendees: list[str] | None = None,
    timezone: str | None = None,
) -> dict[str, Any]:
    """Create an event on the ACTIVE account's calendar.

    `start`/`end` are ISO-8601 datetimes (e.g. '2026-07-09T14:00:00'); the local
    timezone is assumed when no offset is given. `calendar_id='primary'` targets
    the authenticated account's own calendar (so with --account locafy this
    schedules on the Locafy calendar). Returns the created event (`id`,
    `htmlLink`). Requires the `calendar.events` scope — if you only have
    `calendar.readonly`, re-run `setup_auth.py --account <acct>` first.
    """
    service = get_calendar_service()
    tz = timezone or str(LOCAL_TZ)
    body: dict[str, Any] = {
        "summary": summary,
        "start": {"dateTime": start, "timeZone": tz},
        "end": {"dateTime": end, "timeZone": tz},
    }
    if location:
        body["location"] = location
    if description:
        body["description"] = description
    if attendees:
        body["attendees"] = [{"email": a.strip()} for a in attendees if a.strip()]
    event: dict[str, Any] = with_retry(
        lambda: service.events()
        .insert(
            calendarId=calendar_id,
            body=body,
            sendUpdates="all" if attendees else "none",
        )
        .execute()
    )
    return event


def _parse_event_time(time_data: dict[str, str]) -> tuple[datetime, bool]:
    """Parse event start/end time, handling both timed and all-day events."""
    if "dateTime" in time_data:
        dt = datetime.fromisoformat(time_data["dateTime"])
        return dt, False
    else:
        # All-day event: date string like '2026-02-06'
        date_str = time_data.get("date", "")
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
        return dt, True


def get_upcoming_events(
    hours_ahead: int = 24,
    calendar_id: str | None = None,
    max_results: int = 10,
) -> list[CalendarEvent]:
    """
    Get upcoming calendar events.

    Args:
        hours_ahead: Look this many hours into the future
        calendar_id: Calendar ID (defaults to config GOOGLE_CALENDAR_ID)
        max_results: Maximum events to return
    """
    service = get_calendar_service()
    # Fall back order:
    # 1. Explicit calendar_id arg wins.
    # 2. If a multi-profile account is active (set_active_account), use
    #    "primary" so each profile's own calendar is queried instead of
    #    the single GOOGLE_CALENDAR_ID env var (which was pinned to the
    #    growthpro calendar and 404'd on wonderly/locafy profiles).
    # 3. Single-account fallback: GOOGLE_CALENDAR_ID env var.
    # 4. Last resort: "primary".
    from integrations.auth import get_active_account

    if calendar_id:
        cal_id = calendar_id
    elif get_active_account():
        cal_id = "primary"
    else:
        cal_id = GOOGLE_CALENDAR_ID or "primary"

    now = datetime.now(UTC)
    end_time = now + timedelta(hours=hours_ahead)

    result: dict[str, Any] = with_retry(
        lambda: service.events()
        .list(
            calendarId=cal_id,
            timeMin=now.isoformat(),
            timeMax=end_time.isoformat(),
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events: list[CalendarEvent] = []
    for item in result.get("items", []):
        start_data = item.get("start", {})
        end_data = item.get("end", {})

        start, is_all_day = _parse_event_time(start_data)
        end, _ = _parse_event_time(end_data)

        attendees = [a.get("email", "") for a in item.get("attendees", [])]

        events.append(
            CalendarEvent(
                id=item["id"],
                summary=item.get("summary", "(No title)"),
                start=start,
                end=end,
                location=item.get("location"),
                description=item.get("description"),
                attendees=attendees,
                is_all_day=is_all_day,
            )
        )

    return events


def get_today_events(calendar_id: str | None = None) -> list[CalendarEvent]:
    """Get all events for the rest of today (LOCAL_TZ)."""
    now = datetime.now(LOCAL_TZ)
    hours_to_midnight = 24 - now.hour
    return get_upcoming_events(hours_ahead=hours_to_midnight, calendar_id=calendar_id)


def check_for_upcoming_meetings(
    hours_ahead: int = 4,
    calendar_id: str | None = None,
) -> list[CalendarEvent]:
    """Check for meetings coming up soon (within N hours)."""
    return get_upcoming_events(hours_ahead=hours_ahead, calendar_id=calendar_id, max_results=5)


def format_events_for_context(events: list[CalendarEvent]) -> str:
    """Format events for inclusion in Claude's context prompt."""
    if not events:
        return "No upcoming events."

    output: list[str] = []
    for event in events:
        start_cst = event.start.astimezone(LOCAL_TZ) if event.start.tzinfo else event.start
        end_cst = event.end.astimezone(LOCAL_TZ) if event.end.tzinfo else event.end
        time_str = (
            "All day"
            if event.is_all_day
            else f"{start_cst.strftime('%H:%M')} - {end_cst.strftime('%H:%M')}"
        )

        entry = f"- **{sanitize_external_text(event.summary, 'calendar')}** ({time_str})"
        if event.location:
            entry += f"\n  Location: {sanitize_external_text(event.location, 'calendar')}"
        if event.attendees:
            shown = ", ".join(sanitize_external_text(a, "calendar") for a in event.attendees[:3])
            entry += f"\n  Attendees: {shown}"
            if len(event.attendees) > 3:
                entry += f" +{len(event.attendees) - 3} more"

        output.append(entry)

    return "\n\n".join(output)


# CLI for testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Calendar integration")
    parser.add_argument("command", choices=["today", "upcoming", "soon"])
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--calendar", default=None)

    args = parser.parse_args()

    if args.command == "today":
        cal_events = get_today_events(args.calendar)
    elif args.command == "upcoming":
        cal_events = get_upcoming_events(hours_ahead=args.hours, calendar_id=args.calendar)
    elif args.command == "soon":
        cal_events = check_for_upcoming_meetings(hours_ahead=4, calendar_id=args.calendar)

    print(format_events_for_context(cal_events))
