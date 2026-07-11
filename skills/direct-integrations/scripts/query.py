"""
Interactive CLI wrapper for direct platform integrations.

Used by the direct-integrations Claude Code skill to query Gmail, Calendar,
Slack, Google Sheets, Google Docs, and Google Drive from interactive sessions.

For ClickUp task queries use the ClickUp MCP — Asana is not used in this workspace.

Usage:
    python query.py gmail list --max 5
    python query.py calendar today
    python query.py slack channels
    python query.py sheets read <spreadsheet_id> [--range "Sheet1!A1:Z100"]
    python query.py docs read <document_id>
    python query.py drive find "search term" [--type spreadsheet]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add the scripts directory to Python path for integration imports
SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


def _add_account_arg(sub: argparse.ArgumentParser) -> None:
    """Add --account (and --all-accounts where supported) to a subparser."""
    sub.add_argument(
        "--account",
        default=None,
        help="Named Google profile (e.g. growthpro, locafy, wonderly). "
        "Defaults to DEFAULT_GOOGLE_ACCOUNT env var.",
    )


def _add_all_accounts_arg(sub: argparse.ArgumentParser) -> None:
    """Add --all-accounts for commands that can scan every profile."""
    sub.add_argument(
        "--all-accounts",
        dest="all_accounts",
        action="store_true",
        help="Query every configured Google profile and merge results, "
        "tagging each item with the profile it came from.",
    )


def _add_workspace_arg(sub: argparse.ArgumentParser) -> None:
    """Add --workspace to a Slack subparser."""
    sub.add_argument(
        "--workspace",
        default=None,
        help="Named Slack workspace (e.g. growthpro, wonderly). "
        "Defaults to DEFAULT_SLACK_WORKSPACE env var.",
    )


def _iter_google_profiles(args: argparse.Namespace) -> list[str | None]:
    """
    Return the list of Google profiles to run a read-only command against.

    - With `--all-accounts`, iterates over every profile that has a saved token.
    - Otherwise returns `[None]`, meaning "use whatever the contextvar /
      env default already resolved to" — i.e. no switching.
    """
    if getattr(args, "all_accounts", False):
        from config import list_google_profiles

        profiles = list_google_profiles()
        if profiles:
            return list(profiles)
    return [None]


def cmd_gmail(args: argparse.Namespace) -> None:
    """Handle Gmail commands."""
    from integrations.auth import set_active_account
    from integrations.gmail import (
        check_for_urgent_emails,
        create_gmail_draft,
        create_gmail_draft_from_file,
        download_attachment,
        format_emails_for_context,
        format_thread_for_context,
        get_email_details,
        get_gmail_service,
        get_thread_messages,
        get_unread_count,
        list_attachments,
        list_emails,
    )

    if args.action == "list":
        # Default to 24h window when no query specified (recent inbox view)
        # but no time filter when searching (user wants to find old emails too)
        hours = args.hours if args.hours is not None else (None if args.query else 24)
        for profile in _iter_google_profiles(args):
            if profile is not None:
                set_active_account(profile)
                print(f"\n=== Gmail — {profile} ===")
            emails = list_emails(
                max_results=args.max,
                query=args.query or "",
                unread_only=args.unread,
                hours_ago=hours,
            )
            print(format_emails_for_context(emails))

    elif args.action == "urgent":
        for profile in _iter_google_profiles(args):
            if profile is not None:
                set_active_account(profile)
                print(f"\n=== Gmail urgent — {profile} ===")
            urgent = check_for_urgent_emails(hours_ago=args.hours)
            if urgent:
                print(f"Found {len(urgent)} potentially urgent emails:\n")
                print(format_emails_for_context(urgent))
            else:
                print("No urgent emails found")

    elif args.action == "unread":
        for profile in _iter_google_profiles(args):
            if profile is not None:
                set_active_account(profile)
                label = f" ({profile})"
            else:
                label = ""
            count = get_unread_count()
            print(f"Unread emails{label}: {count}")

    elif args.action == "read":
        if not args.message_id:
            print("Error: message_id required for read command")
            sys.exit(1)
        service = get_gmail_service()
        email = get_email_details(service, args.message_id, include_body=True)
        if email:
            print(f"Subject: {email.subject}")
            print(f"From: {email.sender} <{email.sender_email}>")
            print(f"Date: {email.date}")
            print(f"Labels: {', '.join(email.labels)}")
            print(f"\n{email.body or email.snippet}")
        else:
            print("Email not found")

    elif args.action == "thread":
        if not args.message_id:
            print("Error: thread_id required for thread command")
            sys.exit(1)
        emails = get_thread_messages(args.message_id)
        print(format_thread_for_context(emails))

    elif args.action == "search":
        if not args.message_id:
            print("Error: search query required for search command")
            sys.exit(1)
        emails = list_emails(
            max_results=args.max,
            query=args.message_id,
        )
        print(format_emails_for_context(emails))

    elif args.action == "attachments":
        if not args.message_id:
            print("Error: message_id required for attachments command")
            sys.exit(1)
        atts = list_attachments(args.message_id)
        if not atts:
            print("No attachments found on this message.")
        else:
            print(f"Found {len(atts)} attachment(s):\n")
            for a in atts:
                size_kb = a.size / 1024
                print(f"  - {a.filename} ({a.mime_type}, {size_kb:.1f} KB)")
                print(f"    attachment_id: {a.id}")

    elif args.action == "download-attachment":
        if not args.message_id:
            print("Error: message_id required for download-attachment command")
            sys.exit(1)
        att_id = getattr(args, "attachment_id", None)
        if not att_id:
            print("Error: --attachment-id required for download-attachment command")
            sys.exit(1)
        # Determine output path
        output_dir = Path(getattr(args, "output_dir", None) or ".")
        # Get filename from the attachment metadata
        atts = list_attachments(args.message_id)
        filename = "attachment"
        for a in atts:
            if a.id == att_id:
                filename = a.filename
                break
        output_path = output_dir / filename
        result_path = download_attachment(args.message_id, att_id, output_path)
        print(f"Downloaded: {result_path}")

    elif args.action == "create-draft":
        from_file = getattr(args, "from_file", None)
        if from_file:
            # Read everything from the markdown draft file
            result = create_gmail_draft_from_file(from_file)
        else:
            # Manual mode: all args required
            to = getattr(args, "to", None)
            subject = getattr(args, "draft_subject", None)
            body = getattr(args, "body", None)
            thread_id = getattr(args, "thread_id", None)
            msg_id = args.message_id
            if not to or not subject or not body:
                print("Error: --from-file or (--to, --subject, --body) required")
                sys.exit(1)
            attachment_list = getattr(args, "attachment", None) or []
            result = create_gmail_draft(
                to=to,
                subject=subject,
                body=body,
                thread_id=thread_id,
                message_id=msg_id,
                attachments=attachment_list if attachment_list else None,
            )
        print(json.dumps(result, indent=2))

    elif args.action == "send-draft":
        # Sends an EXISTING draft. Only run after Jason has explicitly approved
        # this specific draft — never autonomously.
        from integrations.gmail import send_draft
        if not args.message_id:
            print("Error: draft_id required as the positional argument")
            sys.exit(1)
        print(json.dumps(send_draft(args.message_id), indent=2))


def cmd_calendar(args: argparse.Namespace) -> None:
    """Handle Calendar commands."""
    from integrations.calendar_api import (
        check_for_upcoming_meetings,
        format_events_for_context,
        get_today_events,
        get_upcoming_events,
    )

    if args.action == "today":
        events = get_today_events()
        print(format_events_for_context(events))

    elif args.action == "upcoming":
        events = get_upcoming_events(hours_ahead=args.hours)
        print(format_events_for_context(events))

    elif args.action == "soon":
        events = check_for_upcoming_meetings(hours_ahead=4)
        print(format_events_for_context(events))

    elif args.action == "create":
        from datetime import datetime, timedelta

        from integrations.calendar_api import create_event

        start = args.start
        end = args.end
        if not end:
            s = datetime.fromisoformat(start)
            end = (s + timedelta(minutes=args.duration)).isoformat()
        attendees = [a for a in (args.attendees or "").split(",") if a.strip()] or None
        ev = create_event(
            args.title, start, end,
            calendar_id=args.calendar,
            location=args.location,
            description=args.description,
            attendees=attendees,
        )
        who = f" (invited {len(attendees)})" if attendees else ""
        print(f"Created: {ev.get('summary')} @ {start}{who}\n{ev.get('htmlLink')}")


def cmd_clickup(args: argparse.Namespace) -> None:
    """Handle ClickUp commands. Locafy task tracker — this workspace's only task system."""
    from integrations.clickup_api import (
        format_tasks_for_context,
        get_due_soon_tasks,
        get_my_tasks,
        get_overdue_tasks,
    )

    if args.action == "my-tasks":
        tasks = get_my_tasks(include_closed=args.include_closed)
        if args.max:
            tasks = tasks[: args.max]
        print(format_tasks_for_context(tasks))

    elif args.action == "overdue":
        tasks = get_overdue_tasks()
        if args.max:
            tasks = tasks[: args.max]
        if not tasks:
            print("No overdue tasks.")
        else:
            print(format_tasks_for_context(tasks))

    elif args.action == "due-soon":
        tasks = get_due_soon_tasks(days=args.days)
        if args.max:
            tasks = tasks[: args.max]
        if not tasks:
            print(f"No tasks due in the next {args.days} days.")
        else:
            print(format_tasks_for_context(tasks))


