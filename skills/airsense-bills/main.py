"""airsense-bills — WinSupply invoices (Air Sense inbox) → QuickBooks bills.

Two-step flow, same shape as invoice-router:

    scan     read-only sweep of the Air Sense inbox; queues proposals
    list     show what's queued
    apply    create bills in QBO for entries marked 'approved' ONLY

Nothing is written to QuickBooks without an explicit 'approved' status.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bills_config import (  # noqa: E402
    AIRSENSE_GMAIL_ACCOUNT,
    BRANCH_TO_QBO_VENDOR,
    DEFAULT_EXPENSE_ACCOUNT,
    DEFAULT_LOOKBACK_DAYS,
    GMAIL_LIST_TOOL,
    GMAIL_PAGE_SIZE,
    GMAIL_QUERY,
    INVOICE_SUBJECT_PREFIX,
    PENDING_FILE,
    QUICKBOOKS_ACCOUNT,
    STATE_FILE,
    STATEMENT_SUBJECT_PREFIX,
    VENDOR_SENDER,
    to_doc_number,
)
import ledger  # noqa: E402
from win_parser import parse_message  # noqa: E402


# ── Composio plumbing ───────────────────────────────────────────────────


def _composio(tool: str, payload: dict, account: str | None = None) -> dict:
    """Run one Composio tool call and return its parsed result.

    Large responses get spilled to a file by the CLI, in which case the JSON
    carries `outputFilePath` instead of `data` — follow it transparently so
    callers never have to care which shape came back.
    """
    cmd = ["composio", "execute", tool]
    if account:
        cmd += ["--account", account]
    cmd += ["-d", json.dumps(payload)]

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    raw = proc.stdout.strip()
    start = raw.find("{")
    if start < 0:
        raise RuntimeError(f"{tool}: no JSON in response — {raw[:200]}")
    result = json.loads(raw[start:])

    if not result.get("successful"):
        data = result.get("data") or {}
        status = data.get("status_code")
        err = str(result.get("error") or data.get("http_error") or "")[:300]
        if status == 429:
            raise ThrottledError(
                f"{tool}: QuickBooks returned 429. This is Composio's shared "
                f"Builder App quota with Intuit, not an Air Sense problem — the "
                f"connection itself is ACTIVE. Bills stay queued until it clears."
            )
        raise RuntimeError(f"{tool} failed (status {status}): {err}")

    path = result.get("outputFilePath")
    if path and Path(path).exists():
        return json.load(open(path))
    return result.get("data") or {}


class ThrottledError(RuntimeError):
    """QuickBooks refused the call with a 429."""


def _find_threads(obj: Any) -> list[dict]:
    """Pull the threads list out of a response whose nesting varies."""
    if isinstance(obj, dict):
        if "threads" in obj:
            return obj["threads"] or []
        for value in obj.values():
            found = _find_threads(value)
            if found:
                return found
    return []


# ── State ───────────────────────────────────────────────────────────────


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def _save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2))


# ── scan ────────────────────────────────────────────────────────────────


def cmd_scan(args: argparse.Namespace) -> None:
    pending: list[dict] = _load_json(PENDING_FILE, [])
    state: dict = _load_json(STATE_FILE, {})

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    query = f"{GMAIL_QUERY} after:{since.strftime('%Y/%m/%d')}"
    print(f"== Scanning Air Sense inbox ({args.days}d) ==")
    print(f"   query: {query}")

    raw = _composio(
        GMAIL_LIST_TOOL,
        {"query": query, "max_results": GMAIL_PAGE_SIZE, "verbose": True},
        account=AIRSENSE_GMAIL_ACCOUNT,
    )
    threads = _find_threads(raw)

    # Two independent dedupe layers, both keyed on (branch, invoice number) and
    # never on message id — WinSupply re-sends the same invoice (confirmed:
    # 334483-01 arrived twice, 12h apart, same PDF, different message ids).
    #
    #   ledger  durable, survives the queue being deleted or hand-edited
    #   queued  this scan + whatever is already waiting
    book = ledger.load()
    queued_keys = {ledger.key_for(e.get("branch"), e.get("invoice_no")) for e in pending}

    queued = statements = resends = already = skipped = 0
    for thread in threads:
        for msg in thread.get("messages") or []:
            rec = parse_message(msg)

            if rec["subject"].startswith(STATEMENT_SUBJECT_PREFIX):
                statements += 1
                continue
            if not rec["is_invoice"]:
                skipped += 1
                continue

            key = ledger.key_for(rec["branch"], rec["invoice_no"])
            if ledger.is_blocked(book, rec["branch"], rec["invoice_no"]):
                already += 1
                continue
            if key in queued_keys:
                resends += 1
                continue

            queued_keys.add(key)
            pending.append(
                {
                    **rec,
                    "qbo_vendor": BRANCH_TO_QBO_VENDOR.get(rec["branch"]),
                    "expense_account": DEFAULT_EXPENSE_ACCOUNT,
                    "queued_at": datetime.now(timezone.utc).isoformat(),
                    "status": "pending",
                    "qbo_bill_id": None,
                    "applied_at": None,
                }
            )
            queued += 1

    _save_json(PENDING_FILE, pending)
    state["last_scanned_at"] = datetime.now(timezone.utc).isoformat()
    _save_json(STATE_FILE, state)

    awaiting = sum(1 for e in pending if e["status"] == "pending")
    print(f"\n  queued new     : {queued}")
    print(f"  statements     : {statements}  (excluded — they re-list billed invoices)")
    print(f"  already in QBO : {already}  (ledger — filed or entered by hand)")
    print(f"  duplicate sends: {resends}  (already queued under same invoice #)")
    if skipped:
        print(f"  unparsed       : {skipped}")
    print(f"\nScan complete. awaiting approval: {awaiting}, total: {len(pending)}")

    unmapped = {
        e["branch"] for e in pending if e["status"] == "pending" and not e["qbo_vendor"]
    }
    if unmapped:
        print("\n  [warn] no QBO vendor mapped for: " + ", ".join(sorted(unmapped)))
        print("         set BRANCH_TO_QBO_VENDOR in bills_config.py before apply.")

    if queued:
        print("\nNext: review, set status to 'approved', then run: python main.py apply")

    if args.notify and queued:
        _notify_new_invoices([e for e in pending if e["status"] == "pending"], queued)
    elif args.notify:
        # Nothing new is the common case on an hourly job — stay quiet rather
        # than texting an all-clear every hour.
        print("  (notify: nothing new, staying quiet)")


def _notify_new_invoices(awaiting: list[dict], new_count: int) -> None:
    """Text Jason that new WinSupply invoices are waiting on his approval."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
        from notify_owner import notify_owner
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] could not load notify_owner: {str(exc)[:120]}")
        return

    def money(entry):
        return float((entry.get("invoice_total") or "0").replace(",", ""))

    newest = sorted(awaiting, key=lambda e: e.get("received_at") or "", reverse=True)
    total = sum(money(e) for e in awaiting)

    if new_count == 1:
        one = newest[0]
        head = (
            f"New WinSupply invoice for Air Sense — {one['invoice_no']}, "
            f"${money(one):,.2f} from {one['branch']}, due {one.get('due_date') or '?'}."
        )
    else:
        head = f"{new_count} new WinSupply invoices for Air Sense:"
        for entry in newest[:5]:
            head += f"\n  • {entry['invoice_no']}  ${money(entry):,.2f}  {entry['branch']}"
        if len(newest) > 5:
            head += f"\n  …and {len(newest) - 5} more"

    tail = (
        f"\n\n{len(awaiting)} awaiting approval, ${total:,.2f} total."
        "\nWant me to file it in QuickBooks? Reply and I'll take it from there."
    )

    if notify_owner(head + tail):
        print(f"  [notify] pinged Jason about {new_count} new invoice(s)")
    else:
        print("  [warn] notify_owner failed — invoice(s) still queued")


