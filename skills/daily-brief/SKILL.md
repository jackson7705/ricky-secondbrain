---
name: daily-brief
description: Jason's daily executive brief system. Morning brief (Mon–Fri 7am CT) is an at-a-glance COO rundown — schedule across all three calendars, overdue ClickUp, inbox signal, yesterday's wins, today's one thing. Weekly rollup (Friday 4pm CT) covers wins/slipped/weekend setup. Delivered via iMessage. Never auto-files or auto-sends on Jason's behalf — this is output-only.
---

# daily-brief

Two scheduled briefs, both delivered to Jason's iMessage:

- **morning** — Mon–Fri 7:00 CT. Executive rundown for the day ahead.
- **weekly** — Fri 16:00 CT. Week-over-week rollup with weekend setup.

## When to invoke

Manually:
```bash
cd .claude/skills/daily-brief
uv run --project ../../scripts python main.py morning --dry-run   # preview
uv run --project ../../scripts python main.py morning             # send
uv run --project ../../scripts python main.py weekly --dry-run
uv run --project ../../scripts python main.py weekly
```

Automatically: `com.jasonsecondbrain.dailybrief.morning` and `...weekly` launchd jobs fire hourly across the active window; the script gates on `America/Chicago` weekday+hour and per-day dedup.

## Morning brief structure

```
Good morning, Jason.

Today: <1-line summary — meeting count, overdue count, the one thing>

Schedule
• 09:00 [locafy] 1:1 with Paul
• 10:30 [growthpro] Acme call
• …

Inbox (growthpro primary)
• 14 unread · 2 from flagged senders
• Re: Board packet — Mark Demilio
• Q1 numbers — Paul Harvell

ClickUp
• Overdue (3): Real Estate CE, Q2 board deck, …
• Due today (2): …

Yesterday shipped
• Closed Fathom digest for Stripe sync
• Sent SuperSend renewal

The one thing: <my read of the priority — falsifiable>
```

## Weekly rollup structure

```
Friday wrap, week of Apr 14.

Shipped this week
• …

Slipped / rolled
• …

Weekend setup — Mon/Tue preview
• …

One question for the weekend: <strategic>
```

## Design rules

- **Deterministic composition** — no LLM in v1. The brief is assembled from real data; no hallucinations possible.
- **Idempotent** — state file tracks `last_sent` per subcommand per date (America/Chicago). Re-running the same day is a no-op.
- **Quiet exit outside window** — launchd fires hourly; the script silently exits unless it's actually the send hour in CT.
- **Locked to Central** — timezone is not Mac-local. Script uses `ZoneInfo("America/Chicago")` for all gating.
- **Output-only** — never writes to ClickUp, never sends email, never marks anything read.