def cmd_slack(args: argparse.Namespace) -> None:
    """Handle Slack commands."""
    from integrations.slack_api import (
        check_for_important_messages,
        format_messages_for_context,
        get_channel_id,
        get_recent_messages,
        get_slack_client,
        send_notification,
        update_message,
    )

    if args.action == "channels":
        client = get_slack_client()
        result = client.conversations_list(types="public_channel", limit=100)
        for ch in result.get("channels", []):
            print(f"  #{ch['name']} ({ch['id']})")

    elif args.action == "messages":
        if not args.channel:
            print("Error: channel name required")
            sys.exit(1)
        ch_id = get_channel_id(args.channel)
        if not ch_id:
            print(f"Channel not found: {args.channel}")
            sys.exit(1)
        msgs = get_recent_messages(ch_id, hours_ago=args.hours, limit=20)
        print(format_messages_for_context(msgs))

    elif args.action == "send":
        if not args.channel or not args.message:
            print("Error: channel and message required")
            sys.exit(1)
        result = send_notification(args.channel, args.message)
        print(f"Sent! (ts={result['ts']})" if result else "Failed to send")

    elif args.action == "update":
        if not args.channel or not args.ts or not args.message:
            print("Error: channel, --ts, and message required")
            sys.exit(1)
        result = update_message(args.channel, args.ts, args.message)
        print(f"Updated! (ts={result['ts']})" if result else "Failed to update")

    elif args.action == "check":
        important = check_for_important_messages(hours_ago=args.hours)
        if important:
            print(f"Found {len(important)} important messages:\n")
            print(format_messages_for_context(important))
        else:
            print("No important messages found")


