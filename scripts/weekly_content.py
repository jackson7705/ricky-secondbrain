"""Weekly content engine — Sunday 8am.

Discovers viral AEO/SEO short-form content across creators (TikTok + Instagram via
the Apify MCP), writes 5 standalone viral scripts in Jason's voice using the
short-form-script hook library, and drops them into a fresh Google Doc in the
"Ideas" Drive folder so Jason can plan the week ahead.

Architecture mirrors heartbeat.py: the Agent SDK does the discovery + writing, then
deterministic Python creates the Google Doc (drive.file) and notifies. Runs locally
via launchd because it needs the Apify MCP, the skills, and the Drive write that
only exist on this machine.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import timedelta
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    TextBlock,
    query,
)

from config import MEMORY_DIR, PROJECT_ROOT, now_local
from make_gdoc import create_doc
from notifications import send_toast_notification
from shared import append_to_daily_log, log_hook_execution, validate_bash_command

DRIVE_FOLDER_ID = "1KyK9y1Acav8AFOZ0_0mmzKocmIaaDMjS"  # "Ideas" folder
RESEARCH_DIR = MEMORY_DIR / "research-logs"
HOOKS_DB = Path.home() / ".claude/skills/short-form-script/references/hooks-database.json"


def _load_apify_mcp() -> dict:
    """Pull the apify MCP server config from ~/.claude.json so the headless agent
    can scrape. Token stays in-process, never logged."""
    cfg = json.load(open(os.path.expanduser("~/.claude.json")))
    apify = cfg.get("mcpServers", {}).get("apify")
    return {"apify": apify} if apify else {}


def _week_label() -> str:
    """Monday of the upcoming/current week, e.g. 'Week of June 15, 2026'."""
    today = now_local().date()
    monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7) if today.weekday() != 0 else today
    # Sunday run -> the Monday that starts tomorrow's week
    monday = today + timedelta(days=(0 - today.weekday()) % 7)
    if monday < today:
        monday += timedelta(days=7)
    return monday.strftime("Week of %B %-d, %Y")


PROMPT_TEMPLATE = """You are running Jason Jackson's weekly content engine. Produce 5 short-form video ideas with standalone viral scripts for his AEO / AI-search / SEO lane, then write them to a markdown file. Follow EVERY rule below.

# Niche & voice (hard rules)
- Niche: AEO, AI search (ChatGPT / Perplexity / Google AI Overviews), SEO, technical + local SEO, Google Business Profile, getting cited/recommended by AI. NEVER cold email, lead gen, or outreach.
- Voice: Jason Jackson, COO of Locafy. Confident practitioner-authority, plain-spoken, lightly contrarian, one sharp idea per video.
- Sell visibility and trust, not leads. Never promise leads, revenue, or guaranteed rankings. If a script needs a specific statistic, keep it general or attribute it to "recent studies" rather than inventing a precise number.
- NO em dashes and NO emojis anywhere in scripts or hooks (the green circle in headings below is the one exception, keep it). Use commas, periods, or hyphens.

# Step 1 — Discover viral content (use the Apify MCP, not WebSearch)
Find viral, on-topic content across MANY creators (do not rely on a fixed list, discover new ones):
- TikTok: mcp__apify__call-actor with actor "clockworks/tiktok-scraper", input {{"searchQueries": ["AI search optimization","answer engine optimization","AI overviews SEO","rank on ChatGPT","GEO SEO AI"], "searchSection": "/video", "videoSearchSorting": "MOST_LIKED", "videoSearchDateFilter": "LAST_3_MONTHS", "resultsPerPage": 8, "excludePinnedPosts": true}}, then mcp__apify__get-dataset-items.
- Instagram: mcp__apify__call-actor with actor "apify/instagram-scraper", input {{"directUrls": ["https://www.instagram.com/explore/tags/aisearch/","https://www.instagram.com/explore/tags/aeo/","https://www.instagram.com/explore/tags/answerengineoptimization/"], "resultsType": "reels", "resultsLimit": 12, "onlyPostsNewerThan": "3 months"}}, then mcp__apify__get-dataset-items.
- Keep total Apify spend under $1. Filter OUT off-topic noise (rankings memes, non-English, unrelated AI tool lists). Keep clips with a clear claim Jason can teach around, decent engagement, English.

