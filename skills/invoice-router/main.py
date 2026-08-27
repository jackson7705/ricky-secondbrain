"""
invoice-router orchestrator.

Daily flow:
  1. For each Google profile, list Primary-inbox emails since last scan.
  2. Classify each email → receipt? which business? vendor? amount? date?
  3. If confident: download PDF, upload to the right month folder, append a row
     to the expense tracker (Locafy only) with a HYPERLINK to the Drive file.
  4. If not confident: queue into pending-clarification.json for Jason to
     resolve. His answer flows into vendor-memory.json so we don't ask twice.

The skill is intentionally conservative — when in doubt, ask rather than
misfile a $500 invoice under "personal".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Find scripts dir so we can import the existing integrations. The skill's
# local config is `router_config.py` (not `config.py`) to avoid shadowing
# `scripts/config.py` when Python resolves imports.
_SKILL_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _SKILL_DIR.parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))
sys.path.insert(0, str(_SKILL_DIR))

from router_config import (  # noqa: E402
    ALWAYS_RECEIPT_SENDER_DOMAINS,
    CONFIDENCE_AUTOFILE_THRESHOLD,
    DEFAULT_LOOKBACK_HOURS,
    DEFAULT_REIMBURSED,
    EXPENSE_SHEET_ID,
    WONDERLY_SHEET_ID,
    LOCAFY_EXPENSES_FOLDER_ID,
    MONTH_FOLDERS,
    PENDING_CLARIFICATION_FILE,
    PERSONAL_VENDOR_HINTS,
    RECEIPT_SENDER_DOMAIN_HINTS,
    RECEIPT_SENDER_LOCAL_PREFIXES,
    RECEIPT_SUBJECT_KEYWORDS,
    SCAN_PROFILES,
    SHEET_TAB_BY_MONTH,
    STAGING_DIR,
    STATE_FILE,
    VENDOR_MEMORY_FILE,
    WONDERLY_EXPENSES_FOLDER_ID,
)


# ── Data classes ────────────────────────────────────────────────────────


@dataclass
class Candidate:
    """An email we think might be a receipt, with extracted info."""

    message_id: str
    thread_id: str
    profile: str
    subject: str
    sender: str
    sender_email: str
    received_at: datetime
    body: str
    attachments: list[Any] = field(default_factory=list)

    # Populated by classify()
    business: str = ""  # "locafy" | "wonderly" | "personal" | ""
    vendor: str = ""
    use: str = ""
    amount: float | None = None
    currency: str = "USD"
    confidence: float = 0.0
    reasons: list[str] = field(default_factory=list)


# ── State / memory I/O ──────────────────────────────────────────────────


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default
    except Exception as e:
        print(f"  [warn] couldn't parse {path.name}: {e} — using default")
        return default


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str))


def _load_state() -> dict[str, Any]:
    return _load_json(STATE_FILE, {"last_scanned_at": {}, "processed_message_ids": []})


def _load_vendor_memory() -> dict[str, Any]:
    return _load_json(VENDOR_MEMORY_FILE, {})


def _load_pending() -> list[dict[str, Any]]:
    return _load_json(PENDING_CLARIFICATION_FILE, [])


# ── Classification ──────────────────────────────────────────────────────


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _subject_hits(subject: str) -> int:
    low = subject.lower()
    return sum(1 for kw in RECEIPT_SUBJECT_KEYWORDS if kw in low)


def _has_sender_signal(sender_email: str, vendor_memory: dict[str, Any]) -> bool:
    """True if the sender looks like a billing/receipt mailer.

    Checks three sources of sender-level evidence:
      1. Known receipt domains (stripe.com, paypal.com, …)
      2. Billing-style subdomains (billing.x.com, receipts.y.com, …)
      3. Billing-style local-parts (billing@, invoices+tag@, ar@, …)
      4. Vendor-memory: we've classified this exact sender before
    """
    if not sender_email or "@" not in sender_email:
        return False
    local, _, domain = sender_email.lower().partition("@")
    # 1. Known always-receipt domains
    for known in ALWAYS_RECEIPT_SENDER_DOMAINS:
        if domain == known or domain.endswith("." + known):
            return True
    # 2. Billing-style subdomain hints
    for hint in RECEIPT_SENDER_DOMAIN_HINTS:
        if hint in domain:
            return True
    # 3. Local-part prefix match. Split on '+' and '-' so "invoices+tag" and
    # "billing-noreply" still hit on their leading token.
    first_token = re.split(r"[+\-.]", local, maxsplit=1)[0]
    if first_token in RECEIPT_SENDER_LOCAL_PREFIXES:
        return True
    # 4. Vendor memory — if we've confirmed this sender before, trust it.
    norm_sender = _normalize(sender_email)
    for key in vendor_memory:
        if key.startswith("_"):
            continue
        k = _normalize(key)
        if k and k in norm_sender:
            return True
    return False


def _extract_amount(text: str) -> float | None:
    """Best-effort amount extraction from body/subject. Picks the largest plausible
    USD-looking value since footers often show total > line items."""
    if not text:
        return None
    # Patterns: $1,234.56  |  USD 1234.56  |  1,234.56 USD  |  Total: $123
    pattern = r"(?:USD\s*|\$)\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?|[0-9]+\.[0-9]{2})"
    hits = re.findall(pattern, text, re.IGNORECASE)
    values: list[float] = []
    for h in hits:
        try:
            values.append(float(h.replace(",", "")))
        except ValueError:
            continue
    if not values:
        return None
    # Plausible invoice range — filter wild credit-card-number style matches.
    plausible = [v for v in values if 0.50 <= v <= 100_000]
    if not plausible:
        return None
    return max(plausible)


def _vendor_from_sender(sender_email: str, subject: str) -> str:
    """Best guess at vendor from the sending domain or the 'from' display name."""
    if sender_email and "@" in sender_email:
        domain = sender_email.split("@", 1)[1].lower()
        # Strip common email subdomains
        for prefix in ("mail.", "billing.", "receipts.", "no-reply.", "noreply.", "email."):
            if domain.startswith(prefix):
                domain = domain[len(prefix):]
                break
        base = domain.split(".")[0]
        if base and base not in ("gmail", "googlemail", "outlook", "hotmail"):
            return base
    # Fall back to first couple subject tokens
    tokens = re.split(r"[\s\-\|:,]+", subject)
    return tokens[0] if tokens else ""


def _lookup_vendor_memory(
    vendor: str, subject: str, sender_email: str, vmem: dict[str, Any]
) -> tuple[str, str, float] | None:
    """Return (business, use, confidence) if any memory entry matches."""
    haystacks = [
        _normalize(vendor),
        _normalize(sender_email),
        _normalize(subject),
    ]
    for key, info in vmem.items():
        if key.startswith("_"):
            continue
        k = _normalize(key)
        for h in haystacks:
            if k and k in h:
                return (info["business"], info.get("use", ""), float(info.get("confidence", 0.8)))
    return None


def classify(candidate: Candidate, vendor_memory: dict[str, Any]) -> None:
    """Populate candidate.business / vendor / use / amount / confidence in-place."""
    reasons: list[str] = []

    subject_hits = _subject_hits(candidate.subject)
    if subject_hits:
        reasons.append(f"subject has {subject_hits} receipt keyword(s)")

    candidate.amount = _extract_amount(candidate.body) or _extract_amount(candidate.subject)
    if candidate.amount:
        reasons.append(f"extracted amount ${candidate.amount:.2f}")

    candidate.vendor = _vendor_from_sender(candidate.sender_email, candidate.subject)

    # Vendor memory is the strongest signal.
    mem = _lookup_vendor_memory(candidate.vendor, candidate.subject, candidate.sender_email, vendor_memory)
    if mem:
        business, use, base_conf = mem
        candidate.business = business
        candidate.use = use
        candidate.confidence = base_conf
        reasons.append(f"vendor-memory match → {business}")
    else:
        # Heuristic fallback: personal-hint hits push toward "personal"
        low_sender = (candidate.sender_email or "").lower()
        low_subject = candidate.subject.lower()
        for hint in PERSONAL_VENDOR_HINTS:
            if hint in low_sender or hint in low_subject:
                candidate.business = "personal"
                candidate.confidence = 0.75
                reasons.append(f"personal-hint hit: {hint}")
                break

    # Confidence boost when we have all the signals
    if candidate.business and candidate.amount and subject_hits:
        candidate.confidence = min(1.0, candidate.confidence + 0.1)

    candidate.reasons = reasons


# ── Google API helpers (thin wrappers) ──────────────────────────────────


def _set_profile(profile: str) -> None:
    from integrations.auth import set_active_account

    set_active_account(profile)


def _list_candidate_emails(
    profile: str, after_hours: int, vendor_memory: dict[str, Any]
) -> list[Candidate]:
    """Pull recent Primary-inbox emails that look like they might be receipts.

    The Gmail query is intentionally broad (keyword OR over subject/body), so
    internal emails that merely *mention* "payment" or "invoice" come back too.
    After fetching, we drop any email with neither a subject signal nor a
    sender signal — i.e. body-only matches are discarded as false positives.
    """
    from integrations.gmail import list_emails

    _set_profile(profile)
    raw = list_emails(
        max_results=75,
        hours_ago=after_hours,
        query=(
            "in:inbox -category:promotions -category:social "
            "(receipt OR invoice OR payment OR \"order confirmation\" "
            "OR \"thanks for your payment\" OR subscription OR charged OR statement)"
        ),
    )
    out: list[Candidate] = []
    dropped_body_only = 0
    for e in raw:
        if e.sender_email and e.sender_email.lower() == "me":
            continue
        subject = e.subject or ""
        sender_email = e.sender_email or ""
        # Require either a subject signal or a sender signal. If the only
        # reason this email matched was a body-text keyword (e.g. a teammate
        # saying "I sent payment"), skip it.
        if _subject_hits(subject) == 0 and not _has_sender_signal(sender_email, vendor_memory):
            dropped_body_only += 1
            continue
        out.append(
            Candidate(
                message_id=e.id,
                thread_id=e.thread_id,
                profile=profile,
                subject=subject,
                sender=e.sender or "",
                sender_email=sender_email,
                received_at=e.date,
                body=(e.body or e.snippet or ""),
            )
        )
    if dropped_body_only:
        print(f"  [filter] dropped {dropped_body_only} body-only match(es) — no subject/sender signal")
    return out


def _ensure_month_folder(business: str, month_key: str) -> str:
    """Return the Drive folder ID for (business, YYYY-MM), creating if missing.

    New folders match Jason's naming convention ("April " with trailing space).
    """
    cached = MONTH_FOLDERS.get((business, month_key))
    if cached:
        return cached

    from integrations.auth import set_active_account
    from integrations.drive_api import get_drive_service
    from shared import with_retry

    set_active_account("growthpro")  # expense folders live in growthpro drive
    parent = LOCAFY_EXPENSES_FOLDER_ID if business == "locafy" else WONDERLY_EXPENSES_FOLDER_ID
    month_name = datetime.strptime(month_key, "%Y-%m").strftime("%B")
    # January had no trailing space, everything else does. Match Jason's convention
    # for any new month; a trailing space is harmless if wrong and easy to rename.
    display_name = month_name if month_name == "January" else f"{month_name} "

    service = get_drive_service()
    # Look for an existing folder before creating. Jason's folder names are
    # inconsistent about a trailing space ("July " but "August"), so we list the
    # parent and compare on a normalized name rather than querying an exact
    # string — an exact match would miss the real folder and create a duplicate.
    listed = with_retry(
        lambda: service.files()
        .list(
            q=(
                f"'{parent}' in parents and "
                f"mimeType='application/vnd.google-apps.folder' and trashed=false"
            ),
            fields="files(id,name,createdTime)",
            pageSize=200,
        )
        .execute()
    )
    target = month_name.casefold()
    matches = [f for f in listed.get("files", []) if f["name"].strip().casefold() == target]
    if matches:
        # Oldest wins — if duplicates already exist, the first one created is the
        # one with the history in it. Surface the rest so they can be merged.
        matches.sort(key=lambda f: f.get("createdTime", ""))
        if len(matches) > 1:
            dupes = ", ".join(f"{f['name']!r} ({f['id']})" for f in matches[1:])
            print(
                f"  [warn] {business}/{month_name}: {len(matches)} folders match — "
                f"using oldest {matches[0]['id']}; duplicates: {dupes}"
            )
        return matches[0]["id"]

    # Create new
    body = {
        "name": display_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent],
    }
    created = with_retry(
        lambda: service.files().create(body=body, fields="id").execute()
    )
    print(f"  [info] created month folder {business}/{display_name!r} → {created['id']}")
    return created["id"]


def _profile_error(profile: str, exc: Exception) -> str:
    """Describe a per-profile failure, with a fix when the cause is known.

    A revoked or deleted Google account fails the same way on every run, so say
    what to do about it instead of reprinting the raw OAuth error each time.
    """
    msg = str(exc)
    if "invalid_grant" not in msg:
        return f"  [error] {profile}: {msg}"
    if "deleted" in msg.lower():
        return (
            f"  [error] {profile}: Google account no longer exists — re-auth cannot fix this. "
            f"Drop '{profile}' from SCAN_PROFILES in router_config.py, or point it at a live account."
        )
    return (
        f"  [error] {profile}: Google token revoked or expired. Re-auth with "
        f"`cd .claude/scripts && uv run python setup_auth.py --account {profile}`."
    )


def _download_attachment_or_body(candidate: Candidate, out_dir: Path) -> Path | None:
    """Save the PDF attachment to disk. Returns local path, or None if no PDF."""
    from integrations.auth import set_active_account
    from integrations.gmail import download_attachment, list_attachments

    set_active_account(candidate.profile)
    atts = list_attachments(candidate.message_id)
    pdf = next(
        (a for a in atts if a.mime_type == "application/pdf" or a.filename.lower().endswith(".pdf")),
        None,
    )
    if not pdf:
        return None

    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", pdf.filename) or f"{candidate.message_id}.pdf"
    out_path = out_dir / f"{candidate.received_at.strftime('%Y%m%d')}_{safe_name}"
    download_attachment(candidate.message_id, pdf.id, out_path)
    return out_path


def _upload_to_month_folder(local_path: Path, folder_id: str, display_name: str) -> dict[str, str]:
    """Upload a PDF into the given Drive folder. Returns {id, webViewLink}."""
    from integrations.auth import set_active_account
    from integrations.drive_api import upload_file

    set_active_account("growthpro")  # expense storage always lives in growthpro drive
    result = upload_file(local_path, folder_id, display_name=display_name)
    return {"id": result.id, "url": result.url}


def _append_to_expense_sheet(
    business: str,
    month_key: str,
    vendor: str,
    use: str,
    amount: float,
    drive_url: str,
) -> None:
    """Write one row to the correct monthly tab of the business's Expense Tracker.

    Locafy and Wonderly each have their own sheet with identical column layouts
    (Website, Use, Cost, Reimbursed, Link to Invoice). The tab has template
    placeholder rows (Reimbursed=FALSE, Link="Invoice") below real data AND a
    TOTAL row at the bottom — Sheets' native `append` either skips past
    templates or overwrites the TOTAL. Instead, read column A, find the last
    row where the vendor cell has real content BEFORE the TOTAL row, and
    write to the row after that.
    """
    from integrations.auth import set_active_account
    from integrations.sheets_api import read_spreadsheet, write_spreadsheet

    if business == "locafy":
        spreadsheet_id: str | None = EXPENSE_SHEET_ID
    elif business == "wonderly":
        spreadsheet_id = WONDERLY_SHEET_ID
    else:
        raise ValueError(f"No expense sheet configured for business={business!r}")
    if not spreadsheet_id:
        print(f"  [skip] no sheet id for {business} — uploaded to Drive only")
        return

    set_active_account("growthpro")
    tab = SHEET_TAB_BY_MONTH.get(month_key)
    if not tab:
        raise ValueError(f"No expense sheet tab configured for {month_key}")

    # Read column A to find the next real-data row.
    sheet = read_spreadsheet(spreadsheet_id=spreadsheet_id, range_notation=f"'{tab}'!A1:A1000")
    values = getattr(sheet, "values", None) or []

    next_row = 2  # row 1 is the header
    for idx, row in enumerate(values, start=1):
        cell = (row[0] if row else "").strip()
        # Stop at TOTAL row so we don't pollute below it.
        if cell.upper().startswith("TOTAL"):
            break
        if cell:
            next_row = idx + 1  # the row after the last vendor cell

    hyperlink = f'=HYPERLINK("{drive_url}", "Invoice")'
    row_values = [[vendor, use, f"${amount:,.2f}", DEFAULT_REIMBURSED, hyperlink]]
    write_spreadsheet(
        spreadsheet_id=spreadsheet_id,
        range_notation=f"'{tab}'!A{next_row}:E{next_row}",
        values=row_values,
        input_option="USER_ENTERED",  # honors the HYPERLINK formula
    )


# ── Main pass ───────────────────────────────────────────────────────────


def propose_candidate(
    c: Candidate,
    state: dict[str, Any],
    vendor_memory: dict[str, Any],
    pending: list[dict[str, Any]],
) -> str:
    """Classify an email and queue a proposal for Jason's approval.

    Per Jason's rule (2026-04-19): no uploads happen without his explicit
    confirmation. We ALWAYS stage — this function never touches Drive/Sheets.
    """
    if c.message_id in state.get("processed_message_ids", []):
        return "skipped"
    # Avoid duplicate pending entries across runs
    if any(p["message_id"] == c.message_id for p in pending):
        return "queued-already"

    classify(c, vendor_memory)

    proposed_month = (c.received_at or datetime.now(timezone.utc)).strftime("%Y-%m")
    proposed_folder_name = None
    if c.business in ("locafy", "wonderly"):
        # Human-readable folder suggestion for Jason
        month_name = datetime.strptime(proposed_month, "%Y-%m").strftime("%B")
        proposed_folder_name = (
            f"{'Locafy' if c.business == 'locafy' else 'Wonderly'} Expenses / {month_name}"
        )

    pending.append(
        {
            "message_id": c.message_id,
            "thread_id": c.thread_id,
            "profile": c.profile,
            "subject": c.subject,
            "sender_email": c.sender_email,
            "received_at": c.received_at.isoformat() if c.received_at else None,
            "guess_vendor": c.vendor,
            "guess_business": c.business or "unknown",
            "guess_use": c.use,
            "guess_amount": c.amount,
            "proposed_month": proposed_month,
            "proposed_folder": proposed_folder_name,
            "confidence": round(c.confidence, 2),
            "reasons": c.reasons,
            "queued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": "awaiting_confirmation",
        }
    )
    return "queued"


def apply_confirmed(
    entry: dict[str, Any],
    state: dict[str, Any],
    vendor_memory: dict[str, Any],
) -> str:
    """Apply an approved pending entry — upload + sheet-log.

    `entry` must carry a `status` of "approved" and a final `business` ("locafy",
    "wonderly", or "personal"). Jason can override `vendor`, `use`, `amount`,
    and `proposed_month` before approval.
    """
    if entry.get("status") != "approved":
        return "not-approved"
    if entry["message_id"] in state.get("processed_message_ids", []):
        return "already-applied"

    business = entry.get("business") or entry.get("guess_business")
    if business == "personal":
        state.setdefault("processed_message_ids", []).append(entry["message_id"])
        return "personal-skipped"
    if business not in ("locafy", "wonderly"):
        return f"unknown-business:{business}"

    # Rebuild a minimal Candidate so we can reuse download helpers.
    c = Candidate(
        message_id=entry["message_id"],
        thread_id=entry.get("thread_id", ""),
        profile=entry["profile"],
        subject=entry.get("subject", ""),
        sender=entry.get("sender", entry.get("sender_email", "")),
        sender_email=entry.get("sender_email", ""),
        received_at=datetime.fromisoformat(entry["received_at"]) if entry.get("received_at") else datetime.now(timezone.utc),
        body="",
    )

    pdf_path = _download_attachment_or_body(c, STAGING_DIR)
    if not pdf_path:
        return "no-pdf"

    vendor = entry.get("vendor") or entry.get("guess_vendor") or "vendor"
    use = entry.get("use") or entry.get("guess_use") or ""
    amount = float(entry.get("amount") or entry.get("guess_amount") or 0.0)
    month_key = entry.get("proposed_month") or c.received_at.strftime("%Y-%m")

    folder_id = _ensure_month_folder(business, month_key)
    display_name = f"{c.received_at.strftime('%Y-%m-%d')} — {vendor} — ${amount:.2f}.pdf"
    uploaded = _upload_to_month_folder(pdf_path, folder_id, display_name)

    if business in ("locafy", "wonderly"):
        _append_to_expense_sheet(
            business=business,
            month_key=month_key,
            vendor=vendor.title() if vendor else "Vendor",
            use=use or "(confirmed)",
            amount=amount,
            drive_url=uploaded["url"],
        )

    # Remember the vendor → business mapping so we don't ask again.
    key = (vendor or "").strip().lower()
    if key and key not in vendor_memory:
        vendor_memory[key] = {
            "business": business,
            "use": use,
            "confidence": 0.9,
            "learned_from": entry["message_id"],
        }

    state.setdefault("processed_message_ids", []).append(entry["message_id"])
    entry["status"] = "applied"
    entry["applied_drive_id"] = uploaded["id"]
    entry["applied_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(
        f"  [applied] {business}/{month_key} — {vendor} ${amount:.2f} "
        f"→ Drive {uploaded['id']}"
    )
    return "applied"


def run_scan(lookback_hours: int) -> int:
    """Scan inboxes and queue proposals. No uploads. No sheet writes."""
    state = _load_state()
    vendor_memory = _load_vendor_memory()
    pending = _load_pending()

    now = datetime.now(timezone.utc)
    totals: dict[str, int] = {}

    for profile in SCAN_PROFILES:
        print(f"\n== Scanning {profile} ==")
        try:
            candidates = _list_candidate_emails(profile, lookback_hours, vendor_memory)
        except Exception as e:
            print(_profile_error(profile, e))
            continue
        print(f"  {len(candidates)} candidate emails")

        for c in candidates:
            try:
                status = propose_candidate(c, state, vendor_memory, pending)
            except Exception as e:
                status = "error"
                print(f"  [error] {c.subject[:60]!r}: {e}")
            totals[status] = totals.get(status, 0) + 1

        state.setdefault("last_scanned_at", {})[profile] = now.isoformat(timespec="seconds")

    _save_json(STATE_FILE, state)
    _save_json(PENDING_CLARIFICATION_FILE, pending)

    awaiting = [p for p in pending if p.get("status") == "awaiting_confirmation"]
    print(
        "\nScan complete. "
        + ", ".join(f"{k}={v}" for k, v in totals.items())
        + f"  (awaiting approval: {len(awaiting)}, total pending: {len(pending)})"
    )
    if awaiting:
        print("\nNext step: review pending-clarification.json, set each entry's")
        print("status to 'approved' (plus any corrections to business/vendor/amount),")
        print("then run: uv run python main.py apply")
    return 0


def run_apply() -> int:
    """Apply any pending entries whose status is 'approved'."""
    state = _load_state()
    vendor_memory = _load_vendor_memory()
    pending = _load_pending()

    totals: dict[str, int] = {}
    for entry in pending:
        if entry.get("status") != "approved":
            continue
        try:
            result = apply_confirmed(entry, state, vendor_memory)
        except Exception as e:
            result = "error"
            print(f"  [error] applying {entry.get('message_id')}: {e}")
        totals[result] = totals.get(result, 0) + 1

    _save_json(STATE_FILE, state)
    _save_json(PENDING_CLARIFICATION_FILE, pending)
    _save_json(VENDOR_MEMORY_FILE, vendor_memory)

    print("\nApply complete. " + ", ".join(f"{k}={v}" for k, v in totals.items()))
    return 0


def _render_body_to_pdf(c: "Candidate", out_dir: Path) -> Path | None:
    """Render an email body to a PDF — fallback for HTML-only receipts (e.g.
    Mailchimp) that arrive with no PDF attachment, so there's still a filed
    artifact in Drive."""
    import html as _html
    import subprocess

    out_dir.mkdir(parents=True, exist_ok=True)
    body = c.body or ""
    looks_html = any(t in body.lower() for t in ("<html", "<body", "<table", "<div"))
    if looks_html:
        doc = body
    else:
        doc = (
            "<html><body style='font-family:-apple-system,sans-serif;padding:28px;color:#222'>"
            f"<h3>{_html.escape(c.subject)}</h3>"
            f"<div style='color:#666;font-size:12px'>{_html.escape(c.sender_email)} · "
            f"{c.received_at.strftime('%Y-%m-%d')}</div><hr>"
            f"<pre style='white-space:pre-wrap;font-family:-apple-system,sans-serif'>{_html.escape(body)}</pre>"
            "</body></html>"
        )
    html_path = out_dir / f"{c.message_id}.html"
    html_path.write_text(doc, encoding="utf-8")
    pdf_path = out_dir / f"{c.received_at.strftime('%Y%m%d')}_{c.message_id}.pdf"
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    try:
        subprocess.run(
            [chrome, "--headless", "--disable-gpu", f"--print-to-pdf={pdf_path}", str(html_path)],
            check=True, capture_output=True, timeout=60,
        )
        return pdf_path if pdf_path.exists() and pdf_path.stat().st_size > 0 else None
    except Exception as exc:
        print(f"  [warn] body->pdf render failed: {exc}")
        return None


def file_now(vendor: str, business: str, month_key: str, account: str | None = None) -> int:
    """One-shot filing for Jason's "[Vendor] is [Business] [Month]" shorthand.

    Finds the vendor's most recent receipt across all inboxes (or a named one),
    downloads the PDF, extracts the amount from the email body, uploads to the
    right Drive month folder, and logs the expense row — no queue, no approval
    prompt. This is the path for fresh receipts that aren't in the scan queue yet
    (which is most of Jason's same-day requests). Filing is the explicit ask, so
    it does not re-prompt; it reports the amount so a wrong one is easy to catch.
    """
    from integrations.gmail import list_emails

    state = _load_state()
    vendor_memory = _load_vendor_memory()
    pending = _load_pending()
    vlow = vendor.strip().lower()
    profiles = [account] if account else SCAN_PROFILES

    found: tuple[str, Any] | None = None
    for profile in profiles:
        _set_profile(profile)
        try:
            emails = list_emails(
                max_results=10, hours_ago=24 * 120,
                query=f'in:inbox (receipt OR invoice OR payment) {vendor}',
            )
        except Exception as e:
            print(_profile_error(profile, e))
            continue
        cands = [
            e for e in emails
            if vlow in (e.sender_email or "").lower() or vlow in (e.subject or "").lower()
        ]
        # Drop the user's own "Email Has Changed" / forwarded auto-replies — they
        # share the receipt's subject but carry no PDF and would mis-file.
        cands = [
            e for e in cands
            if "email has changed" not in (e.subject or "").lower()
            and not (e.subject or "").lower().startswith(("fwd:",))
        ]
        # Prefer a real billing sender (stripe/vendor) over a subject-only match,
        # then most recent.
        cands.sort(
            key=lambda e: (
                _has_sender_signal(e.sender_email or "", vendor_memory)
                or vlow in (e.sender_email or "").lower(),
                e.date,
            ),
            reverse=True,
        )
        if cands:
            found = (profile, cands[0])
            break

    if not found:
        print(f"  [not-found] no recent {vendor!r} receipt in {profiles}")
        return 1
    profile, e = found
    if e.id in state.get("processed_message_ids", []):
        print(f"  [already-filed] {e.subject!r} was already processed — skipping")
        return 0

    # Fetch the FULL message body — list_emails returns only a truncated snippet,
    # which made amounts like "$39.00" come back empty (filed as $0.00).
    from integrations.gmail import get_email_details, get_gmail_service
    full_body = ""
    try:
        det = get_email_details(get_gmail_service(), e.id, include_body=True)
        full_body = (det.body if det else "") or ""
    except Exception as exc:
        print(f"  [warn] full-body fetch failed ({exc}); falling back to snippet")
    full_body = full_body or e.body or e.snippet or ""

    c = Candidate(
        message_id=e.id, thread_id=e.thread_id, profile=profile,
        subject=e.subject or "", sender=e.sender or "", sender_email=e.sender_email or "",
        received_at=e.date, body=full_body,
    )
    amount = _extract_amount(c.body) or _extract_amount(c.subject) or 0.0
    mem = vendor_memory.get(vlow, {})
    use = mem.get("use", "")

    pdf_path = _download_attachment_or_body(c, STAGING_DIR)
    if not pdf_path:
        # HTML-only receipt (e.g. Mailchimp) — render the email body to a PDF.
        pdf_path = _render_body_to_pdf(c, STAGING_DIR)
    if not pdf_path:
        print(f"  [no-pdf] {e.subject!r} has no PDF and body render failed — file manually")
        return 1

    folder_id = _ensure_month_folder(business, month_key)
    display_name = f"{c.received_at.strftime('%Y-%m-%d')} — {vlow} — ${amount:.2f}.pdf"
    uploaded = _upload_to_month_folder(pdf_path, folder_id, display_name)
    if business in ("locafy", "wonderly"):
        _append_to_expense_sheet(business, month_key, vendor.title(), use or "(filed)", amount, uploaded["url"])

    if vlow and vlow not in vendor_memory:
        vendor_memory[vlow] = {"business": business, "use": use, "confidence": 0.9, "learned_from": e.id}
        _save_json(VENDOR_MEMORY_FILE, vendor_memory)
    state.setdefault("processed_message_ids", []).append(e.id)
    pending.append({
        "message_id": e.id, "thread_id": e.thread_id, "profile": profile,
        "subject": e.subject or "", "sender_email": e.sender_email or "",
        "received_at": c.received_at.isoformat(), "guess_vendor": vlow,
        "guess_business": business, "guess_use": use, "guess_amount": amount,
        "proposed_month": month_key, "proposed_folder": f"{business.title()} Expenses / {month_key}",
        "confidence": 1.0, "reasons": ["file-now: direct one-shot filing"],
        "queued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "applied", "vendor": vendor.title(), "business": business,
        "use": use, "amount": amount, "applied_drive_id": uploaded["id"],
        "applied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    _save_json(STATE_FILE, state)
    _save_json(PENDING_CLARIFICATION_FILE, pending)
    print(f"  [filed] {business}/{month_key} — {vendor} ${amount:.2f} → {uploaded['url']}")
    if amount == 0.0:
        print("  [warn] amount not found in email body — verify against the PDF before trusting the sheet")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Invoice router. `scan` queues proposals, `apply` uploads approved ones, "
            "`file-now` files a single vendor's latest receipt directly. "
            "scan/apply never write without approval; file-now is the explicit one-shot path."
        )
    )
    sub = parser.add_subparsers(dest="cmd")

    scan = sub.add_parser("scan", help="Sweep inboxes and queue proposals (read-only).")
    scan.add_argument(
        "--hours",
        type=int,
        default=DEFAULT_LOOKBACK_HOURS,
        help=f"Lookback window in hours (default {DEFAULT_LOOKBACK_HOURS})",
    )

    sub.add_parser("apply", help="Upload + sheet-log all pending entries marked 'approved'.")

    fn = sub.add_parser("file-now", help="Find a vendor's latest receipt and file it directly (no queue).")
    fn.add_argument("--vendor", required=True, help="Vendor name, e.g. 'vercel'")
    fn.add_argument("--business", required=True, help="locafy | wonderly")
    fn.add_argument("--month", required=True, help="YYYY-MM, e.g. 2026-06")
    fn.add_argument("--account", default=None, help="Limit to one inbox profile (growthpro|locafy|wonderly)")

    args = parser.parse_args()
    if args.cmd == "apply":
        return run_apply()
    if args.cmd == "file-now":
        return file_now(args.vendor, args.business, args.month, args.account)
    # default to scan
    hours = getattr(args, "hours", DEFAULT_LOOKBACK_HOURS)
    return run_scan(hours)


if __name__ == "__main__":
    raise SystemExit(main())
