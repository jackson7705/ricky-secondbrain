"""Conversation engine wrapping Claude Agent SDK with session persistence."""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any

from models import Attachment, IncomingMessage, OutgoingMessage
from session import HeartbeatThread, PostgresSessionStore, Session, SQLiteSessionStore

# Add scripts dir for shared utilities
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from sanitize import TRUST_BOUNDARY_INSTRUCTION, wrap_external_data  # noqa: E402


# ── Apify MCP loader ──────────────────────────────────────────────────────
#
# Pull the apify MCP server config from ~/.claude.json so Ricky can scrape
# short-form video / social engagement data conversationally (content-research
# over iMessage). Mirrors weekly_content.py's _load_apify_mcp so both the
# scheduled pipeline and the chat agent share one Apify wiring. Token stays
# in-process, never logged. Returns {} if apify isn't configured, so the
# engine degrades gracefully to WebSearch rather than crashing.
def _load_apify_mcp() -> dict:
    """Pull MCP servers from ~/.claude.json for the chat agent.

    - `apify`: short-form/social scraping for content-research.
    - `redis-iris`: Context Retriever query tools over the structured data
      (invoices/vendors/clients) — the additive Redis Iris layer alongside the
      Obsidian vault. See .claude/scripts/redis_iris/.
    Returns {} for any server that isn't configured, so the engine degrades
    gracefully rather than crashing.
    """
    try:
        cfg = json.load(open(os.path.expanduser("~/.claude.json")))
    except (OSError, ValueError):
        return {}
    servers = cfg.get("mcpServers", {})
    return {name: servers[name] for name in ("apify", "redis-iris") if servers.get(name)}


# ── Task runtime profiles ────────────────────────────────────────────────


@dataclass(frozen=True)
class TaskRuntimePolicy:
    """Watchdog limits for one agent request."""

    name: str
    inactivity_timeout_seconds: float
    hard_ceiling_seconds: float

    def __post_init__(self) -> None:
        if self.inactivity_timeout_seconds <= 0:
            raise ValueError("inactivity timeout must be positive")
        if self.hard_ceiling_seconds <= 0:
            raise ValueError("hard ceiling must be positive")
        if self.hard_ceiling_seconds < self.inactivity_timeout_seconds:
            raise ValueError("hard ceiling must be at least the inactivity timeout")


_SLIDE_DECK_INTENT_RE = re.compile(
    r"\b(?:slide\s+deck|deck|slides?|presentation|pptx|powerpoint|keynote)\b",
    re.IGNORECASE,
)

_LARGE_TASK_INTENT_RE = re.compile(
    r"\b(?:"
    r"playbook|handbook|website|web\s+app|application|migration|"
    r"full\s+audit|deep\s+research|"
    r"comprehensive\s+(?:analysis|report|plan|strategy)|"
    r"(?:big|large|long[- ]running|multi[- ]step|end[- ]to[- ]end)\s+"
    r"(?:job|task|project|build|request)"
    r")\b",
    re.IGNORECASE,
)


def _runtime_policy_for(
    text: str,
    normal_policy: TaskRuntimePolicy,
    large_policy: TaskRuntimePolicy,
) -> TaskRuntimePolicy:
    """Select longer watchdog limits for known or explicitly large jobs."""
    if _SLIDE_DECK_INTENT_RE.search(text) or _LARGE_TASK_INTENT_RE.search(text):
        return large_policy
    return normal_policy


def _next_watchdog_timeout(policy: TaskRuntimePolicy, elapsed_seconds: float) -> float:
    """Return the next wait duration without extending the absolute deadline."""
    remaining = policy.hard_ceiling_seconds - elapsed_seconds
    return max(0.0, min(policy.inactivity_timeout_seconds, remaining))


# ── Deliverable directive injection ──────────────────────────────────────
#
# When the user's message looks like a request for a structured document,
# we prepend a hard, non-negotiable rule reminder. SOUL.md alone wasn't
# enough — Jason flagged three consecutive "Ricky knows the rule but
# treated it as optional" failures on 2026-06-03. This makes the rule
# part of every relevant user prompt so the agent literally can't miss it.

