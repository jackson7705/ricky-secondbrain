---
name: direct-integrations
description: Query Gmail, Google Calendar, ClickUp, Slack, Google Sheets, Google Docs, and Google Drive directly via Python APIs. Use when the user asks to check email, view calendar, check clickup tasks, check Slack messages, read/write spreadsheets, read documents, or find files in Drive. Triggers on requests like "check my email", "show calendar", "how's click today", "what's overdue", "clickup tasks", "check slack", "read this spreadsheet", "open this google doc", "find files in drive", "show the hackathon sheet", "what's in this doc", or any platform query. Asana is NOT used in this workspace.
---

# Direct Platform Integrations

Query Gmail, Calendar, ClickUp, Slack, Sheets, Docs, and Drive directly — no Zapier needed.

**ClickUp is the only task system in this workspace.** Asana has been removed. The ClickUp MCP is also available (`mcp__claude_ai_ClickUp__*`) for richer ops, but this skill covers the common read queries for fast answers.

## Script Path

`.claude/skills/direct-integrations/scripts/query.py`

## Running Commands

```bash
# Gmail
python .claude/skills/direct-integrations/scripts/query.py gmail list [--max N] [--query Q] [--unread] [--hours N]
python .claude/skills/direct-integrations/scripts/query.py gmail urgent [--hours N]
python .claude/skills/direct-integrations/scripts/query.py gmail unread
python .claude/skills/direct-integrations/scripts/query.py gmail read <message_id>
python .claude/skills/direct-integrations/scripts/query.py gmail thread <thread_id>
python .claude/skills/direct-integrations/scripts/query.py gmail search "subject or query" [--max N]
python .claude/skills/direct-integrations/scripts/query.py gmail attachments <message_id>
python .claude/skills/direct-integrations/scripts/query.py gmail download-attachment <message_id> --attachment-id <id> [--output-dir <path>]

# Calendar
python .claude/skills/direct-integrations/scripts/query.py calendar today
python .claude/skills/direct-integrations/scripts/query.py calendar upcoming [--hours N]
python .claude/skills/direct-integrations/scripts/query.py calendar soon

# ClickUp (Locafy task tracker — Jason's only task system)
python .claude/skills/direct-integrations/scripts/query.py clickup overdue [--max N]
python .claude/skills/direct-integrations/scripts/query.py clickup due-soon [--days N] [--max N]
python .claude/skills/direct-integrations/scripts/query.py clickup my-tasks [--max N] [--include-closed]

# Slack
python .claude/skills/direct-integrations/scripts/query.py slack channels
python .claude/skills/direct-integrations/scripts/query.py slack messages <channel> [--hours N]
python .claude/skills/direct-integrations/scripts/query.py slack send <channel> <message>
python .claude/skills/direct-integrations/scripts/query.py slack check

# Google Sheets
python .claude/skills/direct-integrations/scripts/query.py sheets read <spreadsheet_id> [--range "Sheet1!A1:Z100"] [--max-rows N]
python .claude/skills/direct-integrations/scripts/query.py sheets info <spreadsheet_id>
python .claude/skills/direct-integrations/scripts/query.py sheets write <spreadsheet_id> --range "A1" --values '[["a","b"]]'
python .claude/skills/direct-integrations/scripts/query.py sheets append <spreadsheet_id> --range "A:Z" --values '[["new","row"]]'

# Google Docs
python .claude/skills/direct-integrations/scripts/query.py docs read <document_id> [--max-chars N]
python .claude/skills/direct-integrations/scripts/query.py docs info <document_id>

# Google Drive
python .claude/skills/direct-integrations/scripts/query.py drive find "search term" [--type spreadsheet|document|folder|presentation|pdf] [--max N]
python .claude/skills/direct-integrations/scripts/query.py drive list [--type TYPE] [--max N]
python .claude/skills/direct-integrations/scripts/query.py drive get <file_id>
```

## Setup

If integrations aren't configured yet:
```bash
cd .claude/scripts && uv run python setup_auth.py --check
```

## Notes

- Gmail + Calendar + Sheets + Docs + Drive share a single Google OAuth token
- Sheets has read/write access; Docs and Drive are read-only
- Slack uses Bot Token from .env
- For ClickUp task queries, use the ClickUp MCP tools (`mcp__claude_ai_ClickUp__*`), not this skill.
- Use `drive find` to locate file IDs by name, then pass to `sheets read` or `docs read`
- Gmail attachments: use `gmail attachments` to list, then `gmail download-attachment` to save to disk. Once downloaded, use the Read tool (images) or pdf skill (PDFs) to process the file content.
