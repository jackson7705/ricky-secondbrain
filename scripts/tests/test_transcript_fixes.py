"""Regression tests for the failures seen in the 2026-09-16 → 09-26 chat transcript:

- parallel agent runs on one conversation (duplicate replies / double filing)
- iMessage attachments silently dropped
- scheduled jobs filing ClickUp tasks without approval
- context lost across session rotation
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

_CHAT_DIR = Path(__file__).resolve().parents[2] / "chat"
sys.path.insert(0, str(_CHAT_DIR))

from adapters.imessage import _message_has_content, _wanted_attachment  # noqa: E402
from engine import ConversationEngine, TaskRuntimePolicy, _runtime_policy_for  # noqa: E402
from models import Channel, IncomingMessage, OutgoingMessage, Platform, Thread, User  # noqa: E402
from router import ChatRouter  # noqa: E402
from session import Session, SQLiteSessionStore  # noqa: E402

import pending_tasks  # noqa: E402


def _incoming(text: str, channel: str = "C1", thread: str | None = None) -> IncomingMessage:
    return IncomingMessage(
        text=text,
        user=User(Platform.IMESSAGE, "+15555550100"),
        channel=Channel(Platform.IMESSAGE, channel),
        platform=Platform.IMESSAGE,
        thread=Thread(thread_id=thread) if thread else None,
    )


# ── 1. Router serializes turns within one conversation ────────────────────


class _TimelineEngine:
    """Records when each turn starts/ends so overlap can be asserted."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []
        self.active = 0
        self.max_active = 0

    async def handle_message(self, incoming: IncomingMessage) -> Any:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.events.append(("start", incoming.text))
        await asyncio.sleep(0.03)
        self.events.append(("end", incoming.text))
        self.active -= 1
        yield OutgoingMessage(text=f"done: {incoming.text}", channel=incoming.channel)


class _NullAdapter:
    def __init__(self) -> None:
        self.sent: list[OutgoingMessage] = []

    async def send(self, outgoing: OutgoingMessage) -> str:
        self.sent.append(outgoing)
        return "imessage-placeholder-suppressed"

    async def update(self, outgoing: OutgoingMessage) -> None:
        self.sent.append(outgoing)


def test_same_conversation_turns_run_in_order_not_in_parallel() -> None:
    engine = _TimelineEngine()
    router = ChatRouter(engine, progress_interval_seconds=10)  # type: ignore[arg-type]
    adapter = _NullAdapter()

    async def run() -> None:
        await asyncio.gather(
            router._handle(adapter, _incoming("I'm looking for flights")),
            router._handle(adapter, _incoming("Not in ClickUp")),
            router._handle(adapter, _incoming("Looking for non stop")),
        )

    asyncio.run(run())
    assert engine.max_active == 1, "turns in one conversation overlapped"
    starts = [t for kind, t in engine.events if kind == "start"]
    assert starts == ["I'm looking for flights", "Not in ClickUp", "Looking for non stop"]
    finals = [m.text for m in adapter.sent if m.text.startswith("done:")]
    assert len(finals) == 3


def test_different_conversations_still_run_concurrently() -> None:
    engine = _TimelineEngine()
    router = ChatRouter(engine, progress_interval_seconds=10)  # type: ignore[arg-type]
    adapter = _NullAdapter()

    async def run() -> None:
        await asyncio.gather(
            router._handle(adapter, _incoming("a", channel="C1")),
            router._handle(adapter, _incoming("b", channel="C2")),
        )

    asyncio.run(run())
    assert engine.max_active == 2


def test_conversation_key_matches_engine_session_key() -> None:
    msg = _incoming("hi", channel="chat-guid", thread="chat-guid")
    assert ChatRouter.conversation_key(msg) == "imessage:chat-guid:chat-guid"
    msg_no_thread = _incoming("hi", channel="C9")
    assert ChatRouter.conversation_key(msg_no_thread) == "imessage:C9:C9"


# ── 2. iMessage attachments are not dropped ───────────────────────────────


def test_caption_less_attachment_message_is_kept() -> None:
    msg = {"text": "", "attachments": [{"guid": "g1", "mimeType": "image/png",
                                        "transferName": "IMG_1.png"}]}
    assert _message_has_content(msg)


def test_truly_empty_message_is_still_skipped() -> None:
    assert not _message_has_content({"text": "   ", "attachments": []})
    assert not _message_has_content({"text": "", "attachments": [
        {"guid": "s", "mimeType": "image/png", "isSticker": True}]})


