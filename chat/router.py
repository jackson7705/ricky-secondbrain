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
    """

    def __init__(self, engine: ConversationEngine) -> None:
        self.engine = engine
        self.adapters: dict[Platform, Any] = {}

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
        """Handle a single incoming message: post placeholder, run engine, update."""
        print(
            f"[{datetime.now()}] Message from {incoming.user.platform_id} "
            f"in {incoming.channel.platform_id}: {incoming.text[:80]}..."
        )

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
        try:
            async for outgoing in self.engine.handle_message(incoming):
                final_text = outgoing.text
                if outgoing.attachments:
                    file_attachments = outgoing.attachments
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
