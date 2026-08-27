---
name: airsense-bills
description: WinSupply invoices in the Air Sense inbox → bills in QuickBooks. SCAN sweeps jason@airsenseenvironmental.com and queues each new invoice; APPLY creates QBO bills only for entries Jason marked 'approved'. Never files autonomously. Use when Jason says "check the WinSupply invoices", "file the Air Sense bills", "any new invoices from WinSupply", or when the scheduled job fires.
---

# airsense-bills

Turns WinSupply's daily invoice emails into QuickBooks bills for **Air Sense Environmental** — after Jason approves each one.

## Core Rules

**1. APPLY never writes a bill that isn't marked `approved`.** Same gate as
`invoice-router` and `email-triage`: parse → propose → Jason approves → file.

**2. A duplicate must never reach QuickBooks.** Jason's standing requirement.
Four independent layers enforce it — see below.

## Commands

```bash
cd .claude/skills/airsense-bills

python3 main.py scan --days 14      # read-only; queue new invoices
python3 main.py scan --days 3 --notify   # what the hourly job runs
python3 main.py list                # show the queue
python3 main.py apply --dry-run     # show what would be filed, write nothing
python3 main.py apply               # file approved entries only

# record invoices already in QBO (entered by hand) so they can never be filed
python3 main.py mark-existing --dry-run
python3 main.py mark-existing --before 2026-08-22
```

Approving is a status edit in `pending-bills.json`: set `"status": "approved"` on
the entries Jason okays, then run `apply`. Report back invoice numbers, amounts,
and QBO bill IDs.

## Hourly job

`com.jasonsecondbrain.airsensebills` runs `scan --days 3 --notify` hourly from
7:15am to 7:15pm. It texts Jason **only when something new was queued** — an
hourly all-clear would be noise. Log: `/tmp/jasonsecondbrain/airsensebills.log`.

**When Jason replies asking to file one**, that is the approval: set that entry's
`status` to `approved` in `pending-bills.json` and run `apply`. Approval is
per-invoice — "file it" refers to the invoice Ricky just named, not the whole
queue. If several are waiting and it is unclear which he means, ask.

The 3-day window is deliberate overlap: a missed run (asleep, offline) is picked
up by the next one, and the ledger makes re-seeing an invoice harmless.

## How duplicates are prevented

`filed-ledger.json` is the durable record — **separate from the queue on
purpose**. `pending-bills.json` is scratch and may be pruned, hand-edited, or
deleted; the ledger is truth about what is already in QuickBooks. Keyed on
`(branch, invoice number)`, because branches number invoices independently.

1. **Scan** skips anything the ledger knows. Deleting the entire queue and
   re-scanning still yields zero — verified.
2. **Apply re-checks the ledger at file time**, not just at scan time. An
   entry approved days ago but since entered by hand is blocked, even when
   fully mapped.
3. **Apply asks QuickBooks directly** for an existing bill with the same
   `DocNumber` on that vendor before creating. Best-effort — the query endpoint
   is throttled (below), so this is a second net, not the primary guard.
4. **Crash safety.** The ledger is marked `in_flight` and flushed *before* the
   create call. If the process dies mid-call, the next `apply` **refuses to run
   at all** and names the unconfirmed invoice, because we cannot tell whether
   QuickBooks accepted it. Ambiguous errors (timeout, dropped connection) stay
   `in_flight`; only definite rejections (4xx, validation faults) clear it.

A corrupt ledger **halts the run** rather than starting from empty — an empty
ledger would happily re-file everything.

Never hand-edit `filed-ledger.json` except to resolve an `in_flight` entry:
set it to `filed` if the bill exists in QBO, or delete it if it does not.

## Two traps this skill exists to avoid

**1. Statements are not invoices.** WinSupply sends `New Statement - <Branch>`
monthly summaries that re-list invoices *already billed*. Filing one as a bill
double-counts every line on it. Only `New Invoice - <Branch>` is queued; scan
prints the statement count so the exclusion stays visible.

**2. WinSupply re-sends invoices.** Invoice `334483-01` ($1,669.85) arrived twice
12 hours apart — same PDF, different Gmail message IDs. **Dedupe is keyed on
invoice number, never message ID.**

## QBO mapping (configured 2026-08-26)

| Branch (email subject) | QBO vendor | |
|---|---|---|
| Winsupply Alton IL Co. | `465` Alton Winnelson | derived from matching bill amounts |
| Edwardsville Winsupply Co. | `466` Edwardsville Win | **Jason's call** — see below |

Expense account `74` "Supplies" for both; it is what every WinSupply bill in the
books already uses. QuickBooks rejects vendor *names* (`Invalid Number :
Winsupply Alton IL Co.`), so these must stay numeric.

**Edwardsville was ambiguous and was decided by Jason, not derived.** Its
invoices had been scattered across three vendors: `258695`/`258293` under `92`
"WIN SUPPLY" (whose address is actually Alton, and which also holds Alton-range
invoices), `258696` under `466`, and older `25xxxx` numbers under `133` "WINN
Electric" (dormant since Mar 2026). Don't "fix" this back to `92` on the grounds
that it holds the two most recent ones.

**DocNumber format differs between systems.** QuickBooks stores `339025 01`
(space); the emails use `339025-01` (hyphen). `to_doc_number()` normalises.
This matters for correctness, not neatness — the QBO duplicate check queries
`DocNumber`, so before this was handled it never matched an existing bill and
that guard silently passed everything.

## Composio gotchas (all confirmed live)

- Gmail connections have **no aliases** — select by word_id.
  `gmail_stroil-boxcar` = jason@airsenseenvironmental.com. Re-derive with
  `composio connections list --toolkit gmail` then `GMAIL_GET_PROFILE`.
- **`GMAIL_FETCH_EMAILS` is broken** — returns `successful: true` with empty
  data on every account. Use `GMAIL_LIST_THREADS`.
- **`GMAIL_LIST_THREADS` returns 0 threads when `max_results` is small** (10/25)
  even for queries that match. Always request 100. A nonsense-sender control
  query does correctly return 0, so filtering works — a small-page zero is a
  false negative, not an empty mailbox.
- Large verbose responses spill to disk; follow `outputFilePath`.
- **QuickBooks reads are throttled, writes are not.** Every `/query` call
  (`QUICKBOOKS_QUERY_ENTITIES`, `QUICKBOOKS_QUERY_ACCOUNT`,
  `QUICKBOOKS_GET_CHANGED_ENTITIES`) returns 429 `ThrottleExceeded` — Composio's
  *shared* Builder App quota with Intuit, not an Air Sense problem; the
  connection is `ACTIVE`. `QUICKBOOKS_CREATE_BILL` reaches Intuit fine and
  returns real validation errors. So bills can be filed as soon as the IDs above
  are known — the throttle only blocks looking them up.

`apply` stops the whole run on a 429 rather than churning the queue.
