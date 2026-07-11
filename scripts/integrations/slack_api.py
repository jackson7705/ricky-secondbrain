"""
Slack Direct Integration for Second Brain.

Read channel messages and send notifications via Slack Bot Token.

Usage:
    uv run python -m integrations.slack_api channels
    uv run python -m integrations.slack_api messages general --hours 2
    uv run python -m integrations.slack_api send second-brain "Test message"
    uv run python -m integrations.slack_api check
"""

from __future__ import annotations

import sys
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

# Add parent dir for config imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (  # noqa: E402
    SLACK_BOT_TOKEN,
    SLACK_MONITORED_CHANNELS,
    SLACK_OWNER_USER_ID,
    list_slack_workspaces,
    slack_token_for,
    slack_workspace_setting,
)
from sanitize import sanitize_external_text  # noqa: E402
from shared import with_retry  # noqa: E402

# Cache for user name resolution, keyed by (workspace, user_id) so display
# names from different Slack workspaces don't collide.
_user_name_cache: dict[tuple[str, str], str] = {}

# The active Slack workspace for the current execution context.
# CLI wrappers set this based on --workspace; heartbeat loops over all
# configured workspaces by calling `set_active_workspace` before each call.
_active_workspace: ContextVar[str | None] = ContextVar("active_slack_workspace", default=None)


def set_active_workspace(workspace: str | None) -> None:
    """Set the active Slack workspace for this execution context."""
    _active_workspace.set(workspace.lower() if workspace else None)


def get_active_workspace() -> str | None:
    """Return the active Slack workspace, if one was set."""
    return _active_workspace.get()


def _resolve_workspace(workspace: str | None) -> str | None:
    """Resolve workspace arg via explicit > contextvar > None."""
    if workspace is not None:
        return workspace.lower()
    return _active_workspace.get()


@dataclass
class SlackMessage:
    """Represents a Slack message."""

    ts: str
    user_id: str
    user_name: str | None
    text: str
    channel: str
    thread_ts: str | None = None
    workspace: str | None = None


def get_slack_client(workspace: str | None = None) -> Any:
    """
    Create an authenticated Slack WebClient for a workspace.

    Args:
        workspace: Named workspace (e.g. "growthpro"). If omitted, uses the
                   context-active workspace, then `DEFAULT_SLACK_WORKSPACE`,
                   then falls back to the legacy single `SLACK_BOT_TOKEN`.
    """
    from slack_sdk import WebClient

    resolved = _resolve_workspace(workspace)
    token = slack_token_for(resolved)

    if not token:
        hint = (
            f"SLACK_BOT_TOKEN_{resolved.upper()}" if resolved else "SLACK_BOT_TOKEN"
        )
        raise ValueError(
            f"{hint} not set in .env\n"
            "Create a Slack app at https://api.slack.com/apps and add a Bot Token."
        )

    client: Any = WebClient(token=token)
    return client


def get_channel_id(channel_name: str) -> str | None:
    """Resolve a channel name (without #) to its ID."""
    client = get_slack_client()
    name = channel_name.lstrip("#")

    try:
        cursor: str | None = None
        while True:
            kwargs: dict[str, Any] = {"types": "public_channel,private_channel", "limit": 200}
            if cursor:
                kwargs["cursor"] = cursor

            result = with_retry(lambda kw=kwargs: client.conversations_list(**kw))
            channels: list[dict[str, Any]] = result.get("channels", [])

            for ch in channels:
                if ch.get("name") == name:
                    channel_id: str = ch["id"]
                    return channel_id

            # Check pagination
            metadata = result.get("response_metadata", {})
            cursor = metadata.get("next_cursor")
            if not cursor:
                break

    except Exception as e:
        print(f"Error listing channels: {e}")

    return None


def resolve_user_name(user_id: str) -> str:
    """Resolve a Slack user ID to display name (with per-workspace caching)."""
    workspace_key = _resolve_workspace(None) or ""
    cache_key = (workspace_key, user_id)
    if cache_key in _user_name_cache:
        return _user_name_cache[cache_key]

    try:
        client = get_slack_client()
        result = with_retry(lambda: client.users_info(user=user_id))
        user_data: dict[str, Any] = result.get("user", {})
        profile: dict[str, str] = user_data.get("profile", {})
        name = profile.get("display_name") or profile.get("real_name") or user_id
        _user_name_cache[cache_key] = name
        return name
    except Exception:
        _user_name_cache[cache_key] = user_id
        return user_id


