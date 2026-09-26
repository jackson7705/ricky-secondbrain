"""iMessage adapter using the BlueBubbles Server REST API.

BlueBubbles is a local macOS app that exposes Apple's Messages database
over HTTP. This adapter polls BlueBubbles for new incoming messages and
POSTs outgoing replies through its REST endpoints.

Why polling and not Socket.IO:
- One extra dependency avoided (no python-socketio).
- Apple's Messages database is a local single-writer source. Polling every
  few seconds against localhost is cheap, and resuming from a saved
  timestamp on restart is trivially reliable.

Auth model: a shared password configured inside the BlueBubbles app. We
pass it as the `password` query param on every request.

Security: incoming messages are gated by an allowlist of phone numbers /
Apple IDs so stray texts can't trigger a Claude run.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

import aiohttp

from models import Attachment, Channel, IncomingMessage, OutgoingMessage, Platform, Thread, User

# Same dated inbox folder the Slack adapter uses, so the agent's Read/Bash
# tools find both surfaces' uploads in one place: <SecondBrain>/inbox/<date>/
INBOX_DIR = Path(__file__).resolve().parent.parent.parent.parent / "inbox"

# What we bother downloading from an iMessage. Images (screenshots of a punch
# list), PDFs and office docs (receipts, invoices, contracts). Anything else —
# stickers, vCards, audio, executables — is noted in the prompt but not fetched.
_ATTACHMENT_MIME_PREFIXES = ("image/", "application/pdf", "text/")
_ATTACHMENT_MIME_EXACT = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/msword",
    "application/vnd.ms-excel",
    "text/csv",
}
_MAX_ATTACHMENT_BYTES = 40 * 1024 * 1024


def _wanted_attachment(att: dict[str, Any]) -> bool:
    """True if this BlueBubbles attachment record is worth downloading."""
    if att.get("isSticker") or att.get("hideAttachment"):
        return False
    if not att.get("guid"):
        return False
    mime = (att.get("mimeType") or "").lower()
    if not mime:
        # Some carriers strip the type; fall back to the file extension.
        name = (att.get("transferName") or "").lower()
        return name.endswith((".png", ".jpg", ".jpeg", ".heic", ".gif", ".webp", ".pdf",
                              ".docx", ".xlsx", ".pptx", ".csv", ".txt"))
    if mime.startswith(_ATTACHMENT_MIME_PREFIXES) or mime in _ATTACHMENT_MIME_EXACT:
        size = att.get("totalBytes") or 0
        return not size or size <= _MAX_ATTACHMENT_BYTES
    return False


def _message_has_content(msg: dict[str, Any]) -> bool:
    """A message is worth handling if it has text OR a downloadable attachment.

    Before 2026-09-26 the poller dropped any message whose text was blank, so a
    receipt photo or a screenshot sent without a caption vanished, and one sent
    WITH a caption ("Fix these", "File") arrived as bare text. Two in a row.
    """
    if (msg.get("text") or "").strip():
        return True
    return any(_wanted_attachment(a) for a in (msg.get("attachments") or []))


# iPhone photos arrive as HEIC, which the agent's Read tool can't open. macOS
# ships `sips`, so convert in place to JPEG. Videos are left as-is: the agent
# can't view them either way, but ffmpeg (if installed) can pull frames on demand.
_HEIC_SUFFIXES = (".heic", ".heif")


async def _transcode_if_needed(path: Path, mimetype: str) -> tuple[Path, str]:
    is_heic = (mimetype or "").lower() in ("image/heic", "image/heif") or \
        path.suffix.lower() in _HEIC_SUFFIXES
    if not is_heic:
        return path, mimetype
    out = path.with_suffix(".jpg")
    try:
        proc = await asyncio.create_subprocess_exec(
            "sips", "-s", "format", "jpeg", "-s", "formatOptions", "90",
            str(path), "--out", str(out),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode == 0 and out.is_file() and out.stat().st_size > 0:
            path.unlink(missing_ok=True)
            print(f"[{datetime.now()}] Transcoded HEIC -> {out.name}")
            return out, "image/jpeg"
        print(f"[{datetime.now()}] sips failed on {path.name}: {err.decode(errors='ignore')[:120]}")
    except Exception as e:  # noqa: BLE001 — keep the original if conversion fails
        print(f"[{datetime.now()}] HEIC transcode error ({path.name}): {e}")
    return path, mimetype


def _normalize_address(addr: str) -> str:
    """Strip spaces, dashes, parens. Leaves + prefix and digits.
    Emails are lower-cased; phone numbers keep their E.164 form."""
    if "@" in addr:
        return addr.strip().lower()
    return re.sub(r"[^\d+]", "", addr)


class IMessageAdapter:
    """BlueBubbles-backed iMessage adapter.

    One iMessage conversation (chat guid) == one `Thread` for the engine.
    That means the session store keeps a separate Claude conversation per
    iMessage thread, mirroring the Slack-per-channel behavior.
    """

    # BlueBubbles caps message body size; leaving headroom for smileys etc.
    MAX_MESSAGE_CHARS = 9000

    # Slack-style emoji shortcodes leak in from engine placeholders (router.py
    # uses `:hourglass_flowing_sand: Thinking...`). iMessage renders these
    # literally, which looks broken — translate a small set to unicode and strip
    # anything else we don't recognize.
    _SLACK_EMOJI_MAP = {
        "hourglass_flowing_sand": "\u23f3",  # ⏳
        "hourglass": "\u231b",  # ⌛
        "sparkles": "\u2728",  # ✨
        "white_check_mark": "\u2705",  # ✅
        "check": "\u2705",
        "x": "\u274c",  # ❌
        "warning": "\u26a0\ufe0f",  # ⚠️
        "rocket": "\U0001f680",  # 🚀
        "robot_face": "\U0001f916",  # 🤖
        "brain": "\U0001f9e0",  # 🧠
        "thinking_face": "\U0001f914",  # 🤔
    }

    def __init__(
        self,
        base_url: str,
        password: str,
        allowed_addresses: list[str],
        state_path: Path,
        poll_interval: float = 3.0,
    ) -> None:
        if not base_url:
            raise ValueError("BlueBubbles base_url is required")
        if not password:
            raise ValueError("BlueBubbles password is required")

        self.base_url = base_url.rstrip("/")
        self.password = password
        # Normalize allowlist for fast membership checks. Empty list = deny all.
        self.allowed_addresses = {_normalize_address(a) for a in allowed_addresses}
        self.state_path = state_path
        self.poll_interval = poll_interval

        self._queue: asyncio.Queue[IncomingMessage] = asyncio.Queue()
        self._session: aiohttp.ClientSession | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._last_seen_ts: int = 0  # dateCreated in ms since epoch
        self._server_address: str | None = None  # our own handle; filters echoes

    @property
    def platform(self) -> Platform:
        return Platform.IMESSAGE

    # ── Lifecycle ───────────────────────────────────────────────────────

    async def connect(self) -> None:
        self._session = aiohttp.ClientSession()
        self._last_seen_ts = self._load_last_seen()

        # Health check so we fail loudly at startup rather than on first poll
        try:
            async with self._session.get(
                f"{self.base_url}/api/v1/ping",
                params={"password": self.password},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    raise RuntimeError(
                        f"BlueBubbles ping failed: HTTP {resp.status}"
                    )
        except aiohttp.ClientError as e:
            raise RuntimeError(f"BlueBubbles unreachable at {self.base_url}: {e}") from e

        # First-run backfill guard: if we have no saved checkpoint, start from "now"
        # so we don't reply to a year of old texts on first boot.
        if self._last_seen_ts == 0:
            self._last_seen_ts = int(time.time() * 1000)
            self._save_last_seen(self._last_seen_ts)

        self._poll_task = asyncio.create_task(self._poll_loop())
        print(
            f"[{datetime.now()}] iMessage adapter connected to {self.base_url} "
            f"(allowlist: {len(self.allowed_addresses)} addresses, poll={self.poll_interval}s)"
        )

    async def disconnect(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        if self._session:
            await self._session.close()
        print(f"[{datetime.now()}] iMessage adapter disconnected")

    async def listen(self) -> Any:
        while True:
            message = await self._queue.get()
            yield message

    # ── Outbound ────────────────────────────────────────────────────────

    async def send(self, message: OutgoingMessage) -> str | None:
        """Send a text message to a BlueBubbles chat guid.

        BlueBubbles has no native "edit message" — updates are sent as new messages.
        Returns the guid of the last chunk sent so the engine can reference it.
        """
        assert self._session is not None, "send() before connect()"

        chat_guid = message.channel.platform_id
        if not chat_guid:
            print(f"[{datetime.now()}] iMessage send skipped: no chat_guid on message")
            return None

        # Skip the router's "Thinking..." placeholder — iMessage already
        # shows "Delivered" on the user's message, and a spinner bubble just
        # adds noise. We return a sentinel so the router still calls update()
        # with the real answer, which our update() then sends as a fresh msg.
        if "Thinking..." in message.text and len(message.text) < 60:
            return "imessage-placeholder-suppressed"

        # Strip Slack markdown artifacts that leak in from the engine.
        text = self._slack_to_imessage_text(message.text)

        last_guid: str | None = None
        for chunk in self._split_message(text):
            body = {
                "chatGuid": chat_guid,
                "message": chunk,
                "method": "apple-script",  # more reliable than 'private-api' on stock setups
                "tempGuid": f"ricky-{int(time.time() * 1000)}",
            }
            try:
                async with self._session.post(
                    f"{self.base_url}/api/v1/message/text",
                    params={"password": self.password},
                    json=body,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    data = await resp.json()
                    if resp.status >= 400:
                        print(
                            f"[{datetime.now()}] iMessage send error "
                            f"{resp.status}: {data.get('error', data)}"
                        )
                        continue
                    last_guid = (data.get("data") or {}).get("guid") or last_guid
            except Exception as e:
                print(f"[{datetime.now()}] iMessage send exception: {e}")
        return last_guid

    async def update(self, message: OutgoingMessage) -> None:
        """iMessage doesn't support edits — send the update as a fresh message.

        The router posts a "Thinking..." placeholder via `send()` and then
        calls `update()` with the final answer. On Slack this edits the
        placeholder in place; on iMessage we can't edit, so the final
        answer arrives as a follow-up message. The user sees "Thinking..."
        stay in the thread, which is a reasonable UX.

        We intentionally only send the *final* update — intermediate
        streaming updates would spam the thread. The router only ever
        calls `update()` once per turn with the completed response.
        """
        # Clear the is_update flag so `send()` treats it as a new message.
        final = OutgoingMessage(
            text=message.text,
            channel=message.channel,
            thread=message.thread,
            attachments=message.attachments,
        )
        await self.send(final)

    async def send_typing(self, channel: Channel) -> None:
        """BlueBubbles' typing indicator endpoint is flaky without private API —
        no-op for now. iMessage shows no typing indicator in that case."""
        return None

    # ── Polling loop ────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        assert self._session is not None
        while True:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # Transient network errors shouldn't kill the adapter.
                print(f"[{datetime.now()}] iMessage poll error: {e}")
            await asyncio.sleep(self.poll_interval)

    async def _poll_once(self) -> None:
        assert self._session is not None

        # `after` is inclusive; add 1ms to avoid re-fetching the last seen msg.
        after_ms = self._last_seen_ts + 1 if self._last_seen_ts else 0
        params: dict[str, Any] = {
            "password": self.password,
            "limit": 25,
            "offset": 0,
            "sort": "ASC",
            "with": ["handle", "chats", "chat.participants"],
        }
        if after_ms:
            params["after"] = after_ms

        async with self._session.post(
            f"{self.base_url}/api/v1/message/query",
            params={"password": self.password},
            json={
                "limit": params["limit"],
                "offset": 0,
                "sort": "ASC",
                "after": after_ms,
                "with": ["handle", "chats", "chat.participants", "attachment"],
            },
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                print(f"[{datetime.now()}] iMessage query HTTP {resp.status}")
                return
            data = await resp.json()

        messages = (data.get("data") or [])
        if not messages:
            return

        newest_ts = self._last_seen_ts
        for msg in messages:
            ts = msg.get("dateCreated") or 0
            if ts > newest_ts:
                newest_ts = ts

            # Skip anything we sent ourselves — BlueBubbles surfaces both directions.
            if msg.get("isFromMe"):
                continue

            # Skip silent/hidden types (reactions, edits, tapbacks) for v1.
            if msg.get("itemType") and msg["itemType"] != 0:
                continue

            if not _message_has_content(msg):
                continue
            text = msg.get("text") or ""

            sender_handle = (msg.get("handle") or {}).get("address") or ""
            normalized_sender = _normalize_address(sender_handle)
            if not self._is_allowed(normalized_sender):
                # Silent drop — log but don't respond to strangers.
                print(
                    f"[{datetime.now()}] iMessage ignored (not in allowlist): "
                    f"{sender_handle}"
                )
                continue

            chats = msg.get("chats") or []
            if not chats:
                continue
            chat = chats[0]
            chat_guid = chat.get("guid") or ""
            # Group chat has >1 participant besides us.
            participants = chat.get("participants") or [{"address": sender_handle}]
            is_dm = len([p for p in participants if p.get("address")]) <= 1

            attachments: list[Attachment] = []
            skipped: list[str] = []
            for att in msg.get("attachments") or []:
                if not _wanted_attachment(att):
                    skipped.append(att.get("transferName") or att.get("mimeType") or "attachment")
                    continue
                downloaded = await self._download_attachment(att)
                if downloaded:
                    attachments.append(downloaded)
                else:
                    skipped.append(att.get("transferName") or "attachment")
            if not text.strip():
                # Caption-less photo/PDF: give the agent something to act on.
                text = f"[The user sent {len(attachments)} attachment(s) with no text.]"
            if skipped:
                text += (
                    f"\n\n[{len(skipped)} attachment(s) could not be fetched: "
                    + ", ".join(skipped[:5]) + "]"
                )

            incoming = IncomingMessage(
                text=text,
                user=User(Platform.IMESSAGE, normalized_sender, display_name=sender_handle),
                channel=Channel(
                    Platform.IMESSAGE,
                    chat_guid,
                    name=chat.get("displayName") or sender_handle,
                    is_dm=is_dm,
                ),
                platform=Platform.IMESSAGE,
                thread=Thread(thread_id=chat_guid),
                platform_message_id=msg.get("guid") or "",
                attachments=attachments,
                timestamp=_ms_to_dt(ts),
                raw_event=msg,
            )
            await self._queue.put(incoming)

        if newest_ts > self._last_seen_ts:
            self._last_seen_ts = newest_ts
            self._save_last_seen(newest_ts)

    # ── Helpers ─────────────────────────────────────────────────────────

    async def _download_attachment(self, att: dict[str, Any]) -> Attachment | None:
        """Fetch one attachment from BlueBubbles and save it under inbox/<date>/.

        BlueBubbles serves the original bytes at
        GET /api/v1/attachment/:guid/download?password=... — HEIC and friends
        come back as-is (no server-side conversion requested), which the
        agent's Read tool handles.
        """
        assert self._session is not None
        guid = att.get("guid") or ""
        filename = att.get("transferName") or f"{guid}.bin"
        mimetype = att.get("mimeType") or "application/octet-stream"

        inbox = INBOX_DIR / date.today().isoformat()
        safe_name = re.sub(r"[^\w.\-]", "_", filename)
        local_path = inbox / f"{datetime.now().strftime('%H%M%S')}_{safe_name}"
        try:
            inbox.mkdir(parents=True, exist_ok=True)
            async with self._session.get(
                f"{self.base_url}/api/v1/attachment/{guid}/download",
                params={"password": self.password},
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status != 200:
                    print(
                        f"[{datetime.now()}] iMessage attachment download failed "
                        f"{resp.status}: {filename}"
                    )
                    return None
                data = await resp.read()
            local_path.write_bytes(data)
            local_path, mimetype = await _transcode_if_needed(local_path, mimetype)
            print(f"[{datetime.now()}] Downloaded iMessage attachment {filename} -> {local_path}")
            return Attachment(filename=local_path.name, mimetype=mimetype,
                              url=str(local_path), size_bytes=local_path.stat().st_size)
        except Exception as e:
            print(f"[{datetime.now()}] iMessage attachment error ({filename}): {e}")
            return None

    def _is_allowed(self, normalized_sender: str) -> bool:
        if not self.allowed_addresses:
            return False  # fail closed
        return normalized_sender in self.allowed_addresses

    def _load_last_seen(self) -> int:
        try:
            raw = json.loads(self.state_path.read_text())
            value = raw.get("last_seen_ts")
            return int(value) if value else 0
        except FileNotFoundError:
            return 0
        except Exception as e:
            print(f"[{datetime.now()}] iMessage state load failed (resetting): {e}")
            return 0

    def _save_last_seen(self, ts: int) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps({"last_seen_ts": ts}))
        except Exception as e:
            print(f"[{datetime.now()}] iMessage state save failed: {e}")

    def _slack_to_imessage_text(self, text: str) -> str:
        """Translate Slack-flavored markdown/emoji into plain text for iMessage.

        iMessage has no rich formatting, so we:
        - Replace known `:shortcode:` emoji with unicode.
        - Drop any unknown `:shortcode:` (safer than leaving `:foo:` visible).
        - Convert Slack's `<url|label>` links to `label (url)`.
        - Strip `*bold*` / `_italic_` wrappers — iMessage renders stars as-is
          and italic underscores look noisy.
        - Convert markdown `[label](url)` to `label (url)` for the same reason.
        """
        def _replace_emoji(match: re.Match[str]) -> str:
            name = match.group(1)
            return self._SLACK_EMOJI_MAP.get(name, "")

        # Emoji shortcodes — known → unicode, unknown → dropped
        text = re.sub(r":([a-z0-9_+-]+):", _replace_emoji, text)

        # Slack-style links: <https://example.com|label> → label (url)
        text = re.sub(r"<(https?://[^|>\s]+)\|([^>]+)>", r"\2 (\1)", text)
        # Bare Slack links: <https://example.com> → https://example.com
        text = re.sub(r"<(https?://[^>\s]+)>", r"\1", text)

        # Markdown links: [label](url) → label (url)
        text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", text)

        # Remove Slack bold/italic markers. We leave ** alone since the engine
        # may emit standard markdown bold that shouldn't become visible stars.
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)  # **bold** → bold
        text = re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"\1", text)  # _italic_ → italic

        # Collapse triple+ blank lines that often show up after stripping.
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text

    def _split_message(self, text: str) -> list[str]:
        """iMessage tolerates long messages better than Slack, but very long
        ones can fail to deliver. Split on paragraph boundaries."""
        if len(text) <= self.MAX_MESSAGE_CHARS:
            return [text]
        chunks: list[str] = []
        remaining = text
        while remaining:
            if len(remaining) <= self.MAX_MESSAGE_CHARS:
                chunks.append(remaining)
                break
            split_at = self.MAX_MESSAGE_CHARS
            paragraph = remaining[:split_at].rfind("\n\n")
            if paragraph > self.MAX_MESSAGE_CHARS // 2:
                split_at = paragraph + 2
            else:
                newline = remaining[:split_at].rfind("\n")
                if newline > self.MAX_MESSAGE_CHARS // 2:
                    split_at = newline + 1
                else:
                    space = remaining[:split_at].rfind(" ")
                    if space > self.MAX_MESSAGE_CHARS // 2:
                        split_at = space + 1
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:]
        return chunks


def _ms_to_dt(ms: int) -> datetime:
    try:
        return datetime.fromtimestamp(ms / 1000)
    except Exception:
        return datetime.now()
