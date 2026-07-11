"""
[Platform Name] Direct Integration for Second Brain.

TODO: Replace [Platform Name] with your service name (e.g., "GitHub", "Notion", "Discord").

Usage:
    uv run python -m integrations.your_service list --max 5
    uv run python -m integrations.your_service search --query "something"

Setup:
    1. Get your API token/credentials from [platform's developer settings]
    2. Add to .env: YOUR_SERVICE_TOKEN=your_token_here
    3. Add the registry entry in registry.py (see Step 5 below)
    4. Add subcommands to query.py (see Step 6 below)
    5. Test: cd .claude/scripts && uv run python -m integrations.your_service list
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Add parent dir for config imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import LOCAL_TZ, now_local  # noqa: E402
from sanitize import sanitize_external_text  # noqa: E402
from shared import with_retry  # noqa: E402


# ---------------------------------------------------------------------------
# Step 1: Define your data model
# ---------------------------------------------------------------------------
# Create a dataclass for the main data type this integration returns.
# Keep it simple — only include fields you'll actually use.

@dataclass
class Item:
    """Represents a single item from [Platform Name].

    TODO: Rename this class and adjust fields to match your platform's data.
    Examples: GitHubIssue, NotionPage, DiscordMessage, LinearTicket
    """

    id: str
    title: str
    created_at: datetime
    url: str = ""
    body: str | None = None
    labels: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Step 2: Authentication
# ---------------------------------------------------------------------------
# Create a function that returns an authenticated client/service.
# Two common patterns:
#   - Token-based: Read from env var, pass to SDK client
#   - OAuth: Use shared Google credentials (see auth.py)

def get_client() -> Any:
    """Build authenticated [Platform Name] client.

    TODO: Replace with your platform's SDK initialization.

    Token-based example (GitHub, Linear, Discord):
        import os
        token = os.getenv("YOUR_SERVICE_TOKEN")
        if not token:
            raise ValueError(
                "YOUR_SERVICE_TOKEN not set in .env\\n"
                "Get one from https://your-platform.com/settings/tokens"
            )
        return YourSDK(token=token)

    Google OAuth example (Sheets, Drive, etc.):
        from googleapiclient.discovery import build
        from integrations.auth import get_google_credentials
        creds = get_google_credentials()
        return build("service", "v1", credentials=creds)
    """
    raise NotImplementedError("TODO: Set up authentication for your platform")


# ---------------------------------------------------------------------------
# Step 3: Core query functions
# ---------------------------------------------------------------------------
# These are the functions the heartbeat and CLI will call.
# Keep them focused: fetch data, parse into dataclasses, return.
# Use with_retry() for any API call to handle transient failures.

def list_items(max_results: int = 10, query: str = "") -> list[Item]:
    """List items from [Platform Name].

    TODO: Implement your platform's list/search API call.
    """
    client = get_client()

    # Example pattern:
    # results = with_retry(lambda: client.items.list(limit=max_results, q=query))
    # return [Item(id=r.id, title=r.title, ...) for r in results]

    raise NotImplementedError("TODO: Implement list_items")


def get_item(item_id: str) -> Item | None:
    """Get a single item by ID.

    TODO: Implement your platform's get-by-ID API call.
    """
    client = get_client()

    # Example pattern:
    # try:
    #     r = with_retry(lambda: client.items.get(item_id))
    #     return Item(id=r.id, title=r.title, ...)
    # except Exception as e:
    #     print(f"Error getting item {item_id}: {e}")
    #     return None

    raise NotImplementedError("TODO: Implement get_item")


# ---------------------------------------------------------------------------
# Step 4: Format for context
# ---------------------------------------------------------------------------
# These functions format your data for inclusion in Claude's context prompt.
# The heartbeat injects this text, so keep it concise and scannable.
# IMPORTANT: Always sanitize external text before including in context.

def format_items_for_context(items: list[Item], max_chars: int = 2000) -> str:
    """Format items for inclusion in Claude's context prompt.

    TODO: Adjust formatting to match your data. Keep it concise —
    this text gets injected into the heartbeat prompt.
    """
    if not items:
        return "No items found."

    output: list[str] = []
    chars = 0

    for item in items:
        title = sanitize_external_text(item.title, "your_service")
        date_str = item.created_at.strftime("%Y-%m-%d %H:%M")
        entry = f"- **{title}** [{item.id}]\n  Date: {date_str}"

        if chars + len(entry) > max_chars:
            remaining = len(items) - len(output)
            output.append(f"\n... and {remaining} more items")
            break

        output.append(entry)
        chars += len(entry)

    return "\n\n".join(output)


# ---------------------------------------------------------------------------
# Step 5: Register in registry.py
# ---------------------------------------------------------------------------
# Add an entry to _REGISTRY in integrations/registry.py:
#
#     "your_service": IntegrationInfo(
#         name="your_service",
#         display_name="Your Service",
#         auth_type="token",               # or "google_oauth"
#         required_config=["YOUR_SERVICE_TOKEN"],
#         module_path="integrations.your_service",
#     ),


# ---------------------------------------------------------------------------
# Step 6: Add subcommands to query.py
# ---------------------------------------------------------------------------
# In the direct-integrations skill's query.py, add a new elif block:
#
#     elif args.platform == "your-service":
#         if args.command == "list":
#             from integrations.your_service import list_items, format_items_for_context
#             items = list_items(max_results=args.max, query=args.query)
#             print(format_items_for_context(items))
#         elif args.command == "get":
#             from integrations.your_service import get_item
#             item = get_item(args.id)
#             print(item)


# ---------------------------------------------------------------------------
# CLI for testing (run directly: python -m integrations.your_service list)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="[Platform Name] integration")
    parser.add_argument("command", choices=["list", "get", "search"])
    parser.add_argument("--max", type=int, default=10)
    parser.add_argument("--query", default="")
    parser.add_argument("--id", default="")

    args = parser.parse_args()

    if args.command == "list":
        results = list_items(max_results=args.max, query=args.query)
        print(format_items_for_context(results))

    elif args.command == "get":
        if not args.id:
            print("--id required for get command")
            sys.exit(1)
        result = get_item(args.id)
        if result:
            print(f"{result.title} ({result.id})")
            if result.body:
                print(result.body)
        else:
            print("Item not found")

    elif args.command == "search":
        if not args.query:
            print("--query required for search command")
            sys.exit(1)
        results = list_items(max_results=args.max, query=args.query)
        print(format_items_for_context(results))