# ── list ────────────────────────────────────────────────────────────────


def cmd_list(args: argparse.Namespace) -> None:
    pending: list[dict] = _load_json(PENDING_FILE, [])
    rows = [e for e in pending if not args.status or e["status"] == args.status]
    if not rows:
        print("nothing queued")
        return

    total = 0.0
    print(f"{'invoice':<14} {'branch':<28} {'amount':>11}  {'due':<14} status")
    print("-" * 78)
    for e in sorted(rows, key=lambda r: r.get("received_at") or ""):
        amount = float((e.get("invoice_total") or "0").replace(",", ""))
        total += amount
        print(
            f"{e['invoice_no']:<14} {(e['branch'] or '?'):<28} "
            f"${amount:>10,.2f}  {(e.get('due_date') or ''):<14} {e['status']}"
        )
    print("-" * 78)
    print(f"{len(rows)} bill(s), ${total:,.2f}")


# ── apply ───────────────────────────────────────────────────────────────


def cmd_apply(args: argparse.Namespace) -> None:
    pending: list[dict] = _load_json(PENDING_FILE, [])
    book = ledger.load()

    # An in_flight entry means a previous run sent a create call and died before
    # confirming it. We cannot tell from here whether QuickBooks accepted it, and
    # guessing either way risks a duplicate — so stop and make a human look.
    stranded = ledger.in_flight_entries(book)
    if stranded and not args.dry_run:
        print("REFUSING TO RUN — unconfirmed bill(s) from an earlier run:\n")
        for e in stranded:
            print(f"  {e['invoice_no']} ({e['branch']}) — started {e['updated_at']}")
        print(
            "\nCheck QuickBooks for each. Then edit filed-ledger.json: set status to\n"
            "'filed' if it exists there, or delete the entry if it does not."
        )
        return

    approved = [e for e in pending if e["status"] == "approved"]
    if not approved:
        print("nothing approved — set status to 'approved' on entries you want filed")
        return

    print(f"Applying {len(approved)} approved bill(s)\n")
    filed = failed = blocked = 0
    for entry in approved:
        label = f"{entry['invoice_no']} ({entry['branch']})"

        # Re-check the ledger at file time, not just at scan time: the queue may
        # have been sitting for days, and the invoice could have been entered by
        # hand in the meantime.
        prior = ledger.status_of(book, entry["branch"], entry["invoice_no"])
        if prior in ledger.BLOCKING:
            print(f"  [blocked] {label}: already in QuickBooks (ledger: {prior})")
            entry["status"] = "duplicate-skipped"
            blocked += 1
            continue

        # Resolve from config at file time. Entries queued before a branch was
        # mapped still carry None, and config is the source of truth; an explicit
        # value on the entry wins so a one-off override is possible.
        if not entry.get("qbo_vendor"):
            entry["qbo_vendor"] = BRANCH_TO_QBO_VENDOR.get(entry["branch"])
        if not entry.get("expense_account"):
            entry["expense_account"] = DEFAULT_EXPENSE_ACCOUNT

        if not entry.get("qbo_vendor"):
            print(f"  [skip] {label}: no QBO vendor mapped for this branch")
            failed += 1
            continue

        # QBO rejects a line whose DetailType is AccountBasedExpenseLineDetail
        # without the matching detail object, so an account is mandatory — never
        # emit a half-built line and let the API sort it out.
        account = entry.get("expense_account")
        if not account:
            print(f"  [skip] {label}: no expense account set (see DEFAULT_EXPENSE_ACCOUNT)")
            failed += 1
            continue

        amount = float((entry["invoice_total"] or "0").replace(",", ""))
        line: dict[str, Any] = {
            "Amount": amount,
            "DetailType": "AccountBasedExpenseLineDetail",
            "Description": f"WinSupply invoice {entry['invoice_no']}",
            "AccountBasedExpenseLineDetail": {"AccountRef": {"value": account}},
        }

        payload = {
            "VendorRef": {"value": entry["qbo_vendor"]},
            "DocNumber": to_doc_number(entry["invoice_no"]),
            "TxnDate": _iso_date(entry.get("received_at")),
            "DueDate": _qbo_date(entry.get("due_date")),
            "Line": [line],
            "PrivateNote": f"Auto-staged from {VENDOR_SENDER} — {entry.get('pdf') or ''}",
        }

        if args.dry_run:
            print(f"  [dry-run] {label}: ${amount:,.2f} → vendor {entry['qbo_vendor']}")
            continue

        # Ask QuickBooks directly whether this invoice number already exists on
        # this vendor. Best-effort: the query endpoint is currently throttled, so
        # a failure here is not fatal — the ledger is the primary guard.
        existing = _existing_bill_id(entry)
        if existing:
            print(f"  [blocked] {label}: QuickBooks already has bill {existing}")
            ledger.record(
                book, entry["branch"], entry["invoice_no"], ledger.FILED,
                qbo_bill_id=existing, amount=entry["invoice_total"],
                note="found in QBO during pre-file check",
            )
            ledger.save(book)
            entry["status"] = "duplicate-skipped"
            blocked += 1
            continue

        # Mark in_flight and persist BEFORE the create call. If we die mid-call,
        # the next run refuses to proceed rather than re-sending a bill that may
        # already have landed.
        ledger.record(
            book, entry["branch"], entry["invoice_no"], ledger.IN_FLIGHT,
            amount=entry["invoice_total"],
        )
        ledger.save(book)

        try:
            result = _composio(
                "QUICKBOOKS_CREATE_BILL", payload, account=QUICKBOOKS_ACCOUNT
            )
        except ThrottledError as exc:
            # Throttle means Intuit refused the request outright — nothing was
            # created, so it is safe to clear the in_flight marker.
            book["entries"].pop(ledger.key_for(entry["branch"], entry["invoice_no"]), None)
            ledger.save(book)
            print(f"\n  [blocked] {exc}")
            print("  Stopping — nothing further attempted; queue is unchanged.")
            break
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if _is_definite_rejection(msg):
                book["entries"].pop(
                    ledger.key_for(entry["branch"], entry["invoice_no"]), None
                )
                ledger.save(book)
                print(f"  [error] {label}: {msg[:160]}")
            else:
                # Ambiguous failure (timeout, dropped connection): the bill may
                # or may not exist. Leave in_flight so the next run stops.
                print(f"  [UNCONFIRMED] {label}: {msg[:140]}")
                print("     left in_flight — verify in QuickBooks before re-running")
            failed += 1
            continue

        bill_id = _dig(result, "Bill", "Id") or _dig(result, "Id")
        ledger.record(
            book, entry["branch"], entry["invoice_no"], ledger.FILED,
            qbo_bill_id=bill_id, amount=entry["invoice_total"],
        )
        ledger.save(book)

        entry["status"] = "applied"
        entry["qbo_bill_id"] = bill_id
        entry["applied_at"] = datetime.now(timezone.utc).isoformat()
        filed += 1
        print(f"  [ok] {label}: ${amount:,.2f} → bill {bill_id}")

    if not args.dry_run:
        _save_json(PENDING_FILE, pending)
    print(f"\nfiled={filed} blocked={blocked} failed={failed}")