def cmd_sheets(args: argparse.Namespace) -> None:
    """Handle Google Sheets commands."""
    from integrations.sheets_api import (
        append_to_spreadsheet,
        format_spreadsheet_for_context,
        get_spreadsheet_info,
        read_spreadsheet,
        write_spreadsheet,
    )

    if args.action == "read":
        if not args.target_id:
            print("Error: spreadsheet_id required")
            sys.exit(1)
        data = read_spreadsheet(
            args.target_id,
            range_notation=args.range or "",
            max_rows=args.max_rows,
        )
        print(format_spreadsheet_for_context(data))

    elif args.action == "info":
        if not args.target_id:
            print("Error: spreadsheet_id required")
            sys.exit(1)
        info = get_spreadsheet_info(args.target_id)
        print(format_spreadsheet_for_context(info))

    elif args.action == "write":
        if not args.target_id or not args.values or not args.range:
            print("Error: spreadsheet_id, --range, and --values required")
            sys.exit(1)
        parsed = json.loads(args.values)
        result = write_spreadsheet(args.target_id, args.range, parsed)
        print(json.dumps(result, indent=2))

    elif args.action == "append":
        if not args.target_id or not args.values or not args.range:
            print("Error: spreadsheet_id, --range, and --values required")
            sys.exit(1)
        parsed = json.loads(args.values)
        result = append_to_spreadsheet(args.target_id, args.range, parsed)
        print(json.dumps(result, indent=2))


def cmd_docs(args: argparse.Namespace) -> None:
    """Handle Google Docs commands."""
    from integrations.docs_api import (
        format_document_for_context,
        get_document_info,
        read_document,
    )

    if args.action == "read":
        if not args.target_id:
            print("Error: document_id required")
            sys.exit(1)
        data = read_document(args.target_id)
        print(format_document_for_context(data, max_chars=args.max_chars))

    elif args.action == "info":
        if not args.target_id:
            print("Error: document_id required")
            sys.exit(1)
        data = get_document_info(args.target_id)
        char_count = len(data.body_text)
        print(f"Title: {data.title}")
        print(f"ID: {data.id}")
        print(f"URL: {data.url}")
        print(f"Content length: ~{char_count} chars")


