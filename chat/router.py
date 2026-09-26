"""Chat router connecting platform adapters to the conversation engine."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from engine import ConversationEngine
from models import OutgoingMessage, Platform


class ChatRouter:
    """Routes messages between platform adapters and the conversation engine.

    Handles concurrent message processing — each incoming message spawns
    its own task so multiple conversations can run simultaneously.

    Within ONE conversation (same platform:channel:thread) turns run strictly
    in arrival order. Before this, two texts sent a minute apart ("Not in
    ClickUp", "Looking for non stop") became two parallel agent runs resuming
    the same SDK session: each answered the first message in full, neither saw
    the other, and side effects doubled (duplicate ClickUp tasks, a receipt
    filed twice — observed 2026-09-24/25).
    """

    def __init__(
        self,
        engine: ConversationEngine,
        progress_interval_seconds: float = 300,
    ) -> None:
        if progress_interval_seconds <= 0:
            raise ValueError("progress interval must be positive")
        self.engine = engine
        self.progress_interval_seconds = progress_interval_seconds
        self.adapters: dict[Platform, Any] = {}
        self._conversation_locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def conversation_key(incoming: Any) -> str:
        """Same key the engine uses for its session row."""
        thread_id = incoming.thread.thread_id if incoming.thread else incoming.channel.platform_id
        return f"{incoming.platform.value}:{incoming.channel.platform_id}:{thread_id}"

    def _lock_for(self, incoming: Any) -> asyncio.Lock:
        key = self.conversation_key(incoming)
        lock = self._conversation_locks.get(key)
        if lock is None:
            lock = self._conversation_locks[key] = asyncio.Lock()
        return lock

    def register(self, adapter: Any) -> None:
        """Register a platform adapter."""
        self.adapters[adapter.platform] = adapter
        print(f"[{datetime.now()}] Registered adapter: {adapter.platform.value}")

    async def run(self) -> None:
        """Connect all adapters and start listening for messages."""
        if not self.adapters:
            print(f"[{datetime.now()}] No adapters registered, nothing to do")
            return

        # Connect all adapters concurrently
        await asyncio.gather(*(a.connect() for a in self.adapters.values()))
        print(f"[{datetime.now()}] All adapters connected")

        # Create a listen task per adapter
        tasks = [asyncio.create_task(self._listen(adapter)) for adapter in self.adapters.values()]

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            print(f"[{datetime.now()}] Router shutting down...")

    async def _listen(self, adapter: Any) -> None:
        """Listen for incoming messages from a single adapter."""
        try:
            async for incoming in adapter.listen():
                asyncio.create_task(self._handle(adapter, incoming))
        except asyncio.CancelledError:
            return
        except Exception as e:
            print(f"[{datetime.now()}] Listener error ({adapter.platform.value}): {e}")

    async def _handle(self, adapter: Any, incoming: Any) -> None:
        """Handle a single incoming message: post placeholder, run engine, update.

        Turns in the same conversation are serialized (see class docstring);
        different conversations still run concurrently.
        """
        print(
            f"[{datetime.now()}] Message from {incoming.user.platform_id} "
            f"in {incoming.channel.platform_id}: {incoming.text[:80]}..."
        )

        lock = self._lock_for(incoming)
        if lock.locked():
            print(
                f"[{datetime.now()}] Conversation {self.conversation_key(incoming)} busy — "
                "queuing this message behind the in-flight turn"
            )
        async with lock:
            await self._handle_turn(adapter, incoming)

    async def _handle_turn(self, adapter: Any, incoming: Any) -> None:
        # Post "Thinking..." placeholder
        placeholder_id: str | None = None
        try:
            placeholder_id = await adapter.send(
                OutgoingMessage(
                    text=":hourglass_flowing_sand: Thinking...",
                    channel=incoming.channel,
                    thread=incoming.thread,
                )
            )
        except Exception as e:
            print(f"[{datetime.now()}] Failed to send placeholder: {e}")

        # Collect the full response from the engine
        final_text = ""
        file_attachments: list[Any] = []

        async def collect_response() -> None:
            nonlocal final_text, file_attachments
            async for outgoing in self.engine.handle_message(incoming):
                final_text = outgoing.text
                if outgoing.attachments:
                    file_attachments = outgoing.attachments

        collector = asyncio.create_task(collect_response())
        started_at = datetime.now()
        try:
            while not collector.done():
                done, _ = await asyncio.wait(
                    {collector},
                    timeout=self.progress_interval_seconds,
                )
                if collector in done or not placeholder_id:
                    continue
                elapsed_minutes = max(
                    1,
                    int((datetime.now() - started_at).total_seconds() // 60),
                )
                try:
                    await adapter.update(
                        OutgoingMessage(
                            text=(
                                ":hourglass_flowing_sand: Still working — "
                                f"{elapsed_minutes} minute(s) elapsed. Large tasks can "
                                "take a while; I’ll post the finished result here."
                            ),
                            channel=incoming.channel,
                            thread=incoming.thread,
                            is_update=True,
                            update_message_id=placeholder_id,
                        )
                    )
                except Exception as e:
                    print(f"[{datetime.now()}] Failed to send progress update: {e}")
            await collector
        except asyncio.CancelledError:
            collector.cancel()
            await asyncio.gather(collector, return_exceptions=True)
            raise
        except Exception as e:
            print(f"[{datetime.now()}] Engine error: {e}")
            final_text = f"Sorry, something went wrong: {e}"

        # Update the placeholder with the final response
        if not final_text.strip():
            final_text = "I processed your request but had no text response."

        try:
            if placeholder_id:
                await adapter.update(
                    OutgoingMessage(
                        text=final_text,
                        channel=incoming.channel,
                        thread=incoming.thread,
                        is_update=True,
                        update_message_id=placeholder_id,
                    )
                )
            else:
                # Placeholder failed — send a new message instead
                await adapter.send(
                    OutgoingMessage(
                        text=final_text,
                        channel=incoming.channel,
                        thread=incoming.thread,
                    )
                )
        except Exception as e:
            print(f"[{datetime.now()}] Failed to send response: {e}")

        # Upload any image attachments (thumbnails, generated images, etc.)
        if file_attachments and hasattr(adapter, "send_files"):
            channel_id = incoming.channel.platform_id
            thread_ts = incoming.thread.thread_id if incoming.thread else None
            file_paths = [att.url for att in file_attachments if att.url]
            if file_paths:
                try:
                    await adapter.send_files(file_paths, channel_id, thread_ts)
                except Exception as e:
                    print(f"[{datetime.now()}] Failed to upload files: {e}")

    async def shutdown(self) -> None:
        """Disconnect all adapters gracefully."""
        for adapter in self.adapters.values():
            try:
                await adapter.disconnect()
            except Exception as e:
                print(f"[{datetime.now()}] Error disconnecting {adapter.platform.value}: {e}")