_DELIVERABLE_INTENT_RE = re.compile(
    r"\b("
    # Explicit deliverable nouns
    r"briefing|brief\s+on|brief\s+me|executive\s+brief|"
    r"report|write[- ]up|summary\s+document|"
    r"pdf|one[- ]?pager|"
    r"document(?:\s+me)?|give\s+me\s+a\s+doc|"
    # Structured-output requests
    r"roster|list\s+(?:of|what|the|all|every|every)|breakdown|mapping|map\s+out|"
    r"plan|strategy|framework|outline|overview|"
    r"what\s+(?:could|would|should|are|do|does)\s+(?!I\b|you\b)|"
    # Multi-thing enumerations
    r"agents?\b|fleet|roster|"
    # Repo / research deliverables
    r"audit|scrape|analyz(?:e|ing)|summari[sz]e|"
    # "list X" verb usage
    r"^list\s|let'?s\s+list|please\s+list|we\s+need\s+to\s+list|"
    r"we\s+need\s+to\s+(?:list|map|outline|breakdown|summari[sz]e)"
    r")\b",
    re.IGNORECASE | re.MULTILINE,
)

_DELIVERABLE_DIRECTIVE = (
    "[SYSTEM DIRECTIVE FROM CHAT ENGINE — HARD RULE, NOT NEGOTIABLE]\n"
    "Your reply to this turn must be delivered as a BRANDED Locafy PDF uploaded to Google Drive.\n"
    "1. Build the PDF using the `locafy-documents` skill — the BRANDED template "
    "(real Locafy logo, teal #00A89D palette, 'Powered by Locafy Localizer' footer). "
    "Do NOT use the generic `pdf`/fpdf2 path or a plain unbranded document — that is "
    "the failure mode Jason flagged: docs came back generic, no logo, no colors.\n"
    "2. Upload via `integrations.drive_api.upload_file(local_path, "
    "'119jT4HsjLV9Dm-ib1UScX0TYPn2ANaW_')` — that ID is the `Ricky Briefings` "
    "folder in growthpro Drive. For business-scoped briefings, route to the "
    "relevant Locafy/Wonderly/Air Sense folder instead.\n"
    "3. Make the file `anyoneWithLink` reader so Jason can open it on his phone.\n"
    "4. Reply with a 1-3 sentence cover note ending with the Drive webViewLink.\n"
    "Produce ONE document, not two. DO NOT put structured content (multiple H2 "
    "sections, lists with categories, rosters, frameworks) in the chat reply itself. "
    "DO NOT ask 'want me to turn this into a PDF?' — the answer is always yes; just "
    "build it (branded). Jason flagged the missing-content failure mode three times "
    "on 2026-06-03, and the missing-branding failure mode on 2026-06-21.\n"
    "[END DIRECTIVE]\n\n"
)

_SLIDE_DECK_DIRECTIVE = (
    "[SYSTEM DIRECTIVE FROM CHAT ENGINE — SLIDE DECK DELIVERY]\n"
    "Your reply to this turn must be delivered as a branded PowerPoint-compatible "
    "PPTX uploaded to Google Drive.\n"
    "1. Use the `pptx-generator` skill and apply the Locafy brand (real logo, "
    "teal #00A89D palette, and established typography). Do NOT convert the deck "
    "into a generic PDF or use `locafy-documents`; the requested artifact is PPTX.\n"
    "2. Follow the skill's batched generation and visual-validation workflow, then "
    "combine all validated batches into ONE final deck.\n"
    "3. Upload the final PPTX via `integrations.drive_api.upload_file(local_path, "
    "'119jT4HsjLV9Dm-ib1UScX0TYPn2ANaW_')`, or the relevant business folder, and "
    "make it `anyoneWithLink` reader.\n"
    "4. Reply with a 1-3 sentence cover note ending with the Drive webViewLink. "
    "Do not return part files or only a local path.\n"
    "[END DIRECTIVE]\n\n"
)


