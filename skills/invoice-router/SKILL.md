---
name: invoice-router
description: Two-step receipt triage — SCAN sweeps Gmail inboxes and proposes how each invoice should be filed (which business, which month folder, which vendor). APPLY uploads and sheet-logs only entries Jason has explicitly approved. Never auto-files. Use when Jason says "run the invoice router", "check receipts", "file my receipts", or when the daily launchd job fires.
---

# invoice-router

Daily receipt triage for Jason. Turns the "200 receipts sitting in my inbox at tax time" pain into "everything is filed and logged — after Jason approves each one."

## Core Rule

**The two-step SCAN→APPROVE→APPLY flow never uploads without approval.** See `memory/feedback_confirm_before_filing.md`. Every scanned receipt becomes a proposal in `pending-clarification.json`; only `approved` entries get applied.

## ⚡ PRIMARY PATH — `file-now` (use this for "[Vendor] is [Business] [Month]")

When Jason says **"[Vendor] is [Business] [Month]"** (e.g. "Vercel is Locafy June", "Anthropic is Locafy June") he means **file that vendor's latest receipt NOW** — it's his standing shorthand, no confirmation needed. Do NOT do the scan→add-to-queue→approve→apply dance for these; that path is fragile for fresh receipts and has stalled repeatedly. Run ONE command:

```bash
cd .claude/skills/invoice-router && uv run --project ../../scripts python main.py file-now --vendor vercel --business locafy --month 2026-06
```

It searches ALL inboxes (growthpro/locafy/wonderly), finds the vendor's most recent receipt, downloads the PDF, extracts the amount from the email body, uploads to the right Drive month folder, logs the expense row, and records it — self-contained, no approval prompt, no asking Jason for the amount. Then reply with the Drive link and the amount.

- The receipt is often in the **Locafy inbox** (`jason.jackson@locafy.com`) — `file-now` already covers it; don't assume growthpro only.
- If it prints `[warn] amount not found in email body`, the amount lives only in the PDF — open the PDF, read the total, and correct the sheet cell.
- If `[not-found]`, the receipt may be older than 120 days or under a different vendor spelling — try `--account locafy` or a different `--vendor` token.
- `[already-filed]` means it's done — just report that.

The SCAN/APPROVE/APPLY flow below is for the **bulk backlog** (many receipts at once), not same-day one-offs.

## Two-Step Flow (bulk backlog)

### Step 1 — SCAN (read-only)

```bash
cd .claude/skills/invoice-router && uv run --project ../../scripts python main.py scan
cd .claude/skills/invoice-router && uv run --project ../../scripts python main.py scan --hours 72
```

- Sweeps Primary inbox of `growthpro`, `locafy`, `wonderly` for invoice/receipt emails.
- Classifies each: guessed vendor, business (locafy/wonderly/personal), use, amount, month.
- Appends a proposal to `pending-clarification.json` with `status: awaiting_confirmation`.
- **Does not touch Drive or Sheets.**

### Step 2 — APPROVE

Jason edits `pending-clarification.json` (or Ricky surfaces the queue in iMessage and updates the file per Jason's replies):
- Change `status` from `awaiting_confirmation` → `approved` for items to file.
- Change `status` → `declined` for items to ignore.
- Override any fields the classifier got wrong (`business`, `vendor`, `use`, `amount`, `proposed_month`).

> **Editing the ledger when it's large (100+ entries):** the `Edit` tool's exact-string match is brittle on a big file. Write a small Python helper to flip the one entry's status by `message_id` and run it — this is fine, the whole `invoice-router/` dir is permission-allowlisted for Write/Edit/Bash. Do NOT abandon the flow when a single `Edit` doesn't take.
> **Receipt not in the ledger yet** (a fresh email like a same-day receipt): run `main.py scan` first to add it as an `awaiting_confirmation` entry, then approve just that one, then apply. Don't hand-fabricate a one-off filing path.
> **Before `apply`, confirm exactly which entries are `approved`** — `apply` files every `approved` entry. Make sure only the intended ones are flipped (there may be a stale `approved` left over).

### Step 3 — APPLY (writes)

```bash
cd .claude/skills/invoice-router && uv run --project ../../scripts python main.py apply
```

- Processes every entry with `status: approved`.
- Downloads the PDF attachment.
- Uploads to the correct month folder inside `💳 Locafy Expenses` or `💳 Wonderly Expenses` (auto-creates the month folder if missing).
- For Locafy and Wonderly: appends a row to the matching `Expense Tracker` sheet (column E is a `=HYPERLINK(url, "Invoice")` formula pointing at the Drive file).
- Saves the vendor → business mapping to `vendor-memory.json` so we don't re-ask.
- Marks the entry `status: applied`.

## Drive / Sheet Layout

- **Locafy expense folder:** `133pCig8B41OajcYN3vHZnR_tovKsYz-X` (has `January`, `February `, `March `, `April ` subfolders)
- **Wonderly expense folder:** `1QwmXXdNSSAPM2_cSupUze3xym9PP6IM2` (has `April `, `May ` subfolders)
- **Locafy Expense Tracker sheet:** `1Mi0p1_ZYsDVehS2sK95UB0FiPTGyphqvpZWrvzcJK8Q` (lives inside Locafy Expenses). One tab per month: `January `, `February `, `March`, `April`, `May`. Columns A–E: Website, Use, Cost, Reimbursed, Link to Invoice.
- **Wonderly Expense Tracker sheet:** `1itXSrN7CSjEXGM-ZC9XBhnxOaxY43weR-8pEbvFj7O8` (lives inside Wonderly Expenses). Same column layout as Locafy. Tabs: `April`, `May`.

## Run

```bash
# Daily run (normally fired by launchd at 09:00 CT)
cd .claude/skills/invoice-router && uv run --project ../../scripts python main.py

# Ad-hoc for a specific lookback window
cd .claude/skills/invoice-router && uv run --project ../../scripts python main.py --hours 72

# Dry run — classify but don't upload / don't log
cd .claude/skills/invoice-router && uv run --project ../../scripts python main.py --dry-run
```

## Files

- `main.py` — orchestrator. Pulls emails → classifies → uploads → logs → queues ambiguities.
- `config.py` — folder IDs, sheet ID, confidence thresholds, attachment rules.
- `vendor-memory.json` — learned vendor → business mapping. Grows over time from Jason's clarifications.
- `pending-clarification.json` — queue of ambiguous emails awaiting Jason's answer.
- `state.json` — `last_scanned_at` per profile so we don't re-process the same emails.

## Conventions

- **Classification confidence** ≥ 0.8 to auto-file. Below that → clarification queue.
- **Personal receipts** (Grubhub, Uber Eats, Doordash, Ace Hardware, etc.) are marked `personal` and **not uploaded to expense folders** — just logged to sheet with `business: personal`.
- **Never delete, archive, or modify the original Gmail message.** The skill is read-only on Gmail.
- **Idempotency:** same Gmail `message_id` never gets processed twice (checked against state + sheet column).
- **Partner-side invoices** (invoices Locafy receives from vendors) go to Locafy expenses. Invoices Jason sends to partners are out of scope for v1.

## Related

- `.claude/scripts/integrations/gmail.py` — email listing, attachment download
- `.claude/scripts/integrations/drive_api.py` — `upload_file()` (added 2026-04-19 for this skill)
- `.claude/scripts/integrations/sheets_api.py` — `append_to_spreadsheet()` for the expense log
- `.claude/scripts/integrations/auth.py` — multi-profile OAuth. Requires `drive.file` scope; re-auth if you haven't since 2026-04-19.
