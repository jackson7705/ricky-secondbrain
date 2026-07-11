"""Discord adapter using discord.py.

Works on any OS. Create an application + bot at https://discord.com/developers,
enable the **Message Content Intent**, invite the bot to a server (or just DM
it). Only user IDs in the allowlist can command Ricky.

Requires the optional `discord.py` dependency:
    uv pip install "discord.py>=2.3"
(or add the `discord` extra — see pyproject.)
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from models import Channel, IncomingMessage, OutgoingMessage, Platform, Thread, User

DISCORD_MAX = 2000  # Discord hard limit per message


class DiscordAdapter:
    """Discord bot adapter. DMs + @mentions from allowlisted users."""

    def __init__(
        self,
        bot_token: str,
        allowed_user_ids: list[str],
        session_store: Any | None = None,
    ) -> None:
        import discord

        self.token = bot_token
        self.allowed = {str(u).strip() for u in allowed_user_ids if str(u).strip()}
        self.session_store = session_store
        self._queue: asyncio.Queue[IncomingMessage] = asyncio.Queue()
        self._channels: dict[str, Any] = {}  # channel_id -> discord channel (for replies)
        self._task: asyncio.Task | None = None

        intents = discord.Intents.default()
        intents.message_content = True  # privileged — enable in the dev portal
        intents.dm_messages = True
        self.client = discord.Client(intents=intents)
        self.client.event(self._on_ready)
        self.client.event(self._on_message)

    @property
    def platform(self) -> Platform:
        return Platform.DISCORD

    async def connect(self) -> None:
        # discord.py owns its lifecycle; run it as a background task.
        self._task = asyncio.create_task(self.client.start(self.token))
        print(f"[{datetime.now()}] Discord adapter starting…")

    async def disconnect(self) -> None:
        await self.client.close()
        if self._task:
            self._task.cancel()
        print(f"[{datetime.now()}] Discord adapter disconnected")

    async def listen(self) -> Any:
        while True:
            yield await self._queue.get()

    async def send(self, message: OutgoingMessage) -> str | None:
        chan = self._channels.get(message.channel.platform_id)
        if chan is None:
            try:
                chan = self.client.get_channel(int(message.channel.platform_id)) or \
                    await self.client.fetch_channel(int(message.channel.platform_id))
            except Exception as e:  # noqa: BLE001
                print(f"[{datetime.now()}] Discord: cannot resolve channel {message.channel.platform_id}: {e}")
                return None
        first_id: str | None = None
        for chunk in self._split(message.text):
            try:
                sent = await chan.send(chunk)
                if first_id is None:
                    first_id = str(sent.id)
            except Exception as e:  # noqa: BLE001
                print(f"[{datetime.now()}] Discord send error: {e}")
        return first_id

    async def update(self, message: OutgoingMessage) -> None:
        await self.send(message)

    async def send_typing(self, channel: Channel) -> None:
        chan = self._channels.get(channel.platform_id)
        if chan is not None:
            try:
                await chan.typing()
            except Exception:  # noqa: BLE001
                pass

    # ── events ───────────────────────────────────────────────────────
    async def _on_ready(self) -> None:
        print(f"[{datetime.now()}] Discord adapter connected (as {self.client.user})")

    async def _on_message(self, message: Any) -> None:
        import discord

        if message.author == self.client.user or message.author.bot:
            return
        if not self._is_allowed(str(message.author.id)):
            return
        is_dm = isinstance(message.channel, discord.DMChannel)
        # In servers, only respond when mentioned.
        if not is_dm and not self.client.user.mentioned_in(message):
            return

        self._channels[str(message.channel.id)] = message.channel
        text = message.content
        if self.client.user:
            text = text.replace(f"<@{self.client.user.id}>", "").replace(
                f"<@!{self.client.user.id}>", "").strip()

        user = User(Platform.DISCORD, str(message.author.id),
                    display_name=getattr(message.author, "display_name", None))
        channel = Channel(Platform.DISCORD, str(message.channel.id), is_dm=is_dm)
        thread = Thread(thread_id=str(message.channel.id))
        await self._queue.put(IncomingMessage(
            text=text, user=user, channel=channel, platform=Platform.DISCORD,
            thread=thread, platform_message_id=str(message.id),
            raw_event={"id": message.id, "author": str(message.author.id)},
        ))

    def _is_allowed(self, user_id: str) -> bool:
        if not self.allowed:
            return False  # fail closed
        return str(user_id) in self.allowed

    @staticmethod
    def _split(text: str, max_length: int = DISCORD_MAX) -> list[str]:
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