def _maybe_prepend_deliverable_directive(text: str) -> str:
    """If the user message looks like a deliverable request, prepend the
    hard rule reminder so it lands in every prompt — not just hopefully
    in SOUL.md context that might be stale on resumed sessions."""
    if not text:
        return text
    if _SLIDE_DECK_INTENT_RE.search(text):
        return _SLIDE_DECK_DIRECTIVE + text
    # Cheap-ish keyword match — false positives are fine (worst case: a
    # short chat answer comes back as a 1-page PDF; recoverable).
    if _DELIVERABLE_INTENT_RE.search(text):
        return _DELIVERABLE_DIRECTIVE + text
    return text


class ConversationEngine:
    """Routes incoming messages to Claude Agent SDK and manages session persistence.

    Each unique platform:channel:thread combination maps to a separate Agent SDK
    session. Sessions are persisted in SQLite so conversations survive restarts.
    """

    def __init__(
        self,
        session_store: SQLiteSessionStore | PostgresSessionStore,
        project_root: Path,
        max_turns: int = 25,
        max_budget_usd: float = 2.0,
        rotate_after_days: int = 30,
        rotate_after_usd: float = 75.0,
        rotate_after_messages: int = 15,
        inactivity_timeout_seconds: float = 600,
        hard_ceiling_seconds: float = 1800,
        large_task_inactivity_timeout_seconds: float = 3600,
        large_task_hard_ceiling_seconds: float = 14400,
    ) -> None:
        self.session_store = session_store
        self.project_root = project_root
        self.max_turns = max_turns
        self.max_budget_usd = max_budget_usd
        # Rotate the underlying Agent SDK session when it gets stale. Keeps
        # cumulative cost bounded (so we don't drift back into the $100 budget
        # cap) and keeps the in-context history short (faster + cheaper turns).
        # The chat.db row is reused — same session_id key, fresh agent_session_id.
        self.rotate_after_days = rotate_after_days
        self.rotate_after_usd = rotate_after_usd
        self.rotate_after_messages = rotate_after_messages
        self.normal_runtime_policy = TaskRuntimePolicy(
            name="normal",
            inactivity_timeout_seconds=inactivity_timeout_seconds,
            hard_ceiling_seconds=hard_ceiling_seconds,
        )
        self.large_runtime_policy = TaskRuntimePolicy(
            name="large",
            inactivity_timeout_seconds=large_task_inactivity_timeout_seconds,
            hard_ceiling_seconds=large_task_hard_ceiling_seconds,
        )

    # Attachment extensions to detect in response text. Images delivered inline;
    # PDFs (and docs/sheets/slides) delivered as iMessage file attachments so
    # Jason can open them on phone or AirDrop to laptop. Don't add executable
    # types here — only formats meant for human consumption.
    _ATTACHMENT_EXTENSIONS = {
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff",  # images
        ".pdf",                                                       # docs
        ".docx", ".xlsx", ".pptx",                                    # office
    }

    # Regex: absolute path to a supported attachment file
    _ATTACHMENT_PATH_RE = re.compile(
        r"(?:^|\s)(/[^\s]+\.(?:png|jpe?g|gif|webp|bmp|tiff|pdf|docx|xlsx|pptx))\b",
        re.IGNORECASE,
    )

    @staticmethod
    def _build_attachment_context(attachments: list[Attachment]) -> str:
        """Build a context string describing attached images for the prompt."""
        if not attachments:
            return ""

        lines = ["\n\n[ATTACHED FILES from user via Slack:]"]
        for att in attachments:
            local_path = att.url  # local file path stored in url field
            lines.append(f"- {att.filename} ({att.mimetype}) saved at: {local_path}")
        lines.append(
            "You can use the Read tool to view these images, or pass their paths "
            "to image generation scripts as --ref or --style arguments."
        )
        return "\n".join(lines)

    @staticmethod
    def _extract_attachment_paths(text: str) -> list[tuple[str, str]]:
        """Extract absolute attachment paths + mime types from response text.

        Returns a list of (path, mimetype). Both images AND documents (PDF,
        Office) are detected so Ricky can deliver real briefing files via
        iMessage attachment instead of dumping markdown into the chat.
        """
        import mimetypes
        seen: set[str] = set()
        out: list[tuple[str, str]] = []
        for match in ConversationEngine._ATTACHMENT_PATH_RE.finditer(text):
            candidate = match.group(1)
            if candidate in seen:
                continue
            seen.add(candidate)
            if not Path(candidate).is_file():
                continue
            mime, _ = mimetypes.guess_type(candidate)
            out.append((candidate, mime or "application/octet-stream"))
        return out

    def _get_heartbeat_context(self, channel_id: str, thread_id: str) -> HeartbeatThread | None:
        """Check if a thread originated from a heartbeat notification."""
        try:
            return self.session_store.get_heartbeat_thread(channel_id, thread_id)
        except Exception:
            return None

    def _should_rotate(self, session: Any) -> bool:
        """True if the session is stale enough to rotate.

        Rotates on any dimension:
          - Turns: message_count >= `rotate_after_messages` (default 15)
          - Cost:  cumulative spend > `rotate_after_usd` (default $75)
          - Age:   created_at older than `rotate_after_days` (default 30)

        The turn gate is the real safeguard. Resuming an SDK session replays
        the entire transcript to the API before the agent can emit a token;
        once that transcript is large enough, the silent replay exceeds the
        engine's 180s inactivity timeout and EVERY message aborts. Turn count
        is the cheapest proxy for transcript size (observed: ~25 turns => 10MB
        => resume > 180s => total breakage). Cost and age are secondary nets.
        """
        from datetime import timedelta
        if session.message_count >= self.rotate_after_messages:
            return True
        if session.total_cost_usd > self.rotate_after_usd:
            return True
        age = datetime.now() - session.created_at
        if age > timedelta(days=self.rotate_after_days):
            return True
        return False

    async def handle_message(self, message: IncomingMessage) -> AsyncIterator[OutgoingMessage]:
        """Process an incoming message and yield response chunks.

        Looks up or creates a session, runs the Agent SDK, and yields
        OutgoingMessage objects as Claude responds. The final yield contains
        the complete response text.
        """
        # Lazy imports — heavy dependencies loaded only when needed
        from claude_agent_sdk import (
            AssistantMessage,
            ClaudeAgentOptions,
            HookMatcher,
            ResultMessage,
            TextBlock,
            query,
        )

        from shared import validate_bash_command

        # Build session key
        thread_id = message.thread.thread_id if message.thread else message.channel.platform_id
        platform_str = message.platform.value
        channel_id = message.channel.platform_id

        # Classify from the original user text. Injected directives contain
        # deliverable keywords and must not influence runtime policy selection.
        runtime_policy = _runtime_policy_for(
            message.text,
            self.normal_runtime_policy,
            self.large_runtime_policy,
        )
        print(
            f"[{datetime.now()}] Runtime profile={runtime_policy.name} "
            f"(silence={runtime_policy.inactivity_timeout_seconds:.0f}s, "
            f"ceiling={runtime_policy.hard_ceiling_seconds:.0f}s)"
        )

        # Hard-inject the deliverable rule when the user's message looks like
        # a request for a document/briefing/structured content. Instruction-
        # following via SOUL.md was insufficient — Jason flagged the same
        # failure mode three times on 2026-06-03. This forces the rule into
        # the user prompt on every doc-shaped turn so Ricky can't claim it
        # was out of context.
        message.text = _maybe_prepend_deliverable_directive(message.text)

        # Look up existing session
        existing = self.session_store.get(platform_str, channel_id, thread_id)

        # Rotate stale sessions: bound cumulative cost AND keep agent context
        # short. We reuse the chat.db row (same session_id key) but reset the
        # counters and clear agent_session_id so the SDK spins up a fresh
        # underlying conversation. The vault is the long-term memory; resuming
        # an N-week-old SDK session adds latency without adding much value.
        if existing and self._should_rotate(existing):
            from datetime import timedelta as _td  # noqa: F401  # for clarity in the log
            age = datetime.now() - existing.created_at
            print(
                f"[{datetime.now()}] Rotating session {existing.session_id} "
                f"(age={age}, cost=${existing.total_cost_usd:.2f}, turns={existing.message_count})"
            )
            existing.agent_session_id = ""
            existing.message_count = 0
            existing.total_cost_usd = 0.0
            existing.created_at = datetime.now()

        # Build Agent SDK options
        options_kwargs: dict[str, Any] = {
            "cwd": str(self.project_root),
            "setting_sources": ["user", "project"],
            "system_prompt": {
                "type": "preset",
                "preset": "claude_code",
                "append": (
                    "\n\n# Chat Interface Rules\n"
                    "You are responding through a chat interface (Slack). "
                    "Only your FINAL assistant turn is shown to the user — all intermediate turns "
                    "(tool calls, research, reasoning) are invisible. Therefore:\n"
                    "- Your last message MUST contain the complete, self-contained answer.\n"
                    "- Do NOT split your answer across multiple turns. Do all research/tool calls first, "
                    "then write one comprehensive final response.\n"
                    "- Never end with just sources, references, or a summary — the full report belongs in the final turn.\n"
                    "\n## Sending Images\n"
                    "Generated images (PNG/JPG/etc.) can be sent inline via the chat "
                    "adapter: just include the absolute local path in your final reply "
                    "and the engine auto-attaches it.\n"
                    "\n## Producing Briefings, Reports, and Documents — Drive Always\n"
                    "When the user asks for a 'briefing', 'document', 'report', 'PDF', "
                    "'one-pager', 'deck', 'write-up', or any deliverable that implies a "
                    "real file (not a chat message), you MUST:\n"
                    "1. Build the actual file with the **`locafy-documents`** skill — "
                    "the BRANDED Locafy template (real logo, teal #00A89D palette, "
                    "'Powered by Locafy Localizer'). For SEO/GSC reports use "
                    "`locafy-gsc-reporting`; for slide decks use `pptx-generator` but "
                    "apply the same brand. Do NOT use the generic `pdf`/fpdf2 path — it "
                    "produces unbranded docs. Write to a temp path on disk.\n"
                    "2. **Upload to Google Drive — ALWAYS.** Use "
                    "`integrations.drive_api.upload_file(local_path, parent_folder_id)`. "
                    "Default folder for general briefings: `119jT4HsjLV9Dm-ib1UScX0TYPn2ANaW_` "
                    "(the `Ricky Briefings` folder in growthpro Drive). For "
                    "business-scoped work, use the relevant Locafy/Wonderly/Air Sense "
                    "expenses folder instead.\n"
                    "3. Make the uploaded file `anyoneWithLink` reader so Jason can open "
                    "it on his phone without re-auth.\n"
                    "4. Reply with a brief cover note (1-3 sentences) — what's in it, "
                    "headline finding, any follow-ups — and **end with the Drive link "
                    "(webViewLink)**, NOT the local path.\n"
                    "Anti-patterns to avoid:\n"
                    "- Dumping the full markdown into the chat instead of producing a file.\n"
                    "- Producing the file but sending the local path. Local paths don't "
                    "open on his phone; Drive links do. Confirmed 2026-06-03.\n"
                ),
            },
            "mcp_servers": _load_apify_mcp(),
            "allowed_tools": [
                "Read",
                "Write",
                "Edit",
                "Bash",
                "Glob",
                "Grep",
                "Skill",
                "WebSearch",
                "WebFetch",
                "NotebookEdit",
                # Subagent dispatch. Without this, the 78 specialists in
                # .claude/agents/ are only reachable from a Claude Code session
                # — over Slack/iMessage they were unreachable dead weight.
                # Tool name verified against the bundled CLI (2.1.114): the tool
                # registers as "Agent" with "Task" as a legacy alias.
                "Agent",
                # Apify MCP — lets content-research score real engagement
                # (view counts) on short-form refs instead of best-effort
                # site:-restricted guessing. No-op if apify isn't configured.
                "mcp__apify__search-actors",
                "mcp__apify__fetch-actor-details",
                "mcp__apify__call-actor",
                "mcp__apify__get-dataset-items",
                "mcp__apify__get-actor-run",
                # Redis Iris Context Retriever — structured queries over
                # invoices / vendors / clients (see .claude/scripts/redis_iris).
                "mcp__redis-iris__get_invoice_by_id",
                "mcp__redis-iris__filter_invoice_by_vendor",
                "mcp__redis-iris__filter_invoice_by_business",
                "mcp__redis-iris__filter_invoice_by_month",
                "mcp__redis-iris__filter_invoice_by_status",
                "mcp__redis-iris__find_invoice_by_amount_range",
                "mcp__redis-iris__search_invoice_by_text",
                "mcp__redis-iris__get_vendor_by_id",
                "mcp__redis-iris__filter_vendor_by_business",
                "mcp__redis-iris__search_vendor_by_text",
                "mcp__redis-iris__get_client_by_id",
                "mcp__redis-iris__filter_client_by_business",
                "mcp__redis-iris__filter_client_by_property_url",
                "mcp__redis-iris__search_client_by_text",
            ],
            "permission_mode": "acceptEdits",
            "max_turns": self.max_turns,
            "max_budget_usd": self.max_budget_usd,
            # SDK default is 1MB which is too small once a turn includes tool
            # results from large file reads or repeated Drive operations.
            # 2026-06-04: observed a JSON-buffer overflow on a simple receipt-
            # filing message. Bump to 10MB; cost of memory is negligible.
            "max_buffer_size": 10 * 1024 * 1024,
            "hooks": {
                "PreToolUse": [
                    HookMatcher(
                        matcher="Bash",
                        hooks=[validate_bash_command],
                    )
                ]
            },
        }

        # Resume existing conversation if we have a session AND it has an
        # agent SDK id (rotation clears it to force a fresh underlying session).
        if existing and existing.agent_session_id:
            options_kwargs["resume"] = existing.agent_session_id
            print(f"[{datetime.now()}] Resuming session {existing.session_id}")
        else:
            session_key = f"{platform_str}:{channel_id}:{thread_id}"
            print(f"[{datetime.now()}] Starting new session for {session_key}")

            # Check if this is a thread reply to a heartbeat notification
            hb_thread = self._get_heartbeat_context(channel_id, thread_id)
            if hb_thread:
                wrapped_alert = wrap_external_data(hb_thread.alert_text, "heartbeat_alert")
                message.text = (
                    f"[CONTEXT: This conversation started from a heartbeat alert. "
                    f"Original alert:\n{wrapped_alert}\n"
                    f"{TRUST_BOUNDARY_INSTRUCTION}]\n\n"
                    f"{message.text}"
                )
                print(f"[{datetime.now()}] Injected heartbeat context into session")

        # Append attachment context (images sent via Slack)
        attachment_ctx = self._build_attachment_context(message.attachments)
        if attachment_ctx:
            message.text += attachment_ctx
            print(f"[{datetime.now()}] Injected {len(message.attachments)} attachment(s) into prompt")

        options = ClaudeAgentOptions(**options_kwargs)

        # Run the agent
        response_text = ""
        session_id_from_sdk: str | None = None
        cost_usd: float | None = None
        first_yield = True

        # Inactivity timeout. Resets on each SDK message. Large tasks receive a
        # separate, longer policy because the SDK emits no events while one long
        # render/generation/upload tool call is in flight.
        # 2026-06-03 origin: a 5-min wall-clock hang on a 1-line message cost
        # ~$2 in a tool loop. 2026-06-08: wall-clock was killing legit
        # 4-min+ doc workflows; switched to inactivity.
        import asyncio as _asyncio
        # Inactivity timeout as a TRUE per-gap wall-clock limit via wait_for: it
        # resets on every SDK message, so legitimate long work (a Chrome PDF
        # render, a large doc generation, multi-step Drive uploads) survives as
        # long as SOMETHING keeps arriving, while a genuine hang is caught at the
        # threshold rather than only retroactively when the next message lands.
        # The wait duration is capped by the remaining hard ceiling, so the
        # absolute deadline is enforced even when no SDK message ever arrives.
        agent_started = monotonic()

        try:
            _agen = query(prompt=message.text, options=options).__aiter__()
            while True:
                elapsed_total = monotonic() - agent_started
                hard_ceiling_is_next = (
                    runtime_policy.hard_ceiling_seconds - elapsed_total
                    <= runtime_policy.inactivity_timeout_seconds
                )
                wait_timeout = _next_watchdog_timeout(runtime_policy, elapsed_total)
                if wait_timeout <= 0:
                    raise TimeoutError(
                        f"Agent took >{runtime_policy.hard_ceiling_seconds:.0f}s total — aborted."
                    )
                try:
                    sdk_message = await _asyncio.wait_for(
                        _agen.__anext__(), timeout=wait_timeout
                    )
                except StopAsyncIteration:
                    break
                except TimeoutError:
                    elapsed_total = monotonic() - agent_started
                    if hard_ceiling_is_next:
                        print(
                            f"[{datetime.now()}] Agent SDK hard ceiling hit after "
                            f"{elapsed_total:.0f}s — aborting runaway"
                        )
                        raise TimeoutError(
                            f"Agent took >{runtime_policy.hard_ceiling_seconds:.0f}s "
                            "total — aborted."
                        )
                    print(
                        f"[{datetime.now()}] Agent SDK inactivity timeout after "
                        f"{runtime_policy.inactivity_timeout_seconds:.0f}s of silence "
                        f"(profile={runtime_policy.name}) — aborting"
                    )
                    raise TimeoutError(
                        "Agent went silent for "
                        f">{runtime_policy.inactivity_timeout_seconds:.0f}s — aborted."
                    )
                if isinstance(sdk_message, AssistantMessage):
                    # Reset on each new AssistantMessage (keep only the latest turn)
                    response_text = ""
                    for block in sdk_message.content:
                        if isinstance(block, TextBlock):
                            response_text += block.text

                    # Yield response updates
                    if response_text.strip():
                        yield OutgoingMessage(
                            text=response_text,
                            channel=message.channel,
                            thread=message.thread,
                            is_update=not first_yield,
                        )
                        first_yield = False

                elif isinstance(sdk_message, ResultMessage):
                    session_id_from_sdk = sdk_message.session_id
                    cost_usd = sdk_message.total_cost_usd
                    cost_str = f"${cost_usd:.4f}" if cost_usd else "N/A"
                    print(
                        f"[{datetime.now()}] Agent completed: "
                        f"session={session_id_from_sdk}, cost={cost_str}"
                    )

                    # Scan final response for attachment paths (images + PDFs +
                    # office docs) and send them back through the chat adapter.
                    attachment_paths = self._extract_attachment_paths(response_text)
                    if attachment_paths:
                        attachments_out = [
                            Attachment(filename=Path(p).name, mimetype=mt, url=p)
                            for p, mt in attachment_paths
                        ]
                        kinds = ", ".join(sorted({mt for _, mt in attachment_paths}))
                        print(
                            f"[{datetime.now()}] Detected {len(attachments_out)} "
                            f"attachment(s) to send back ({kinds})"
                        )
                        yield OutgoingMessage(
                            text=response_text,
                            channel=message.channel,
                            thread=message.thread,
                            is_update=not first_yield,
                            attachments=attachments_out,
                        )
                        first_yield = False

        except Exception as e:
            print(f"[{datetime.now()}] Agent SDK error: {e}")
            yield OutgoingMessage(
                text=f"Sorry, I hit an error: {e}",
                channel=message.channel,
                thread=message.thread,
                is_update=not first_yield,
            )
            return

        # Persist session
        if session_id_from_sdk:
            now = datetime.now()
            if existing:
                existing.agent_session_id = session_id_from_sdk
                existing.message_count += 1
                existing.total_cost_usd += cost_usd or 0.0
                existing.updated_at = now
                self.session_store.update(existing)
            else:
                session = Session(
                    session_id=f"{platform_str}:{channel_id}:{thread_id}",
                    agent_session_id=session_id_from_sdk,
                    platform=platform_str,
                    channel_id=channel_id,
                    thread_id=thread_id,
                    user_id=message.user.platform_id,
                    created_at=now,
                    updated_at=now,
                    message_count=1,
                    total_cost_usd=cost_usd or 0.0,
                )
                self.session_store.create(session)
