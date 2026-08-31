"""Tests for large-task runtime policies and chat progress reporting."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

_CHAT_DIR = Path(__file__).resolve().parents[2] / "chat"
sys.path.insert(0, str(_CHAT_DIR))

from engine import (  # noqa: E402
    TaskRuntimePolicy,
    _maybe_prepend_deliverable_directive,
    _next_watchdog_timeout,
    _runtime_policy_for,
)
from models import Channel, IncomingMessage, OutgoingMessage, Platform, User  # noqa: E402
from router import ChatRouter  # noqa: E402

NORMAL_POLICY = TaskRuntimePolicy("normal", 600, 1800)
LARGE_POLICY = TaskRuntimePolicy("large", 3600, 14400)


class TestTaskRuntimePolicy:
    def test_normal_chat_keeps_normal_limits(self) -> None:
        selected = _runtime_policy_for(
            "What time is my next meeting?",
            NORMAL_POLICY,
            LARGE_POLICY,
        )
        assert selected is NORMAL_POLICY

    @pytest.mark.parametrize(
        "prompt",
        [
            "Build me a 25-slide deck for the annual meeting",
            "Create a PowerPoint presentation about our strategy",
            "Run a full audit of the website",
            "This is a large task: migrate the application",
            "Do deep research on our market",
        ],
    )
    def test_large_work_gets_large_limits(self, prompt: str) -> None:
        selected = _runtime_policy_for(prompt, NORMAL_POLICY, LARGE_POLICY)
        assert selected is LARGE_POLICY

    def test_policy_rejects_nonpositive_limits(self) -> None:
        with pytest.raises(ValueError, match="inactivity timeout"):
            TaskRuntimePolicy("invalid", 0, 100)

    def test_policy_rejects_ceiling_shorter_than_inactivity(self) -> None:
        with pytest.raises(ValueError, match="hard ceiling"):
            TaskRuntimePolicy("invalid", 100, 99)

    def test_next_wait_is_capped_by_remaining_hard_ceiling(self) -> None:
        assert _next_watchdog_timeout(NORMAL_POLICY, 0) == 600
        assert _next_watchdog_timeout(NORMAL_POLICY, 1500) == 300
        assert _next_watchdog_timeout(NORMAL_POLICY, 1800) == 0


class TestDeliverableRouting:
    def test_deck_uses_pptx_directive_without_generic_pdf_mandate(self) -> None:
        prompt = _maybe_prepend_deliverable_directive("Build me a slide deck")
        assert "SLIDE DECK DELIVERY" in prompt
        assert "PPTX uploaded to Google Drive" in prompt
        assert "Do NOT convert the deck" in prompt
        assert "must be delivered as a BRANDED Locafy PDF" not in prompt

    def test_report_retains_branded_pdf_directive(self) -> None:
        prompt = _maybe_prepend_deliverable_directive("Write a quarterly report")
        assert "must be delivered as a BRANDED Locafy PDF" in prompt
        assert "SLIDE DECK DELIVERY" not in prompt

    def test_plain_chat_gets_no_deliverable_directive(self) -> None:
        prompt = "When is my next meeting?"
        assert _maybe_prepend_deliverable_directive(prompt) == prompt


class _SlowEngine:
    async def handle_message(self, incoming: IncomingMessage) -> Any:
        await asyncio.sleep(0.04)
        yield OutgoingMessage(text="Finished the large job", channel=incoming.channel)


class _FakeAdapter:
    def __init__(self, fail_progress_update: bool = False) -> None:
        self.sent: list[OutgoingMessage] = []
        self.updated: list[OutgoingMessage] = []
        self.fail_progress_update = fail_progress_update

    async def send(self, outgoing: OutgoingMessage) -> str:
        self.sent.append(outgoing)
        return "placeholder-1"

    async def update(self, outgoing: OutgoingMessage) -> None:
        if self.fail_progress_update and "Still working" in outgoing.text:
            self.fail_progress_update = False
            raise RuntimeError("temporary adapter failure")
        self.updated.append(outgoing)


def test_router_reports_progress_without_cancelling_large_job() -> None:
    async def run() -> _FakeAdapter:
        adapter = _FakeAdapter()
        router = ChatRouter(_SlowEngine(), progress_interval_seconds=0.01)  # type: ignore[arg-type]
        incoming = IncomingMessage(
            text="Build a slide deck",
            user=User(Platform.SLACK, "U123"),
            channel=Channel(Platform.SLACK, "C123"),
            platform=Platform.SLACK,
        )
        await router._handle(adapter, incoming)
        return adapter

    adapter = asyncio.run(run())
    progress_updates = [m for m in adapter.updated if "Still working" in m.text]
    assert progress_updates
    assert adapter.updated[-1].text == "Finished the large job"
    assert adapter.updated[-1].update_message_id == "placeholder-1"


def test_router_rejects_nonpositive_progress_interval() -> None:
    with pytest.raises(ValueError, match="progress interval"):
        ChatRouter(_SlowEngine(), progress_interval_seconds=0)  # type: ignore[arg-type]


def test_failed_progress_update_does_not_cancel_large_job() -> None:
    async def run() -> _FakeAdapter:
        adapter = _FakeAdapter(fail_progress_update=True)
        router = ChatRouter(_SlowEngine(), progress_interval_seconds=0.01)  # type: ignore[arg-type]
        incoming = IncomingMessage(
            text="Build a slide deck",
            user=User(Platform.SLACK, "U123"),
            channel=Channel(Platform.SLACK, "C123"),
            platform=Platform.SLACK,
        )
        await router._handle(adapter, incoming)
        return adapter

    adapter = asyncio.run(run())
    assert adapter.updated[-1].text == "Finished the large job"
