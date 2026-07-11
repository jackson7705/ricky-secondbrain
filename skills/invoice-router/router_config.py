"""Configuration for invoice-router.

Everything that might change over time lives here so main.py stays focused
on orchestration. Folder IDs were confirmed live against the growthpro
Google Drive on 2026-04-19.
"""

from __future__ import annotations

from pathlib import Path

# ── Drive layout ────────────────────────────────────────────────────────

# Top-level expense folders (each contains monthly subfolders).
LOCAFY_EXPENSES_FOLDER_ID = "133pCig8B41OajcYN3vHZnR_tovKsYz-X"
WONDERLY_EXPENSES_FOLDER_ID = "1QwmXXdNSSAPM2_cSupUze3xym9PP6IM2"

# Month-subfolder lookup for 2026. Keyed by (business, yyyy-mm).
# Folder names in Drive have a trailing space on months after January —
# that's how Jason created them, we just match his convention when creating
# new ones. The IDs below are the ones that already exist; missing months
# get auto-created in main.py.
MONTH_FOLDERS: dict[tuple[str, str], str] = {
    ("locafy", "2026-01"): "1cJ21tiZMA3f5g9o7O8d4o-H9K3uL-Y4w",
    ("locafy", "2026-02"): "1sYtBsm6WgA7K1djE3WPn0CBcg-6fKliB",
    ("locafy", "2026-03"): "1nL1J-PCkramtR7CwBSZPoGT4POqVgcnG",
    ("locafy", "2026-04"): "1H3XMpdOf3r1YO6p8o5I3iZsSUh5o2FNJ",
    ("locafy", "2026-05"): "1wZSKsAuxwSWtqHn4wf4nyoyVvBghPVQX",
    ("locafy", "2026-06"): "1i10V4iAh913YH-Va38hqaJAEMu-HH4jL",
    ("locafy", "2026-07"): "1alUe9U4OYoi7Don2e52eX8bl2tRNVSDD",
    ("wonderly", "2026-04"): "1GlMitPnkEW3fDl8OnpAlNK0WKKInUdwW",
    ("wonderly", "2026-05"): "1ttFmnKuXVTg2SQ4B7U0jzjX95a0H9y0I",
}

# ── Expense Tracker sheet (Locafy) ───────────────────────────────────────

# "Expense Tracker" — lives inside Locafy Expenses folder. One tab per month.
# Columns A–E: Website | Use | Cost | Reimbursed | Link to Invoice (HYPERLINK).
EXPENSE_SHEET_ID = "1Mi0p1_ZYsDVehS2sK95UB0FiPTGyphqvpZWrvzcJK8Q"

# Tab name per month. Jason named them with trailing spaces; match exactly.
SHEET_TAB_BY_MONTH: dict[str, str] = {
    "2026-01": "January ",
    "2026-02": "February ",
    "2026-03": "March",
    "2026-04": "April",
    "2026-05": "May",
    "2026-06": "June",
    "2026-07": "July",
}

# How the sheet wants rows structured (what goes in each column).
SHEET_COLUMNS = ["Website", "Use", "Cost", "Reimbursed", "Link to Invoice"]

# Reimbursed default for auto-filed rows. Jason flips to TRUE manually once
# the partner / Locafy reimburses — we never touch this column after write.
DEFAULT_REIMBURSED = "FALSE"

# Wonderly expense tracker (created 2026-04-23). Same column layout as Locafy's.
# Jason asked for parity with Locafy, so Wonderly receipts now sheet-log too.
WONDERLY_SHEET_ID: str | None = "1itXSrN7CSjEXGM-ZC9XBhnxOaxY43weR-8pEbvFj7O8"

# ── Scan parameters ─────────────────────────────────────────────────────

# Which Google profiles to sweep. All three accounts get scanned so we don't
# miss a receipt that landed in Locafy-only mail.
SCAN_PROFILES = ["growthpro", "locafy", "wonderly"]

# Lookback window on first run (default). Subsequent runs use state.json
# `last_scanned_at` to pick up where we left off.
DEFAULT_LOOKBACK_HOURS = 48

# Classification confidence threshold. Below this, the email goes to the
# clarification queue instead of being auto-filed.
CONFIDENCE_AUTOFILE_THRESHOLD = 0.8

# ── Local paths ─────────────────────────────────────────────────────────

SKILL_DIR = Path(__file__).resolve().parent
VENDOR_MEMORY_FILE = SKILL_DIR / "vendor-memory.json"
PENDING_CLARIFICATION_FILE = SKILL_DIR / "pending-clarification.json"
STATE_FILE = SKILL_DIR / "state.json"
STAGING_DIR = SKILL_DIR / "staging"  # temp dir for downloaded PDFs pre-upload

# ── Classification heuristics ───────────────────────────────────────────

# Subject-line tokens that strongly suggest a receipt. Hit-count is factored
# into confidence: more hits = higher confidence.
RECEIPT_SUBJECT_KEYWORDS = [
    "receipt",
    "invoice",
    "payment",
    "thank you for your order",
    "order confirmation",
    "your subscription",
    "has been processed",
    "payment received",
    "payment confirmed",
    "purchase confirmation",
    "statement",
]

# Senders that are always receipts (domain match). Extend as patterns emerge.
ALWAYS_RECEIPT_SENDER_DOMAINS = [
    "stripe.com",
    "paypal.com",
    "square.com",
    "intuit.com",
]

# Local-part prefixes on the sender that imply a billing/receipt sender
# (e.g. "billing@acme.com", "invoices+abc123@stripe.com"). Matched as prefix
# on the local-part so "billing-noreply" and "invoices+tag" both hit.
RECEIPT_SENDER_LOCAL_PREFIXES = [
    "billing",
    "invoice",
    "invoices",
    "invoicing",
    "receipt",
    "receipts",
    "payment",
    "payments",
    "accounts",
    "accounting",
    "bookkeeping",
    "ar",
    "ap",
]

# Subdomains that strongly imply a transactional/billing mail stream
# (e.g. "billing.intuit.com", "receipts.squareup.com"). Matched as a
# substring against the full domain.
RECEIPT_SENDER_DOMAIN_HINTS = [
    "billing.",
    "invoice.",
    "invoices.",
    "receipts.",
    "receipt.",
    "payments.",
    "accounting.",
]

# Vendors we never want in the expense tracker even if they're receipts —
# personal purchases. Logged to state but not uploaded or sheet-logged.
PERSONAL_VENDOR_HINTS = [
    "grubhub",
    "doordash",
    "uber eats",
    "ubereats",
    "instacart",
    "ace hardware",
    "amazon",  # most Amazon is personal for Jason; override in vendor-memory if needed
]
