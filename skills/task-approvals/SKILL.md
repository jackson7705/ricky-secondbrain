---
name: task-approvals
description: Approve, reject, or list ClickUp task proposals queued by Ricky's scheduled jobs (inbox sweep, Fathom sweep). Use when the owner replies to a "proposed task(s)" message with "add 12, 14", "add all", "skip 13", "skip all", or asks what's pending. Never create ClickUp tasks without this approval step.
---

# Task approvals — the ClickUp gate

Owner's standing rule (2026-09-17): **nothing goes on his ClickUp list without a
numbered proposal and an explicit yes.** Scheduled jobs therefore *propose*; this
skill is how an approval turns into real tasks.

## When the owner replies to a proposal

Proposal messages look like:

```
📋 3 proposed task(s) from your inbox — NOT filed yet:
#12 Reply to Jeff (Local Siren) re: pricing questions
#13 Review and sign Map Labs NDA
#14 Send Taylor the SEO report (due 2026-09-18)
Reply "add 12, 13" or "add all" ...
```

Map the reply to one command, run it from `.claude/scripts`, and confirm:

| Owner says | Run |
|---|---|
| "add 12, 14" / "yes to 12 and 14" / "file 12" | `uv run python pending_tasks.py approve 12 14` |
| "add all" / "yes all" / "file them" | `uv run python pending_tasks.py approve all` |
| "skip 13" / "not 13" / "drop 13" | `uv run python pending_tasks.py reject 13` |
| "skip all" / "none of those" | `uv run python pending_tasks.py reject all` |
| "what's pending" | `uv run python pending_tasks.py list` |

Ids are stable and global, so an approval hours later still works. Reply with what
was filed (title + ClickUp link from the command output) and what is still pending.

## Rules

- A thumbs-up / "liked" reaction is **not** approval. Words are.
- "Approve" or "yes" with no numbers right after a single proposal = that proposal.
  If several proposals are outstanding, ask which (or list them).
- Your own suggestions follow the same gate: end the reply with a short numbered
  list, file only what he approves next turn. Never `create_task` as a side effect.
- "Not in ClickUp" means do the work with no task and stop offering in that thread.

State lives in `.claude/data/state/pending-tasks.json`; unanswered proposals expire
after 7 days and rejected titles are remembered so the same email isn't re-proposed.
