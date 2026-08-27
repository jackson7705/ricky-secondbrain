"""Configuration for airsense-bills.

Everything that might change over time lives here so main.py stays focused on
orchestration. Composio account selectors and the WinSupply email format were
confirmed live against jason@airsenseenvironmental.com on 2026-08-22.
"""

from __future__ import annotations

from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent

# ── Composio access ─────────────────────────────────────────────────────

# Composio's Gmail connections have no aliases, so accounts are selected by
# their generated word_id. Re-derive with:
#   composio connections list --toolkit gmail
#   composio execute GMAIL_GET_PROFILE --account <id> -d '{"user_id":"me"}'
AIRSENSE_GMAIL_ACCOUNT = "gmail_stroil-boxcar"  # jason@airsenseenvironmental.com

# QuickBooks company 9130357561108566. Only one connection exists, so the
# --account flag is unnecessary, but pin it so a second link can't silently
# redirect bills into the wrong company's books.
QUICKBOOKS_ACCOUNT = "quickbooks_snock-sherry"

# GMAIL_FETCH_EMAILS reports success but returns empty data on every account —
# it's broken. GMAIL_LIST_THREADS works. Separately, LIST_THREADS returns zero
# threads when max_results is small (10/25) even for queries that do match, so
# always ask for a large page.
GMAIL_LIST_TOOL = "GMAIL_LIST_THREADS"
GMAIL_PAGE_SIZE = 100

# ── What counts as an invoice ───────────────────────────────────────────

VENDOR_SENDER = "noreply@winsupplyinc.com"
GMAIL_QUERY = f"from:{VENDOR_SENDER}"

# Subject prefixes. WinSupply also sends "New Statement - <Branch>" monthly
# summaries that re-list invoices ALREADY billed — filing those as bills
# double-counts every line, so they are excluded explicitly rather than by
# omission, and counted so the exclusion stays visible in scan output.
INVOICE_SUBJECT_PREFIX = "New Invoice - "
STATEMENT_SUBJECT_PREFIX = "New Statement - "

# Branch name (from the subject) → QuickBooks vendor id. WinSupply bills from
# per-branch entities that are separate vendors in QBO. apply refuses to post an
# unmapped branch rather than guessing — QBO rejects names outright, so these
# must be numeric ids.
#
# Derived 2026-08-26 by matching existing bills back to the invoice emails:
#   339025/338915/338793 → vendor 465, amounts match the emails exactly.
#
# Edwardsville needed a human call: historically its invoices were scattered
# across three vendors — 258695/258293 under 92 "WIN SUPPLY" (whose address is
# actually Alton), 258696 under 466, and older 25xxxx numbers under 133 "WINN
# Electric" (dormant since Mar 2026). Jason chose 466 on 2026-08-26. Do not
# "correct" this back to 92 just because 92 holds the two most recent ones.
BRANCH_TO_QBO_VENDOR: dict[str, str | None] = {
    "Winsupply Alton IL Co.": "465",        # Alton Winnelson
    "Edwardsville Winsupply Co.": "466",    # Edwardsville Win
}

# Expense account bills post to. Account 74 "Supplies" is what every WinSupply
# bill in the books uses, across both branches.
DEFAULT_EXPENSE_ACCOUNT: str | None = "74"  # Supplies

# QuickBooks stores these invoice numbers with a SPACE ("339025 01"), while the
# emails use a hyphen ("339025-01"). The duplicate check queries DocNumber, so
# without normalising, it would never match an existing bill and the QBO-side
# guard would silently pass everything.
def to_doc_number(invoice_no: str | None) -> str:
    return (invoice_no or "").replace("-", " ")

# ── Files ───────────────────────────────────────────────────────────────

PENDING_FILE = SKILL_DIR / "pending-bills.json"
STATE_FILE = SKILL_DIR / "state.json"

# Default lookback for a scan. WinSupply invoices arrive daily on weekdays.
DEFAULT_LOOKBACK_DAYS = 14