def _is_definite_rejection(msg: str) -> bool:
    """True when QuickBooks clearly rejected the request and created nothing.

    Validation faults and 4xx responses are safe to treat as "no bill exists".
    Anything else (timeout, connection reset) is ambiguous and must stay
    in_flight so a human confirms before a retry can duplicate a bill.
    """
    markers = ("status 400", "status 401", "status 403", "status 404", '"Fault"',
               "Invalid Number", "Invalid Reference Id", "Input validation failed")
    return any(m in msg for m in markers)


def _existing_bill_id(entry: dict) -> str | None:
    """Return the QBO bill id for this invoice number, if one already exists."""
    doc = to_doc_number(entry.get("invoice_no")).replace("'", "''")
    vendor = (entry.get("qbo_vendor") or "").replace("'", "''")
    query = (
        f"select Id, DocNumber from Bill "
        f"where DocNumber = '{doc}' and VendorRef = '{vendor}'"
    )
    try:
        result = _composio("QUICKBOOKS_QUERY_ENTITIES", {"query": query},
                           account=QUICKBOOKS_ACCOUNT)
    except Exception:  # noqa: BLE001 — throttled or unsupported; ledger still guards
        return None
    bills = _dig(result, "QueryResponse", "Bill") or []
    return str(bills[0].get("Id")) if bills else None