def get_recent_messages(
    channel_id: str,
    hours_ago: int = 2,
    limit: int = 20,
) -> list[SlackMessage]:
    """
    Get recent messages from a channel.

    Args:
        channel_id: Channel ID (not name — use get_channel_id() to resolve)
        hours_ago: How far back to look
        limit: Max messages to return
    """
    client = get_slack_client()

    oldest = str(time.time() - (hours_ago * 3600))

    try:
        result = with_retry(lambda: client.conversations_history(channel=channel_id, oldest=oldest, limit=limit))
        raw_messages: list[dict[str, Any]] = result.get("messages", [])

        messages: list[SlackMessage] = []
        for msg in raw_messages:
            # Skip bot messages and system messages
            if msg.get("subtype") in ("bot_message", "channel_join", "channel_leave"):
                continue

            user_id = msg.get("user", "")
            user_name = resolve_user_name(user_id) if user_id else None

            messages.append(
                SlackMessage(
                    ts=msg.get("ts", ""),
                    user_id=user_id,
                    user_name=user_name,
                    text=msg.get("text", ""),
                    channel=channel_id,
                    thread_ts=msg.get("thread_ts"),
                    workspace=_resolve_workspace(None),
                )
            )

        return messages
    except Exception as e:
        print(f"Error fetching messages: {e}")
        return []


def send_notification(
    channel: str, text: str, thread_ts: str | None = None
) -> dict[str, Any] | None:
    """
    Send a message to a Slack channel.

    Args:
        channel: Channel name (with or without #) or channel ID
        text: Message text (supports Slack markdown)
        thread_ts: Optional thread timestamp to reply in a thread

    Returns:
        Dict with 'channel' (resolved ID) and 'ts' (message timestamp), or None on failure.
    """
    client = get_slack_client()

    # Resolve channel name to ID if needed
    target = channel
    if not target.startswith("C") and not target.startswith("D"):
        resolved = get_channel_id(target)
        if not resolved:
            print(f"Channel not found: {channel}")
            return None
        target = resolved

    try:
        kwargs: dict[str, Any] = {"channel": target, "text": text}
        if thread_ts:
            kwargs["thread_ts"] = thread_ts

        response = with_retry(lambda: client.chat_postMessage(**kwargs))
        return {"channel": response.get("channel", target), "ts": response.get("ts", "")}
    except Exception as e:
        print(f"Error sending message: {e}")
        return None


def update_message(
    channel: str, ts: str, text: str
) -> dict[str, Any] | None:
    """
    Update an existing Slack message.

    Args:
        channel: Channel name (with or without #) or channel ID
        ts: Timestamp of the message to update
        text: New message text

    Returns:
        Dict with 'channel' and 'ts', or None on failure.
    """
    client = get_slack_client()

    # Resolve channel name to ID if needed
    target = channel
    if not target.startswith("C") and not target.startswith("D"):
        resolved = get_channel_id(target)
        if not resolved:
            print(f"Channel not found: {channel}")
            return None
        target = resolved

    try:
        response = with_retry(lambda: client.chat_update(channel=target, ts=ts, text=text))
        return {"channel": response.get("channel", target), "ts": response.get("ts", "")}
    except Exception as e:
        print(f"Error updating message: {e}")
        return None


def check_for_important_messages(
    channels: list[str] | None = None,
    hours_ago: int = 2,
) -> list[SlackMessage]:
    """
    Check monitored channels in the active workspace for important messages.

    Channels and owner user ID are resolved per-workspace when a workspace is
    active (e.g. `SLACK_MONITORED_CHANNELS_GROWTHPRO` /
    `SLACK_OWNER_USER_ID_GROWTHPRO`), falling back to the unsuffixed env vars.
    """
    workspace = _resolve_workspace(None)

    if channels is None:
        scoped_channels = slack_workspace_setting(
            "SLACK_MONITORED_CHANNELS", workspace, default=""
        )
        if scoped_channels:
            channel_names = [c.strip() for c in scoped_channels.split(",") if c.strip()]
        else:
            channel_names = SLACK_MONITORED_CHANNELS
    else:
        channel_names = channels

    owner_id = slack_workspace_setting(
        "SLACK_OWNER_USER_ID", workspace, default=SLACK_OWNER_USER_ID
    )

    all_messages: list[SlackMessage] = []

    for ch_name in channel_names:
        ch_name = ch_name.strip()
        if not ch_name:
            continue
        ch_id = get_channel_id(ch_name)
        if not ch_id:
            print(f"Warning: Could not find channel #{ch_name}")
            continue

        messages = get_recent_messages(ch_id, hours_ago=hours_ago, limit=10)

        # Filter for potentially important messages (mentions owner or keywords)
        for msg in messages:
            is_important = False

            # Direct mentions of owner
            if owner_id and f"<@{owner_id}>" in msg.text:
                is_important = True

            # @here or @channel
            if "<!here>" in msg.text or "<!channel>" in msg.text:
                is_important = True

            if is_important:
                all_messages.append(msg)

    return all_messages


