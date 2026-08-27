"""Durable record of every WinSupply invoice that must never be filed twice.

Separate from the working queue on purpose. `pending-bills.json` is scratch —
it gets pruned, edited by hand, and could be deleted; this file is append-only
truth about what is already in QuickBooks. If the queue is lost, the ledger
still blocks every invoice that has ever been filed or entered manually.

Keyed on (branch, invoice number). Branch is part of the key because WinSupply
branches number invoices independently, so the same number could in principle
be issued by two branches for two genuinely different bills.

States:
    preexisting  already in QBO by some other route (e.g. entered by hand)
    in_flight    a create call was started but not confirmed — see reconcile()
    filed        confirmed created by this skill, with the QBO bill id
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

LEDGER_FILE = Path(__file__).resolve().parent / "filed-ledger.json"

PREEXISTING = "preexisting"
IN_FLIGHT = "in_flight"
FILED = "filed"

# Any of these mean "do not file again".
BLOCKING = {PREEXISTING, IN_FLIGHT, FILED}


def key_for(branch: str | None, invoice_no: str | None) -> str:
    return f"{(branch or '?').strip()}|{(invoice_no or '?').strip()}"


def load() -> dict:
    if not LEDGER_FILE.exists():
        return {"entries": {}}
    try:
        data = json.loads(LEDGER_FILE.read_text())
    except json.JSONDecodeError:
        # Never silently start from empty — an unreadable ledger would let
        # every previously-filed invoice through as if it were new.
        raise RuntimeError(
            f"{LEDGER_FILE.name} is corrupt. Refusing to run: an empty ledger "
            f"would re-file invoices already in QuickBooks. Restore it from git."
        )
    data.setdefault("entries", {})
    return data


def save(data: dict) -> None:
    tmp = LEDGER_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
    tmp.replace(LEDGER_FILE)  # atomic: a crash mid-write can't truncate it


def status_of(data: dict, branch: str | None, invoice_no: str | None) -> str | None:
    entry = data["entries"].get(key_for(branch, invoice_no))
    return entry["status"] if entry else None


def is_blocked(data: dict, branch: str | None, invoice_no: str | None) -> bool:
    return status_of(data, branch, invoice_no) in BLOCKING


def record(
    data: dict,
    branch: str | None,
    invoice_no: str | None,
    status: str,
    *,
    qbo_bill_id: str | None = None,
    amount: str | None = None,
    note: str | None = None,
) -> None:
    entry = data["entries"].setdefault(key_for(branch, invoice_no), {})
    entry.update(
        {
            "branch": branch,
            "invoice_no": invoice_no,
            "status": status,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    if qbo_bill_id is not None:
        entry["qbo_bill_id"] = qbo_bill_id
    if amount is not None:
        entry["amount"] = amount
    if note:
        entry["note"] = note


def in_flight_entries(data: dict) -> list[dict]:
    return [e for e in data["entries"].values() if e["status"] == IN_FLIGHT]