# Step 2 — Pick 5
- 5 ideas, ONE per creator (5 distinct creators). Spread across TikTok and Instagram. Favor viral / high-engagement, on-niche, reactable clips.

# Step 3 — Write standalone viral scripts
- Read the hook library at {hooks_db} and pull 5-6 hooks per idea that fit the topic (adapt wording to the specific idea).
- Each Script is STANDALONE: Jason records it start to finish. The reference clip is for familiarity only, he does NOT react to it on camera and the script must not summarize or reference "this video" or "he says". Open on the lead hook, deliver Jason's own teaching/framework, close with a clear takeaway.

# Step 4 — Write the file
Write the result to EXACTLY this path: {output_md}
Use EXACTLY this markdown structure (no preamble before Idea #1):

### 🟢 IDEA #1: <short title> [Reference: <Platform> — @<creator>]
Reference (watch for familiarity only): <clip url>

TEXT HOOK:
— <hook 1>
— <hook 2>
— <hook 3>
— <hook 4>
— <hook 5>

<one or two plain caption-style hooks, no dash>

Script:

<standalone viral script, several short paragraphs>

(repeat for IDEA #2 through #5)

When the file is written, reply with just the 5 idea titles and the platforms. Do not try to create the Google Doc yourself; that happens automatically after you finish.
"""


async def run_agent(output_md: Path) -> str:
    prompt = PROMPT_TEMPLATE.format(hooks_db=HOOKS_DB, output_md=output_md)
    mcp = _load_apify_mcp()
    response_text = ""
    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            cwd=str(PROJECT_ROOT),
            setting_sources=["user", "project"],
            system_prompt={"type": "preset", "preset": "claude_code"},
            mcp_servers=mcp,
            allowed_tools=[
                "Read", "Write", "Edit", "Bash", "Glob", "Grep", "Skill",
                "mcp__apify__call-actor",
                "mcp__apify__get-dataset-items",
                "mcp__apify__fetch-actor-details",
            ],
            permission_mode="bypassPermissions",
            max_turns=80,
            hooks={"PreToolUse": [HookMatcher(matcher="Bash", hooks=[validate_bash_command])]},
        ),
    ):
        if isinstance(message, AssistantMessage):
            response_text = ""
            for block in message.content:
                if isinstance(block, TextBlock):
                    response_text += block.text
        elif isinstance(message, ResultMessage):
            cost = f"${message.total_cost_usd:.2f}" if message.total_cost_usd else "N/A"
            print(f"[{now_local()}] weekly_content agent done: {message.subtype}, cost={cost}")
    return response_text


def main() -> None:
    started = now_local()
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    stamp = started.strftime("%Y-%m-%d")
    output_md = RESEARCH_DIR / f"ideas-week-of-{stamp}.md"
    title = f"Ideas — {_week_label()}"
    status, detail = "OK", ""
    try:
        asyncio.run(run_agent(output_md))
        if not output_md.exists() or output_md.stat().st_size < 400:
            raise RuntimeError("agent did not produce a usable ideas file")
        link = create_doc(str(output_md), DRIVE_FOLDER_ID, title)
        detail = link or "created (no link returned)"
        append_to_daily_log(
            f"Weekly content engine ran. New ideas doc: {title}\n{link}",
            section_name="Weekly Content",
        )
        send_toast_notification("Week's content ideas are ready", f"{title} is in your Ideas folder")
        print(f"[{now_local()}] weekly_content created doc: {link}")
    except Exception as e:  # noqa: BLE001
        status, detail = "FAIL", str(e)[:300]
        send_toast_notification("Weekly content engine failed", detail)
        print(f"[{now_local()}] weekly_content ERROR: {e}")
    finally:
        dur = (now_local() - started).total_seconds()
        log_hook_execution("weekly-content", "scheduled", status, dur, detail[:200])


if __name__ == "__main__":
    main()
