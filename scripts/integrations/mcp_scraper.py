"""
MCP Scraper Direct Integration for Second Brain.

Calls MCP Scraper tools (SERP, page extraction, hosted browser, social) from
deterministic scripts over its hosted JSON-RPC endpoint — no agent, no MCP
session. In chat, Ricky uses the same tools through the `mcp-scraper` MCP server.

Usage:
    uv run python -m integrations.mcp_scraper status
    uv run python -m integrations.mcp_scraper call search_serp --args '{"query": "plumber austin"}'

Setup:
    1. Get your API key from https://mcpscraper.dev
    2. Add to .env: MCP_SCRAPER_API_KEY=sk_live_...
       (falls back to the key the `mcp-scraper` MCP server uses in ~/.claude.json)
    3. Test: cd .claude/scripts && uv run python -m integrations.mcp_scraper status
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ENDPOINT = "https://mcpscraper.dev/mcp"
MCP_SERVER_NAME = "mcp-scraper"
RETRYABLE_STATUS = (429, 500, 502, 503, 504)


class McpScraperError(RuntimeError):
    """The tool call failed, or MCP Scraper is not configured."""


def api_key() -> str:
    """Prefer MCP_SCRAPER_API_KEY from .env; fall back to the key the MCP
    server already uses in ~/.claude.json so scripts need no new plumbing."""
    key = os.environ.get("MCP_SCRAPER_API_KEY", "").strip()
    if key:
        return key
    try:
        cfg = json.loads(Path.home().joinpath(".claude.json").read_text())
        return str(cfg["mcpServers"][MCP_SERVER_NAME]["env"]["MCP_SCRAPER_API_KEY"]).strip()
    except Exception as exc:  # noqa: BLE001
        raise McpScraperError(
            f"no MCP_SCRAPER_API_KEY available ({type(exc).__name__})"
        ) from exc


def _ssl_context() -> ssl.SSLContext:
    # python.org builds on macOS ship without system roots; certifi has them.
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _parse_rpc(body: str) -> dict[str, Any]:
    """The endpoint answers as JSON or as a server-sent event stream."""
    for line in body.splitlines():
        if line.startswith("data:"):
            body = line[len("data:"):]
            break
    parsed: dict[str, Any] = json.loads(body)
    return parsed


def _unwrap(result: dict[str, Any]) -> Any:
    """A tool's payload: structured content if present, else its text (parsed if JSON)."""
    if result.get("structuredContent") is not None:
        return result["structuredContent"]
    text = "\n".join(
        part.get("text", "") for part in result.get("content", []) if part.get("type") == "text"
    )
    try:
        return json.loads(text)
    except ValueError:
        return text


def call_tool(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    timeout: float = 120,
    retries: int = 2,
) -> Any:
    """
    Call one MCP Scraper tool and return its payload.

    Retries only on transport errors and 429/5xx. A tool that ran and reported
    failure raises immediately — re-running it would bill twice.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    }
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={
            "x-api-key": api_key(),
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as resp:
                body = resp.read().decode()
            break
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRYABLE_STATUS or attempt == retries:
                raise McpScraperError(f"{name}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == retries:
                raise McpScraperError(f"{name}: {type(exc).__name__}: {exc}") from exc
        time.sleep(2**attempt)

    rpc = _parse_rpc(body)
    if rpc.get("error"):
        raise McpScraperError(f"{name}: {rpc['error'].get('message', rpc['error'])}")
    result = rpc.get("result") or {}
    payload_out = _unwrap(result)
    if result.get("isError"):
        raise McpScraperError(f"{name}: {str(payload_out)[:300]}")
    return payload_out


def read_page(url: str, *, ready: Any = None, attempts: int = 6, wait: float = 4.0) -> str:
    """
    Visible text of a JavaScript-rendered page, via a hosted browser session.

    Args:
        url: Page to load.
        ready: Optional callable(text) -> bool. The page is re-read until it
            returns True, for pages that keep loading after navigation.

    The session is always closed — it bills per minute while open.
    """
    for attempt in range(3):
        try:
            opened = call_tool("browser_open", {"timeout_seconds": 180})
            break
        except McpScraperError as exc:
            # The account's concurrency slots are shared with chat and other
            # jobs. No session was opened, so waiting for a slot costs nothing.
            if "concurrent" not in str(exc) or attempt == 2:
                raise
            time.sleep(30)
    session_id = opened["session_id"]
    try:
        call_tool("browser_goto", {"session_id": session_id, "url": url})
        text = ""
        for _ in range(attempts):
            text = str(call_tool("browser_read", {"session_id": session_id}).get("text", ""))
            if text and (ready is None or ready(text)):
                return text
            time.sleep(wait)
        return text
    finally:
        try:
            call_tool("browser_close", {"session_id": session_id}, retries=0)
        except McpScraperError:
            pass  # abandoned sessions are auto-closed after a short idle window


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP Scraper direct integration")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Check the key and show the credit balance")
    p_call = sub.add_parser("call", help="Call any tool")
    p_call.add_argument("tool")
    p_call.add_argument("--args", default="{}", help="JSON arguments")

    args = parser.parse_args()
    try:
        if args.command == "status":
            info = call_tool("credits_info")
            balance = info.get("balanceCredits") if isinstance(info, dict) else None
            print(f"MCP Scraper: OK — {balance:,.0f} credits" if balance is not None
                  else f"MCP Scraper: OK\n{str(info)[:400]}")
        else:
            out = call_tool(args.tool, json.loads(args.args))
            print(out if isinstance(out, str) else json.dumps(out, indent=2)[:20000])
    except McpScraperError as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