@pytest.mark.parametrize(
    "att, wanted",
    [
        ({"guid": "a", "mimeType": "application/pdf", "transferName": "receipt.pdf"}, True),
        ({"guid": "a", "mimeType": "image/heic", "transferName": "IMG.HEIC"}, True),
        ({"guid": "a", "mimeType": "", "transferName": "invoice.PDF"}, True),
        ({"guid": "a", "mimeType": "audio/amr", "transferName": "voice.amr"}, False),
        ({"guid": "a", "mimeType": "image/png", "totalBytes": 200 * 1024 * 1024}, False),
        ({"mimeType": "image/png"}, False),  # no guid → nothing to download
    ],
)
def test_wanted_attachment_filter(att: dict, wanted: bool) -> None:
    assert _wanted_attachment(att) is wanted


def test_attachment_context_names_platform_and_tells_agent_to_open_files() -> None:
    from models import Attachment
    ctx = ConversationEngine._build_attachment_context(
        [Attachment(filename="IMG_1.png", mimetype="image/png", url="/inbox/IMG_1.png")],
        "imessage",
    )
    assert "via imessage" in ctx
    assert "/inbox/IMG_1.png" in ctx
    assert "Never reply that nothing was attached" in ctx


# ── 3. Approval gate for ClickUp tasks ────────────────────────────────────


class _FakeTask:
    def __init__(self, n: int) -> None:
        self.id = f"t{n}"
        self.url = f"https://app.clickup.com/t/t{n}"


def test_pending_tasks_propose_approve_reject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLICKUP_INBOX_LIST_ID", "L1")
    monkeypatch.setenv("CLICKUP_OWNER_UID", "42")
    import config
    monkeypatch.setattr(config, "CLICKUP_INBOX_LIST_ID", "L1")
    monkeypatch.setattr(config, "CLICKUP_OWNER_UID", "42")

    pt = pending_tasks.PendingTasks(tmp_path / "pending.json")
    added = pt.propose([
        {"title": "Reply to Jeff re pricing", "note": "Local Siren", "source": "email"},
        {"title": "Sign Map Labs NDA", "note": "", "due": "2026-09-30", "source": "email"},
        {"title": "Reply to Jeff re pricing", "note": "dupe", "source": "email"},
    ], origin="inbox")
    assert [a["id"] for a in added] == [1, 2]
    assert len(pt.pending()) == 2

    created: list[tuple] = []

    def fake_create(list_id, name, description="", due_on=None, assignees=None, priority=None):
        created.append((list_id, name, due_on, assignees))
        return _FakeTask(len(created))

    filed, errors = pt.approve(["2"], create_task=fake_create)
    assert not errors
    assert [f["title"] for f in filed] == ["Sign Map Labs NDA"]
    assert created[0][0] == "L1" and str(created[0][2]) == "2026-09-30" and created[0][3] == [42]
    assert filed[0]["clickup_url"].endswith("/t1")

    dropped = pt.reject(["#1"])
    assert [d["id"] for d in dropped] == [1]
    assert pt.pending() == []
    # rejected titles stay known so the next sweep doesn't re-propose them
    assert pt.is_known("reply to jeff re pricing")
    pt.save()
    again = pending_tasks.PendingTasks(tmp_path / "pending.json")
    assert again.state["next_id"] == 3


def test_pending_tasks_approve_all_and_expiry(tmp_path: Path) -> None:
    pt = pending_tasks.PendingTasks(tmp_path / "p.json")
    pt.propose([{"title": "Old thing"}], origin="fathom")
    pt.items[0]["proposed_at"] = (datetime.now() - timedelta(days=9)).isoformat(timespec="seconds")
    pt.propose([{"title": "New thing"}], origin="fathom")  # propose() expires stale rows
    assert [i["title"] for i in pt.pending()] == ["New thing"]
    assert pt.items[0]["status"] == "expired"

    filed, errors = pt.approve(["all"], create_task=lambda *a, **k: _FakeTask(1))
    assert [f["title"] for f in filed] == ["New thing"] and not errors


def test_proposal_message_format_is_numbered_and_says_not_filed(tmp_path: Path) -> None:
    pt = pending_tasks.PendingTasks(tmp_path / "p.json")
    added = pt.propose([{"title": "Send Taylor the report", "due": "2026-09-18"}], origin="inbox")
    text = pending_tasks.format_proposal(added, "your inbox")
    assert "NOT filed" in text
    assert "#1 Send Taylor the report (due 2026-09-18)" in text
    assert '"add all"' in text


def test_jobs_default_to_propose_mode() -> None:
    import config
    assert config.TASK_FILING_MODE in ("propose", "auto")
    # Source-level guard: neither sweep may call ClickUp before the gate.
    for name in ("loose_ends.py", "fathom_sweep.py"):
        src = (Path(__file__).resolve().parents[1] / name).read_text()
        assert 'TASK_FILING_MODE == "propose"' in src
        assert src.index("pending.propose(") < src.index("create_task(INBOX_LIST_ID")