def cmd_mark_existing(args: argparse.Namespace) -> None:
    """Record queued invoices as already-in-QuickBooks so they never get filed.

    For the backlog that was entered by hand before this skill existed.
    """
    pending: list[dict] = _load_json(PENDING_FILE, [])
    book = ledger.load()

    targets = [e for e in pending if e["status"] in ("pending", "approved")]
    if args.before:
        cutoff = args.before
        targets = [e for e in targets if (e.get("received_at") or "")[:10] < cutoff]

    if not targets:
        print("nothing to mark")
        return

    print(f"Marking {len(targets)} invoice(s) as already in QuickBooks:\n")
    total = 0.0
    for entry in targets:
        amount = float((entry.get("invoice_total") or "0").replace(",", ""))
        total += amount
        print(f"  {entry['invoice_no']:<14} {entry['branch']:<28} ${amount:>10,.2f}")
        if not args.dry_run:
            ledger.record(
                book, entry["branch"], entry["invoice_no"], ledger.PREEXISTING,
                amount=entry["invoice_total"],
                note=args.note or "entered in QBO before airsense-bills existed",
            )
            entry["status"] = "preexisting"

    print(f"\n  {len(targets)} invoice(s), ${total:,.2f}")
    if args.dry_run:
        print("  (dry-run — nothing written)")
        return

    ledger.save(book)
    _save_json(PENDING_FILE, pending)
    print("  recorded in filed-ledger.json — these can never be filed again")


