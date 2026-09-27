"""CHAT_PERMISSIONS=full vs scoped: what the chat agent may touch."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_CHAT_DIR = Path(__file__).resolve().parents[2] / "chat"
sys.path.insert(0, str(_CHAT_DIR))

from engine import (  # noqa: E402
    ConversationEngine,
    _load_mcp_servers,
    _make_permission_callback,
    _repo_dirs_for,
)
from models import Channel, IncomingMessage, OutgoingMessage, Platform, User  # noqa: E402


def _decide(cb: Any, tool: str, path: str) -> str:
    res = asyncio.run(cb(tool, {"file_path": path}, None))
    return type(res).__name__


def test_full_mode_allows_writes_anywhere_but_credential_files(tmp_path: Path) -> None:
    cb = _make_permission_callback(tmp_path / "scripts", "full")
    allow = "PermissionResultAllow"
    assert _decide(cb, "Write", "/Users/x/Projects/locafy-website/src/app.tsx") == allow
    assert _decide(cb, "Edit", str(Path.home() / "Library/LaunchAgents/com.x.plist")) == allow
    assert _decide(cb, "Bash", "") == "PermissionResultAllow"
    assert _decide(cb, "Write", "/Users/x/Projects/api/.env") == "PermissionResultDeny"
    assert _decide(cb, "Edit", "/Users/x/app/credentials.json") == "PermissionResultDeny"
    assert _decide(cb, "Write", "/Users/x/.notebooklm/master_token.json") == "PermissionResultDeny"


def test_scoped_mode_still_fences_to_own_scripts(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    cb = _make_permission_callback(scripts, "scoped")
    assert _decide(cb, "Write", str(scripts / "new_job.py")) == "PermissionResultAllow"
    assert _decide(cb, "Write", str(tmp_path / "elsewhere.py")) == "PermissionResultDeny"
    assert _decide(cb, "Write", str(scripts / ".env")) == "PermissionResultDeny"


def test_full_mode_grants_every_repo_on_every_turn(tmp_path: Path) -> None:
    for name in ("locafy-website", "podcast-kit", ".hidden"):
        (tmp_path / name).mkdir()
    dirs = _repo_dirs_for("what's on my calendar", tmp_path, ["locafy-website", "triton"], "full")
    assert dirs == sorted([str(tmp_path / "locafy-website"), str(tmp_path / "podcast-kit")])
    # scoped: a calendar question grants nothing
    assert _repo_dirs_for("what's on my calendar", tmp_path, ["locafy-website"], "scoped") == []


def test_full_mode_loads_every_configured_mcp_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude.json").write_text(json.dumps({"mcpServers": {
        "mcp-scraper": {"command": "npx"}, "vercel": {"url": "https://mcp.vercel.com"},
        "redis-iris": {"command": "uv"}, "broken": None,
    }}))
    assert set(_load_mcp_servers("full")) == {"mcp-scraper", "vercel", "redis-iris"}
    assert set(_load_mcp_servers("scoped")) == {"mcp-scraper", "redis-iris"}


class _Store:
    def get(self, *_: Any) -> None:
        return None

    def create(self, *_: Any) -> None:
        pass


def test_full_engine_preapproves_mcp_and_tells_agent_it_is_unrestricted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import claude_agent_sdk
    from claude_agent_sdk import AssistantMessage, TextBlock

    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".claude.json").write_text(json.dumps({"mcpServers": {"vercel": {"url": "u"}}}))
    (tmp_path / "Projects" / "locafy-website").mkdir(parents=True)
    captured: dict[str, Any] = {}

    async def fake_query(*, prompt: Any, options: Any) -> Any:
        captured["allowed"] = options.allowed_tools
        captured["append"] = options.system_prompt["append"]
        captured["add_dirs"] = options.add_dirs
        captured["mcp"] = options.mcp_servers
        yield AssistantMessage(content=[TextBlock(text="ok")], model="m")

    monkeypatch.setattr(claude_agent_sdk, "query", fake_query)
    engine = ConversationEngine(_Store(), tmp_path, permissions="full",  # type: ignore[arg-type]
                                repo_workspace_root=tmp_path / "Projects")
    incoming = IncomingMessage(text="hi", user=User(Platform.IMESSAGE, "u"),
                               channel=Channel(Platform.IMESSAGE, "c"), platform=Platform.IMESSAGE)

    async def run() -> list[OutgoingMessage]:
        return [o async for o in engine.handle_message(incoming)]

    asyncio.run(run())
    assert "mcp__vercel" in captured["allowed"]
    assert "vercel" in captured["mcp"]
    assert "full read/write access on this Mac" in captured["append"]
    assert captured["add_dirs"] == [str(tmp_path / "Projects" / "locafy-website")]


@pytest.mark.parametrize(("key", "advertised"), [("ts-key", True), ("", False)])
def test_judgment_layer_is_advertised_only_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str, advertised: bool
) -> None:
    import claude_agent_sdk
    from claude_agent_sdk import AssistantMessage, TextBlock

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("TYPESAFE_API_KEY", key)
    captured: dict[str, Any] = {}

    async def fake_query(*, prompt: Any, options: Any) -> Any:
        captured["append"] = options.system_prompt["append"]
        yield AssistantMessage(content=[TextBlock(text="ok")], model="m")

    monkeypatch.setattr(claude_agent_sdk, "query", fake_query)
    engine = ConversationEngine(_Store(), tmp_path, permissions="scoped")  # type: ignore[arg-type]
    incoming = IncomingMessage(text="hi", user=User(Platform.IMESSAGE, "u"),
                               channel=Channel(Platform.IMESSAGE, "c"), platform=Platform.IMESSAGE)

    async def run() -> list[OutgoingMessage]:
        return [o async for o in engine.handle_message(incoming)]

    asyncio.run(run())
    assert ("Judgment Layer" in captured["append"]) is advertised


def test_scoped_chat_preapproves_scraper_research_but_not_sends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import claude_agent_sdk
    from claude_agent_sdk import AssistantMessage, TextBlock

    monkeypatch.setenv("HOME", str(tmp_path))
    captured: dict[str, Any] = {}

    async def fake_query(*, prompt: Any, options: Any) -> Any:
        captured["allowed"] = options.allowed_tools
        yield AssistantMessage(content=[TextBlock(text="ok")], model="m")

    monkeypatch.setattr(claude_agent_sdk, "query", fake_query)
    engine = ConversationEngine(_Store(), tmp_path, permissions="scoped")  # type: ignore[arg-type]
    incoming = IncomingMessage(text="hi", user=User(Platform.IMESSAGE, "u"),
                               channel=Channel(Platform.IMESSAGE, "c"), platform=Platform.IMESSAGE)

    async def run() -> list[OutgoingMessage]:
        return [o async for o in engine.handle_message(incoming)]

    asyncio.run(run())
    assert "mcp__mcp-scraper__search_serp" in captured["allowed"]
    assert "mcp__mcp-scraper" not in captured["allowed"]
    assert not [t for t in captured["allowed"] if "send" in t or "browser" in t]
    assert not [t for t in captured["allowed"] if "apify" in t]