# ── 4. Context survives session rotation ──────────────────────────────────


def test_sqlite_turn_history_round_trip_and_trim(tmp_path: Path) -> None:
    from session import TURN_HISTORY_KEEP
    store = SQLiteSessionStore(tmp_path / "chat.db")
    for i in range(TURN_HISTORY_KEEP + 3):
        store.append_turn("imessage:c:c", f"user {i}", f"reply {i}")
    turns = store.recent_turns("imessage:c:c", limit=4)
    assert [u for _, u, _ in turns] == [f"user {i}" for i in range(TURN_HISTORY_KEEP - 1,
                                                                    TURN_HISTORY_KEEP + 3)]
    assert store.recent_turns("other", limit=4) == []


class _RotatingStore:
    def __init__(self, session: Session, turns: list[tuple[str, str, str]]) -> None:
        self.session = session
        self.turns = turns
        self.appended: list[tuple[str, str, str]] = []

    def get(self, *_: Any) -> Session:
        return self.session

    def update(self, session: Session) -> None:
        pass

    def create(self, session: Session) -> None:
        pass

    def recent_turns(self, session_id: str, limit: int = 6) -> list[tuple[str, str, str]]:
        return self.turns[-limit:]

    def append_turn(self, session_id: str, user_text: str, reply_text: str) -> None:
        self.appended.append((session_id, user_text, reply_text))


def test_rotated_session_gets_recent_conversation_recap(monkeypatch: pytest.MonkeyPatch) -> None:
    import claude_agent_sdk
    from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

    now = datetime.now()
    session = Session(
        session_id="imessage:c1:c1", agent_session_id="old", platform="imessage",
        channel_id="c1", thread_id="c1", user_id="u", created_at=now, updated_at=now,
        message_count=15,  # at the rotation threshold
    )
    store = _RotatingStore(session, [
        ("2026-09-24T15:01:00", "Verbal is locafy sept",
         "Filed Vercel receipt #2872-2288, $79.55, to Locafy September."),
    ])
    prompts: list[str] = []

    async def fake_query(*, prompt: str, options: Any) -> Any:
        prompts.append(prompt)
        assert options.resume is None, "rotated session must start fresh"
        yield AssistantMessage(content=[TextBlock(text="ok")], model="m")
        yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
                            num_turns=1, session_id="new-sdk-id", total_cost_usd=0.01)

    monkeypatch.setattr(claude_agent_sdk, "query", fake_query)
    engine = ConversationEngine(store, Path("."))  # type: ignore[arg-type]
    incoming = _incoming("Vercel", channel="c1", thread="c1")

    async def collect() -> list[OutgoingMessage]:
        return [o async for o in engine.handle_message(incoming)]

    asyncio.run(collect())
    assert len(prompts) == 1
    assert "Verbal is locafy sept" in prompts[0]
    assert "fresh agent session" in prompts[0]
    assert prompts[0].rstrip().endswith("Vercel")
    # The turn log gets the user's own words, not the injected context.
    assert store.appended == [("imessage:c1:c1", "Vercel", "ok")]


def test_engine_tolerates_store_without_turn_history(monkeypatch: pytest.MonkeyPatch) -> None:
    import claude_agent_sdk
    from claude_agent_sdk import AssistantMessage, TextBlock

    class _BareStore:
        def get(self, *_: Any) -> None:
            return None

        def create(self, session: Session) -> None:
            pass

    async def fake_query(*, prompt: str, options: Any) -> Any:
        yield AssistantMessage(content=[TextBlock(text="fine")], model="m")

    monkeypatch.setattr(claude_agent_sdk, "query", fake_query)
    engine = ConversationEngine(_BareStore(), Path("."))  # type: ignore[arg-type]

    async def collect() -> list[OutgoingMessage]:
        return [o async for o in engine.handle_message(_incoming("hello"))]

    assert [o.text for o in asyncio.run(collect())] == ["fine"]


# ── 5. Code work gets the long watchdog ───────────────────────────────────


def test_repo_fix_requests_get_large_runtime_policy() -> None:
    normal = TaskRuntimePolicy("normal", 600, 1800)
    large = TaskRuntimePolicy("large", 3600, 14400)
    assert _runtime_policy_for(
        "Fix these on airsenseenvironmental.com you should have access to the repo", normal, large
    ) is large
    assert _runtime_policy_for("Verbal is locafy sept", normal, large) is normal
