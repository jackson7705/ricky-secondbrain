"""The chat prompt only advertises the TypeSafe judgment layer when it is configured."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

_CHAT_DIR = Path(__file__).resolve().parents[2] / "chat"
sys.path.insert(0, str(_CHAT_DIR))

from engine import ConversationEngine  # noqa: E402
from models import Channel, IncomingMessage, OutgoingMessage, Platform, User  # noqa: E402


class _Store:
    def get(self, *_: Any) -> None:
        return None

    def create(self, *_: Any) -> None:
        pass


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
    engine = ConversationEngine(_Store(), tmp_path)  # type: ignore[arg-type]
    incoming = IncomingMessage(text="hi", user=User(Platform.IMESSAGE, "u"),
                               channel=Channel(Platform.IMESSAGE, "c"), platform=Platform.IMESSAGE)

    async def run() -> list[OutgoingMessage]:
        return [o async for o in engine.handle_message(incoming)]

    asyncio.run(run())
    assert ("Judgment Layer" in captured["append"]) is advertised