def cmd_circle(args: argparse.Namespace) -> None:
    """Handle Circle commands (read-only)."""
    from integrations.circle_api import (
        format_chat_rooms_for_context,
        format_messages_for_context,
        format_notifications_for_context,
        format_posts_for_context,
        format_spaces_for_context,
        get_chat_messages,
        get_chat_rooms,
        get_member_posts,
        get_notifications,
        get_post,
        get_posts,
        get_spaces,
        search_posts,
    )

    if args.action == "spaces":
        spaces = get_spaces()
        print(format_spaces_for_context(spaces))

    elif args.action == "posts":
        if not args.target_id:
            print("Error: space_id required. Run 'circle spaces' first.")
            sys.exit(1)
        posts = get_posts(int(args.target_id), max_results=args.max)
        print(format_posts_for_context(posts))

    elif args.action == "post":
        if not args.target_id:
            print("Error: post_id required")
            sys.exit(1)
        post = get_post(int(args.target_id))
        if post:
            print(format_posts_for_context([post]))
        else:
            print("Post not found")

    elif args.action == "search":
        if not args.query:
            print("Error: search query required")
            sys.exit(1)
        posts = search_posts(args.query, max_results=args.max)
        print(format_posts_for_context(posts))

    elif args.action == "dms":
        rooms = get_chat_rooms(max_results=args.max)
        print(format_chat_rooms_for_context(rooms))

    elif args.action == "dm":
        if not args.target_id:
            print("Error: chat_room_uuid required. Run 'circle dms' first.")
            sys.exit(1)
        messages = get_chat_messages(args.target_id, max_results=args.max)
        print(format_messages_for_context(messages))

    elif args.action == "notifications":
        notifications = get_notifications(max_results=args.max)
        print(format_notifications_for_context(notifications))

    elif args.action == "feed":
        posts = get_member_posts(max_results=args.max)
        print(format_posts_for_context(posts))


