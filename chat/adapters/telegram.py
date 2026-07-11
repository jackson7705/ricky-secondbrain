"""Telegram adapter — raw Bot API long-polling (no extra dependency).

Works on any OS (unlike BlueBubbles). Create a bot via @BotFather, grab the
token, and message it. Only user IDs in the allowlist can command Ricky.

To find your Telegram numeric user id: message @userinfobot, or check the
`raw_event` logged on first message.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import aiohttp

from models import Channel, IncomingMessage, OutgoingMessage, Platform, Thread, User

API = "https://api.telegram.org/bot{token}/{method}"
TG_MAX = 4096  # Telegram hard limit per message


class TelegramAdapter:
    """Telegram Bot API adapter using getUpdates long-polling."""

    def __init__(
        self,
        bot_token: str,
        allowed_user_ids: list[str],
        session_store: Any | None = None,
    ) -> None:
        self.token = bot_token
        self.allowed = {str(u).strip() for u in allowed_user_ids if str(u).strip()}
        self.session_store = session_store
        self._session: aiohttp.ClientSession | None = None
        self._offset = 0
        self._running = False

    @property
    def platform(self) -> Platform:
        return Platform.TELEGRAM

    async def connect(self) -> None:
        self._session = aiohttp.ClientSession()
        # Validate token + clear any stale webhook so getUpdates works
        me = await self._call("getMe")
        await self._call("deleteWebhook", {"drop_pending_updates": False})
        self._running = True
        uname = (me or {}).get("result", {}).get("username", "?")
        print(f"[{datetime.now()}] Telegram adapter connected (@{uname})")

    async def disconnect(self) -> None:
        self._running = False
        if self._session:
            await self._session.close()
            print(f"[{datetime.now()}] Telegram adapter disconnected")

    async def listen(self) -> Any:
        """Long-poll getUpdates and yield allowed messages."""
        while self._running:
            try:
                data = await self._call("getUpdates", {"offset": self._offset, "timeout": 25}, timeout=35)
            except Exception as e:  # noqa: BLE001
                print(f"[{datetime.now()}] Telegram poll error: {e}")
                await asyncio.sleep(3)
                continue
            for upd in (data or {}).get("result", []):
                self._offset = max(self._offset, upd["update_id"] + 1)
                msg = upd.get("message") or upd.get("edited_message")
                if not msg:
                    continue
                incoming = self._normalize(msg)
                if incoming is not None:
                    yield incoming

    async def send(self, message: OutgoingMessage) -> str | None:
        chat_id = message.channel.platform_id
        first_id: str | None = None
        for chunk in self._split(message.text):
            res = await self._call("sendMessage", {"chat_id": chat_id, "text": chunk,
                                                   "disable_web_page_preview": True})
            if res and first_id is None:
                first_id = str(res.get("result", {}).get("message_id", "")) or None
        return first_id

    async def update(self, message: OutgoingMessage) -> None:
        # Telegram edits are per-message; simplest is to post a fresh message.
        await self.send(message)

    async def send_typing(self, channel: Channel) -> None:
        await self._call("sendChatAction", {"chat_id": channel.platform_id, "action": "typing"})

    # ── helpers ──────────────────────────────────────────────────────
    def _is_allowed(self, user_id: str) -> bool:
        if not self.allowed:
            return False  # fail closed
        return str(user_id) in self.allowed

    def _normalize(self, msg: dict[str, Any]) -> IncomingMessage | None:
        frm = msg.get("from", {})
        user_id = str(frm.get("id", ""))
        if not self._is_allowed(user_id):
            return None
        chat = msg.get("chat", {})
        chat_id = str(chat.get("id", ""))
        text = msg.get("text") or msg.get("caption") or ""
        name = frm.get("username") or frm.get("first_name") or user_id
        user = User(Platform.TELEGRAM, user_id, display_name=name)
        channel = Channel(Platform.TELEGRAM, chat_id, is_dm=(chat.get("type") == "private"))
        thread = Thread(thread_id=chat_id)
        return IncomingMessage(
            text=text, user=user, channel=channel, platform=Platform.TELEGRAM,
            thread=thread, platform_message_id=str(msg.get("message_id", "")),
            raw_event=msg,
        )

    async def _call(self, method: str, params: dict | None = None, timeout: int = 20) -> dict | None:
        assert self._session is not None
        url = API.format(token=self.token, method=method)
        try:
            async with self._session.post(url, json=params or {},
                                          timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                return await r.json()
        except Exception as e:  # noqa: BLE001
            print(f"[{datetime.now()}] Telegram {method} error: {e}")
            return None

    @staticmethod
    def _split(text: str, max_length: int = TG_MAX) -> list[str]:
        if len(text) <= max_length:
            return [text]
        chunks, remaining = [], text
        while remaining:
            if len(remaining) <= max_length:
                chunks.append(remaining)
                break
            cut = remaining.rfind("\n\n", 0, max_length)
            if cut < max_length // 2:
                cut = remaining.rfind("\n", 0, max_length)
            if cut < max_length // 2:
                cut = remaining.rfind(" ", 0, max_length)
            if cut < max_length // 2:
                cut = max_length
            chunks.append(remaining[:cut])
            remaining = remaining[cut:].lstrip("\n")
        return chunks
