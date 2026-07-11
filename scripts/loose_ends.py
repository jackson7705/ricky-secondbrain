#!/usr/bin/env python3
"""loose_ends.py — catch action items from Jason's inbox and file them as ClickUp
tasks so nothing slips through. Dedupes against existing tasks; reports via iMessage.

DRY-RUN by default (extract + show, create nothing). `--apply` auto-creates the tasks
and texts Jason a summary.

Scope note: the inbox half is fully automated here. Fathom meetings are NOT scriptable
in this setup (no Fathom MCP wired) — `meeting-concierge` covers those semi-manually.

    uv run python loose_ends.py --dry-run
    uv run python loose_ends.py --apply
"""
from __future__ import annotations

import argparse
import difflib
import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent / ".env")

STATE = Path(__file__).resolve().parent.parent / "data" / "state" / "loose-ends-state.json"
from config import CLICKUP_INBOX_LIST_ID as INBOX_LIST_ID  # noqa: E402
from config import CLICKUP_OWNER_UID as OWNER_UID  # noqa: E402
ACCOUNTS = ["growthpro", "locafy"]
LOOKBACK_HOURS = 48
MAX_EMAILS = 30

EXTRACT_PROMPT = """You are triaging Jason's email inbox so nothing slips through the cracks.
From the emails below, extract ONLY genuine action items Jason needs to DO or follow up on:
commitments he made, requests awaiting his reply, deadlines, deliverables he owes, things
he's waiting on from others. SKIP newsletters, receipts/invoices, marketing, automated
notifications, and pure FYIs. Be conservative — a false task is worse than a miss.

Output ONLY a JSON array; each element:
{"title":"short imperative task (<=80 chars)","note":"one line: who/what/why","due":"YYYY-MM-DD or empty string","source":"email subject"}
If nothing qualifies, output []."""


def _load_state() -> dict:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text())
        except ValueError:
            pass
    return {"seen_email_ids": [], "created_signatures": [], "last_run": None}


def _save_state(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=2))


def _existing_task_names() -> list[str]:
    """Existing ClickUp task titles (from the Redis mirror) for dedup — fast."""
    import os
    try:
        import redis
        r = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
        names = []
        for k in r.scan_iter("task:*", count=2000):
            n = r.execute_command("JSON.GET", k, "$.name")
            if n:
                names.append(json.loads(n)[0].lower())
        return names
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] task dedup mirror unavailable ({str(exc)[:60]}) — creating without mirror dedup")
        return []


def _recent_emails() -> list[dict]:
    # Re-scan the whole lookback window every run (no permanent "seen" skip) so a
    # real action item the LLM misses on one pass gets caught on the next. The
    # task dedup (Redis mirror + created_signatures) stops duplicate creation.
    from integrations.auth import set_active_account
    from integrations.gmail import get_email_details, get_gmail_service, list_emails
    out: list[dict] = []
    for acct in ACCOUNTS:
        set_active_account(acct)
        try:
            emails = list_emails(max_results=MAX_EMAILS, hours_ago=LOOKBACK_HOURS,
                                 query="in:inbox -category:promotions -category:social")
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] {acct} inbox scan failed: {str(exc)[:60]}")
            continue
        svc = get_gmail_service()
        for e in emails:
            if (e.sender_email or "").lower() in ("me",):
                continue
            body = ""
            try:
                det = get_email_details(svc, e.id, include_body=True)
                body = (det.body if det else "") or e.snippet or ""
            except Exception:  # noqa: BLE001
                body = e.snippet or ""
            out.append({"id": e.id, "account": acct, "from": e.sender_email or "",
                        "subject": e.subject or "", "body": body[:1800]})
    return out