def cmd_drive(args: argparse.Namespace) -> None:
    """Handle Google Drive commands."""
    from integrations.drive_api import (
        find_files,
        format_files_for_context,
        get_file_by_id,
        list_files,
    )

    if args.action == "find":
        if not args.query:
            print("Error: search query required")
            sys.exit(1)
        files = find_files(args.query, file_type=args.file_type, max_results=args.max)
        print(format_files_for_context(files))

    elif args.action == "list":
        files = list_files(file_type=args.file_type, max_results=args.max)
        print(format_files_for_context(files))

    elif args.action == "get":
        if not args.query:
            print("Error: file ID required")
            sys.exit(1)
        file = get_file_by_id(args.query)
        if file:
            print(format_files_for_context([file]))
        else:
            print("File not found")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Direct Platform Integrations")
    subparsers = parser.add_subparsers(dest="service", required=True)

    # Gmail
    gmail_parser = subparsers.add_parser("gmail", help="Gmail operations")
    gmail_parser.add_argument("action", choices=["list", "urgent", "unread", "read", "thread", "search", "attachments", "download-attachment", "create-draft", "send-draft"])
    gmail_parser.add_argument("message_id", nargs="?", default=None, help="Message/thread ID, or message being replied to (for create-draft)")
    gmail_parser.add_argument("--max", type=int, default=10)
    gmail_parser.add_argument("--query", default=None)
    gmail_parser.add_argument("--hours", type=int, default=None)
    gmail_parser.add_argument("--unread", action="store_true")
    gmail_parser.add_argument("--from-file", default=None, help="Path to markdown draft file (auto-reads recipient, subject, body, thread)")
    gmail_parser.add_argument("--to", default=None, help="Recipient for create-draft (manual mode)")
    gmail_parser.add_argument("--subject", dest="draft_subject", default=None, help="Subject for create-draft (manual mode)")
    gmail_parser.add_argument("--body", default=None, help="Body text for create-draft (manual mode)")
    gmail_parser.add_argument("--thread-id", default=None, help="Thread ID for threading the draft (manual mode)")
    gmail_parser.add_argument("--attachment", action="append", default=None, help="File path to attach to draft (can be used multiple times)")
    gmail_parser.add_argument("--attachment-id", default=None, help="Attachment ID for download-attachment command")
    gmail_parser.add_argument("--output-dir", default=None, help="Output directory for download-attachment command")
    _add_account_arg(gmail_parser)
    _add_all_accounts_arg(gmail_parser)

    # Calendar
    cal_parser = subparsers.add_parser("calendar", help="Calendar operations")
    cal_parser.add_argument("action", choices=["today", "upcoming", "soon", "create"])
    cal_parser.add_argument("--hours", type=int, default=24)
    # `create` args
    cal_parser.add_argument("--title", help="Event title (create)")
    cal_parser.add_argument("--start", help="ISO start, e.g. 2026-07-09T14:00:00 (create)")
    cal_parser.add_argument("--end", help="ISO end (create; omit to use --duration)")
    cal_parser.add_argument("--duration", type=int, default=30, help="Minutes if no --end (create)")
    cal_parser.add_argument("--attendees", help="Comma-separated emails (create)")
    cal_parser.add_argument("--location", help="Location (create)")
    cal_parser.add_argument("--description", help="Notes (create)")
    cal_parser.add_argument("--calendar", default="primary", help="Calendar id (default: the account's own)")
    _add_account_arg(cal_parser)
    _add_all_accounts_arg(cal_parser)

    # ClickUp (Locafy task tracker — this workspace's only task system)
    clickup_parser = subparsers.add_parser("clickup", help="ClickUp operations")
    clickup_parser.add_argument("action", choices=["my-tasks", "overdue", "due-soon"])
    clickup_parser.add_argument("--max", type=int, default=20)
    clickup_parser.add_argument("--days", type=int, default=3)
    clickup_parser.add_argument(
        "--include-closed",
        dest="include_closed",
        action="store_true",
        help="Include closed/done tasks in my-tasks",
    )

    # Slack
    slack_parser = subparsers.add_parser("slack", help="Slack operations")
    slack_parser.add_argument("action", choices=["channels", "messages", "send", "update", "check"])
    slack_parser.add_argument("channel", nargs="?", default=None)
    slack_parser.add_argument("message", nargs="?", default=None)
    slack_parser.add_argument("--ts", default=None, help="Message timestamp for update")
    slack_parser.add_argument("--hours", type=int, default=2)
    _add_workspace_arg(slack_parser)
    slack_parser.add_argument(
        "--all-workspaces",
        dest="all_workspaces",
        action="store_true",
        help="Run the 'check' action across every configured Slack workspace.",
    )

    # Google Sheets
    sheets_parser = subparsers.add_parser("sheets", help="Google Sheets operations")
    sheets_parser.add_argument("action", choices=["read", "info", "write", "append"])
    sheets_parser.add_argument("target_id", nargs="?", default=None, help="Spreadsheet ID")
    sheets_parser.add_argument("--range", default=None, help="A1 notation range")
    sheets_parser.add_argument("--values", default=None, help="JSON 2D array for write/append")
    sheets_parser.add_argument("--max-rows", type=int, default=500)
    _add_account_arg(sheets_parser)

    # Google Docs
    docs_parser = subparsers.add_parser("docs", help="Google Docs operations")
    docs_parser.add_argument("action", choices=["read", "info"])
    docs_parser.add_argument("target_id", nargs="?", default=None, help="Document ID")
    docs_parser.add_argument("--max-chars", type=int, default=4000)
    _add_account_arg(docs_parser)

    # Circle
    circle_parser = subparsers.add_parser("circle", help="Circle community operations (read-only)")
    circle_parser.add_argument("action", choices=["spaces", "posts", "post", "search", "dms", "dm", "notifications", "feed"])
    circle_parser.add_argument("target_id", nargs="?", default=None, help="space_id, post_id, or chat_room_uuid")
    circle_parser.add_argument("--query", default=None, help="Search query for search action")
    circle_parser.add_argument("--max", type=int, default=10)

    # Google Drive
    drive_parser = subparsers.add_parser("drive", help="Google Drive operations")
    drive_parser.add_argument("action", choices=["find", "list", "get"])
    drive_parser.add_argument("query", nargs="?", default=None, help="Search term or file ID")
    drive_parser.add_argument("--type", dest="file_type", default=None,
                              choices=["spreadsheet", "document", "folder", "presentation", "pdf"])
    drive_parser.add_argument("--max", type=int, default=10)
    _add_account_arg(drive_parser)

    args = parser.parse_args()

    # Apply the active Google profile / Slack workspace before dispatching so
    # every downstream integration call (gmail, calendar, sheets, docs, drive,
    # slack) picks it up via contextvars.
    account = getattr(args, "account", None)
    if account:
        from integrations.auth import set_active_account

        set_active_account(account)

    workspace = getattr(args, "workspace", None)
    if workspace:
        from integrations.slack_api import set_active_workspace

        set_active_workspace(workspace)

    try:
        if args.service == "gmail":
            cmd_gmail(args)
        elif args.service == "calendar":
            cmd_calendar(args)
        elif args.service == "clickup":
            cmd_clickup(args)
        elif args.service == "slack":
            cmd_slack(args)
        elif args.service == "sheets":
            cmd_sheets(args)
        elif args.service == "docs":
            cmd_docs(args)
        elif args.service == "circle":
            cmd_circle(args)
        elif args.service == "drive":
            cmd_drive(args)
    except Exception as e:
        print(json.dumps({"error": str(e), "type": "runtime"}, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
