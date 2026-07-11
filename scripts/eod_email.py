#!/usr/bin/env python3
"""eod_email.py — end-of-day inbox triage.

Finds emails that look like they're awaiting Jason's reply, DRAFTS replies straight
into his Gmail Drafts, stages them for approval, and texts him a summary.

⚠️ THIS JOB NEVER SENDS. Sending is a separate, explicitly-approved step: Ricky runs
`query.py gmail send-draft <id>` ONLY after Jason approves that specific draft. There is
no send call anywhere in this file.

    uv run python eod_email.py            # scan + draft + ping  (default)
    uv run python eod_email.py --dry-run  # scan + show, create no drafts
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent / ".env")

DATA = Path(__file__).resolve().parent.parent / "data" / "state"
STATE = DATA / "eod-email-state.json"
PENDING = DATA / "pending-replies.json"   # read by Ricky when Jason approves a send
ACCOUNTS = ["growthpro", "locafy"]
LOOKBACK_HOURS = 30
MAX_EMAILS = 20

DRAFT_PROMPT = """You draft email replies for Jason Jackson, COO of Locafy (also runs Growth Pro Agency).
For each email below that genuinely awaits Jason's reply — a direct question, a request, something needing his decision or response — write a reply in HIS voice: direct, warm-professional, concise, no filler, sign off as "Jason". SKIP anything that doesn't need a reply (newsletters, receipts, notifications, FYIs, threads where nothing is being asked of him).

Output ONLY a JSON array; one element per email that needs a reply:
{"idx": <the email's index>, "draft_body": "<the full reply text>", "why": "<one line: what they asked>"}
If none need a reply, output []."""


def _load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except ValueError:
            pass
    return {"drafted_threads": [], "last_run": None}


def _candidates(done_threads: set[str]) -> list[dict]:
    """Recent inbound emails Jason likely hasn't answered yet."""
    from integrations.auth import set_active_account
    from integrations.gmail import (
        check_sent_reply, get_email_details, get_gmail_service, list_emails,
    )
    out: list[dict] = []
    for acct in ACCOUNTS:
        set_active_account(acct)
        try:
            emails = list_emails(max_results=MAX_EMAILS, hours_ago=LOOKBACK_HOURS,
                                 query="in:inbox -category:promotions -category:social")
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] {acct} scan failed: {str(exc)[:60]}")
            continue
        svc = get_gmail_service()
        for e in emails:
            tid = e.thread_id or e.id
            if tid in done_threads or (e.sender_email or "").lower() in ("me",):
                continue
            # skip if Jason already replied in this thread
            try:
                if check_sent_reply(tid, e.date.isoformat()):
                    continue
            except Exception:  # noqa: BLE001
                pass
            body = ""
            try:
                det = get_email_details(svc, e.id, include_body=True)
                body = (det.body if det else "") or e.snippet or ""
            except Exception:  # noqa: BLE001
                body = e.snippet or ""
            out.append({"id": e.id, "thread_id": tid, "account": acct,
                        "from": e.sender or e.sender_email or "", "from_email": e.sender_email or "",
                        "subject": e.subject or "", "body": body[:1800]})
    return out


def _draft(emails: list[dict]) -> list[dict]:
    if not emails:
        return []
    blob = "\n\n".join(f"[{i}] FROM {e['from']} | SUBJECT: {e['subject']}\n{e['body']}"
                       for i, e in enumerate(emails))
    try:
        res = subprocess.run(["claude", "-p"], input=f"{DRAFT_PROMPT}\n\n=== EMAILS ===\n{blob}\n",
                             capture_output=True, text=True, timeout=360)
    except Exception as exc:  # noqa: BLE001
        print(f"  [error] drafting failed: {exc}")
        return []
    out = (res.stdout or "").strip()
    a, b = out.find("["), out.rfind("]")
    if a == -1 or b == -1:
        return []
    try:
        return json.loads(out[a:b + 1])
    except ValueError:
        return []


def main(dry_run: bool) -> int:
    from integrations.auth import set_active_account
    from integrations.gmail import create_gmail_draft

    st = _load_state()
    done = set(st.get("drafted_threads", []))
    emails = _candidates(done)
    print(f"scanned inbox ({', '.join(ACCOUNTS)}, {LOOKBACK_HOURS}h) — {len(emails)} unanswered candidate(s)")
    drafts = _draft(emails)
    print(f"drafted {len(drafts)} repl(y/ies):\n")

    pending, previews = [], []
    for d in drafts:
        try:
            e = emails[int(d["idx"])]
        except (KeyError, ValueError, IndexError):
            continue
        subject = e["subject"] if e["subject"].lower().startswith("re:") else f"Re: {e['subject']}"
        print(f"  → to {e['from_email']}  ({d.get('why','')})")
        print(f"    {d['draft_body'][:160].replace(chr(10),' ')}…\n")
        previews.append(f"{len(previews)+1}. {e['from_email']} — {d.get('why','')}")
        if dry_run:
            continue
        set_active_account(e["account"])
        try:
            res = create_gmail_draft(to=e["from_email"], subject=subject, body=d["draft_body"],
                                     thread_id=e["thread_id"], message_id=e["id"])
        except Exception as exc:  # noqa: BLE001
            print(f"  [error] draft create failed: {str(exc)[:70]}")
            continue
        pending.append({"n": len(pending) + 1, "draft_id": res["draft_id"], "account": e["account"],
                        "to": e["from_email"], "subject": subject, "why": d.get("why", ""),
                        "source_subject": e["subject"]})
        done.add(e["thread_id"])

    if dry_run:
        print("(DRY-RUN — no drafts created, nothing staged.)")
        return 0

    DATA.mkdir(parents=True, exist_ok=True)
    PENDING.write_text(json.dumps(pending, indent=2))
    st["drafted_threads"] = list(done)[-500:]
    st["last_run"] = datetime.now().isoformat(timespec="seconds")
    STATE.write_text(json.dumps(st, indent=2))

    if pending:
        _ping(previews)
    print(f"\nstaged {len(pending)} draft(s) in Gmail + {PENDING} — NOTHING SENT.")
    return 0


def _ping(previews: list[str]) -> None:
    import urllib.parse
    import urllib.request

    from config import BLUEBUBBLES_PASSWORD, BLUEBUBBLES_URL
    text = ("📥 End-of-day email triage — I drafted " + str(len(previews)) +
            " repl(y/ies) (they're in your Gmail Drafts, nothing sent):\n\n" +
            "\n".join(previews) +
            "\n\nReply e.g. \"send 1\", \"send all\", or \"edit 2\" — I won't send anything until you say so.")
    if not BLUEBUBBLES_URL or not BLUEBUBBLES_PASSWORD:
        print("  [skip] BlueBubbles not configured — summary:\n" + text)
        return
    url = f"{BLUEBUBBLES_URL}/api/v1/message/text?password={urllib.parse.quote(BLUEBUBBLES_PASSWORD)}"
    body = json.dumps({"chatGuid": "any;-;+16185582424", "message": text[:1600],
                       "method": "apple-script",
                       "tempGuid": f"eod-{int(datetime.now().timestamp()*1000)}"}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}), timeout=20)
        print("  texted Jason the triage ✓")
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] iMessage ping failed: {str(exc)[:60]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", default=False)
    sys.exit(main(ap.parse_args().dry_run))
