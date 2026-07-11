---
name: meeting-concierge
description: Two flows around Jason's meetings. BRIEF (pre-meeting) checks his calendars for anything starting in the next 15 min and texts a short prep brief — attendees, related ClickUp tasks, past notes. DIGEST (post-meeting) pulls the Fathom recording + action items and stages a proposal for ClickUp tasks and follow-up email drafts (never auto-created). Use when Jason says "brief me on my next meeting", "any meetings coming up?", "process my last Fathom", "write my follow-ups", or when the pre-meeting launchd job fires.
---

# meeting-concierge

Two jobs, one skill.

## Pre-Meeting Brief (pre)

Every 5 minutes during active hours, check all three Google calendars for events starting in the next 15 minutes. If one is found and hasn't been briefed yet:

1. Pull attendees, calendar description, and any attached doc links.
2. Look up related ClickUp tasks (match by attendee email or meeting title keywords).
3. Check recent emails from attendees (last 14 days).
4. Compose a brief under 600 chars and send to Jason's iMessage:
   - Meeting title + time + attendees
   - Related open ClickUp tasks
   - Recent email context (one-liner per thread)
   - Any prep gap ("no agenda doc yet — want me to draft one?")

### Never auto-create content. Always propose.

If the brief spots a prep gap (no agenda, no prep doc), it offers to draft one — it doesn't create the doc.

## Post-Meeting Digest (post)

After Fathom finishes recording a meeting:

1. Pull the meeting's action items + transcript summary via Fathom MCP.
2. For each action item:
   - Classify the assignee (Jason vs someone on Jason's team vs external partner).
   - Draft a ClickUp task (list, name, description, assignee, due date).
   - If the action item requires a follow-up email, draft that too (in Jason's voice — see `tone-of-voice.md`).
3. Stage everything in `pending-digest.json` with `status: awaiting_confirmation`.
4. Ping Jason with a one-line summary: *"Meeting with X produced 4 action items — say 'approve' to file them in ClickUp."*

Jason confirms via iMessage, then `apply` runs the creates. Same two-step pattern as `invoice-router` — per the `always-confirm-before-filing` rule.

## Commands

```bash
# Pre-meeting brief — run by launchd every 5 min during 08:00–22:00 CT
cd .claude/skills/meeting-concierge && uv run --project ../../scripts python main.py brief

# Post-meeting digest — run on demand or when Fathom webhook fires
cd .claude/skills/meeting-concierge && uv run --project ../../scripts python main.py digest

# Apply approved ClickUp tasks + email drafts from the digest queue
cd .claude/skills/meeting-concierge && uv run --project ../../scripts python main.py apply
```

## Files

- `main.py` — orchestrator for all three subcommands
- `meeting_config.py` — timing, ClickUp list mapping, recency windows, filter rules
- `state.json` — last-briefed event IDs (so we don't re-brief), last-processed Fathom recording ID
- `pending-digest.json` — queued ClickUp/email proposals awaiting Jason's approval

## Dependencies

- **Fathom MCP** (`mcp__fathom__*`) — installed via `claude mcp add fathom -- npx mcp-remote@latest https://api.fathom.ai/mcp`. Requires OAuth on first invocation.
- **Calendar** — already multi-account via `integrations/calendar_api.py` + `integrations/auth.py`.
- **ClickUp** — via `integrations/clickup_api.py` for task reads; creates go through ClickUp MCP on apply.
- **Gmail** — via `integrations/gmail.py` for recent-email context and draft creation.
- **iMessage** — outbound briefs go through the running chat service (writes a message via BlueBubbles REST).

## Launchd

`com.jasonsecondbrain.meetingbrief` — `brief` runs every 300s during 08:00–22:00 America/Chicago. Outside that window the script exits immediately, so safe to let launchd fire regardless.

## Related

- [[BACKLOG]] — Priority 5 spec
- [[invoice-router/SKILL]] — same two-step proposal/apply pattern