def _dig(obj: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _iso_date(value: str | None) -> str:
    if not value:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return value[:10]


def _qbo_date(value: str | None) -> str | None:
    """'Sep 25, 2026' → '2026-09-25'."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%b %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    scan = sub.add_parser("scan", help="Sweep the Air Sense inbox (read-only).")
    scan.add_argument("--days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    scan.add_argument("--notify", action="store_true",
                      help="Text Jason if (and only if) new invoices were queued.")
    scan.set_defaults(func=cmd_scan)

    listing = sub.add_parser("list", help="Show queued bills.")
    listing.add_argument("--status", default=None)
    listing.set_defaults(func=cmd_list)

    apply_cmd = sub.add_parser("apply", help="Create bills for approved entries.")
    apply_cmd.add_argument("--dry-run", action="store_true")
    apply_cmd.set_defaults(func=cmd_apply)

    mark = sub.add_parser(
        "mark-existing",
        help="Record queued invoices as already in QBO so they are never filed.",
    )
    mark.add_argument("--before", default=None, metavar="YYYY-MM-DD",
                      help="Only mark invoices received before this date.")
    mark.add_argument("--note", default=None)
    mark.add_argument("--dry-run", action="store_true")
    mark.set_defaults(func=cmd_mark_existing)

    args = parser.parse_args()
    try:
        args.func(args)
    except RuntimeError as exc:
        print(f"\n[stopped] {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