def check_for_important_messages_all(
    hours_ago: int = 2,
) -> list[SlackMessage]:
    """
    Run `check_for_important_messages` across every configured workspace.

    Used by the heartbeat to monitor both the `growthpro` and `wonderly`
    workspaces (and any future ones) in a single call. Messages from
    different workspaces are tagged via `SlackMessage.workspace`.
    """
    workspaces = list_slack_workspaces()
    if not workspaces:
        # Legacy single-token path
        return check_for_important_messages(hours_ago=hours_ago)

    combined: list[SlackMessage] = []
    previous = _active_workspace.get()
    try:
        for ws in workspaces:
            _active_workspace.set(ws)
            try:
                combined.extend(check_for_important_messages(hours_ago=hours_ago))
            except Exception as e:
                print(f"Warning: Slack check failed for workspace '{ws}': {e}")
    finally:
        _active_workspace.set(previous)

    return combined


def format_messages_for_context(messages: list[SlackMessage], max_chars: int = 2000) -> str:
    """Format messages for inclusion in Claude's context prompt."""
    if not messages:
        return "No messages found."

    output: list[str] = []
    chars = 0

    for msg in messages:
        dt = datetime.fromtimestamp(float(msg.ts))
        time_str = dt.strftime("%H:%M")
        name = sanitize_external_text(msg.user_name or msg.user_id, "slack")
        ws_tag = f" [{msg.workspace}]" if msg.workspace else ""

        entry = (
            f"- [{time_str}]{ws_tag} **{name}**: "
            f"{sanitize_external_text(msg.text[:200], 'slack')}"
        )

        if chars + len(entry) > max_chars:
            remaining = len(messages) - len(output)
            output.append(f"\n... and {remaining} more messages")
            break

        output.append(entry)
        chars += len(entry)

    return "\n\n".join(output)


# CLI for testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Slack integration")
    parser.add_argument("command", choices=["messages", "channels", "send", "update", "check"])
    parser.add_argument("channel", nargs="?", default=None, help="Channel name for messages/send")
    parser.add_argument("message", nargs="?", default=None, help="Message text for send/update")
    parser.add_argument("--ts", default=None, help="Message timestamp for update")
    parser.add_argument("--hours", type=int, default=2)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--workspace",
        default=None,
        help="Named workspace (e.g. growthpro). Uses default if omitted.",
    )

    args = parser.parse_args()

    if args.workspace:
        set_active_workspace(args.workspace)

    if args.command == "channels":
        slack_client = get_slack_client()
        result_data = slack_client.conversations_list(types="public_channel", limit=100)
        for ch in result_data.get("channels", []):
            print(f"  #{ch['name']} ({ch['id']})")

    elif args.command == "messages":
        if not args.channel:
            print("Channel name required: slack_api.py messages <channel> [--hours N]")
            sys.exit(1)
        ch_id = get_channel_id(args.channel)
        if not ch_id:
            print(f"Channel not found: {args.channel}")
            sys.exit(1)
        msgs = get_recent_messages(ch_id, hours_ago=args.hours, limit=args.limit)
        print(format_messages_for_context(msgs))

    elif args.command == "send":
        if not args.channel or not args.message:
            print("Usage: slack_api.py send <channel> <message>")
            sys.exit(1)
        result = send_notification(args.channel, args.message)
        print(f"Sent! (ts={result['ts']})" if result else "Failed to send")

    elif args.command == "update":
        if not args.channel or not args.ts or not args.message:
            print("Usage: slack_api.py update <channel> <message> --ts <timestamp>")
            sys.exit(1)
        result = update_message(args.channel, args.ts, args.message)
        print(f"Updated! (ts={result['ts']})" if result else "Failed to update")

    elif args.command == "check":
        important = check_for_important_messages(hours_ago=args.hours)
        if important:
            print(f"Found {len(important)} important messages:")
            print(format_messages_for_context(important))
        else:
            print("No important messages found")