def _extract(emails: list[dict]) -> list[dict]:
    if not emails:
        return []
    blob = "\n\n".join(f"[{i}] FROM {e['from']} | SUBJECT: {e['subject']}\n{e['body']}"
                       for i, e in enumerate(emails))
    payload = f"{EXTRACT_PROMPT}\n\n=== EMAILS ===\n{blob}\n"
    try:
        res = subprocess.run(["claude", "-p"], input=payload, capture_output=True, text=True, timeout=300)
    except Exception as exc:  # noqa: BLE001
        print(f"  [error] extraction failed: {exc}")
        return []
    out = (res.stdout or "").strip()
    a, b = out.find("["), out.rfind("]")
    if a == -1 or b == -1:
        return []
    try:
        return json.loads(out[a:b + 1])
    except ValueError:
        return []


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def _is_dupe(title: str, existing: list[str], sigs: set[str]) -> bool:
    n = _norm(title)
    if n in sigs:
        return True
    for name in existing:
        if difflib.SequenceMatcher(None, n, name).ratio() >= 0.72 or n in name or name in n:
            return True
    return False


def main(dry_run: bool) -> int:
    st = _load_state()
    sigs = set(st.get("created_signatures", []))

    emails = _recent_emails()
    print(f"scanned {len(emails)} new inbox emails ({', '.join(ACCOUNTS)}, last {LOOKBACK_HOURS}h)")
    items = _extract(emails)
    existing = _existing_task_names()

    fresh = []
    for it in items:
        title = (it.get("title") or "").strip()
        if not title or _is_dupe(title, existing, sigs):
            continue
        fresh.append(it)

    print(f"extracted {len(items)} action item(s); {len(fresh)} new after dedup:\n")
    for it in fresh:
        due = it.get("due") or "—"
        print(f"  • {it.get('title')}  [due {due}]\n      {it.get('note','')}  (from: {it.get('source','')})")

    if dry_run:
        print("\n(DRY-RUN — no tasks created.)")
        return 0

    # --apply: create tasks + report
    from integrations.clickup_api import create_task
    created = []
    for it in fresh:
        due_on = None
        if it.get("due"):
            try:
                due_on = date.fromisoformat(it["due"])
            except ValueError:
                due_on = None
        desc = f"{it.get('note','')}\n\nAuto-filed by Ricky from inbox — source: {it.get('source','')}"
        try:
            t = create_task(INBOX_LIST_ID, it["title"], description=desc,
                            due_on=due_on, assignees=[int(OWNER_UID)] if OWNER_UID else [])
            created.append((it, t))
            sigs.add(_norm(it["title"]))
        except Exception as exc:  # noqa: BLE001
            print(f"  [error] create '{it['title'][:40]}': {str(exc)[:70]}")

    # update state — only remember what we CREATED (dedup), not what we scanned
    st["created_signatures"] = list(sigs)[-2000:]
    st["last_run"] = datetime.now().isoformat(timespec="seconds")
    _save_state(st)

    print(f"\ncreated {len(created)} ClickUp task(s) in the Inbox list")
    if created:
        _report(created)
    return 0


def _report(created: list) -> None:
    import urllib.parse
    import urllib.request

    from config import BLUEBUBBLES_PASSWORD, BLUEBUBBLES_URL, OWNER_IMESSAGE_GUID
    lines = [f"🧹 Loose ends — filed {len(created)} task(s) from your inbox:"]
    for it, _t in created:
        due = f" (due {it['due']})" if it.get("due") else ""
        lines.append(f"• {it['title']}{due}")
    lines.append("\nAll in your ClickUp Inbox list. Reply if any shouldn't be there.")
    text = "\n".join(lines)[:1400]
    if not BLUEBUBBLES_URL or not BLUEBUBBLES_PASSWORD:
        print("  [skip] BlueBubbles not configured — summary:\n" + text)
        return
    url = f"{BLUEBUBBLES_URL}/api/v1/message/text?password={urllib.parse.quote(BLUEBUBBLES_PASSWORD)}"
    body = json.dumps({"chatGuid": OWNER_IMESSAGE_GUID, "message": text,
                       "method": "apple-script",
                       "tempGuid": f"loose-{int(datetime.now().timestamp()*1000)}"}).encode()
    try:
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=20)
        print("  texted Jason the summary ✓")
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] iMessage report failed: {str(exc)[:60]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", default=True)
    ap.add_argument("--apply", dest="dry_run", action="store_false")
    sys.exit(main(ap.parse_args().dry_run))
