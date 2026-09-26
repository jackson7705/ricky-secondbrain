#!/usr/bin/env python3
"""pending_tasks.py — the approval gate between Ricky's task-finding jobs and ClickUp.

Owner's standing instruction (2026-09-17): "Ask me before you add these to my
personal list." Until then `loose_ends` and `fathom_sweep` filed straight into
ClickUp and *then* announced it. Now they propose; nothing is created until the
owner approves by number.

Flow
    job (loose_ends / fathom_sweep)  →  propose(items)   → owner gets a numbered list
    owner replies "add 12, 14" / "add all" / "skip 13"   → chat agent runs:
        uv run python pending_tasks.py approve 12 14
        uv run python pending_tasks.py approve all
        uv run python pending_tasks.py reject 13
        uv run python pending_tasks.py reject all
        uv run python pending_tasks.py list

Ids are stable and global (#12 means the same thing tomorrow), so approvals
can arrive hours after the proposal message. Pending items older than
PENDING_TTL_DAYS are dropped automatically. Rejected titles are remembered so
the same email doesn't get re-proposed on the next sweep.

State: .claude/data/state/pending-tasks.json
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent / ".env")

STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "state" / "pending-tasks.json"
PENDING_TTL_DAYS = 7
REMEMBER_DECIDED = 400  # approved/rejected rows kept for dedup


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def _similar(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return a == b or a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.72


class PendingTasks:
    def __init__(self, path: Path = STATE_PATH) -> None:
        self.path = path
        self.state = self._load()

    # ── persistence ────────────────────────────────────────────────────
    def _load(self) -> dict:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                data.setdefault("next_id", 1)
                data.setdefault("items", [])
                return data
            except ValueError:
                pass
        return {"next_id": 1, "items": []}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state, indent=2, ensure_ascii=False))

    # ── queries ────────────────────────────────────────────────────────
    @property
    def items(self) -> list[dict]:
        return self.state["items"]

    def pending(self) -> list[dict]:
        return [i for i in self.items if i["status"] == "pending"]

    def known_titles(self) -> list[str]:
        """Every title we've proposed, approved or rejected — for job-side dedup."""
        return [_norm(i["title"]) for i in self.items]

    def is_known(self, title: str) -> bool:
        n = _norm(title)
        return any(_similar(n, k) for k in self.known_titles())

    # ── mutations ──────────────────────────────────────────────────────
    def expire(self, now: datetime | None = None) -> int:
        """Drop pending items past the TTL; trim decided history. Returns dropped count."""
        now = now or datetime.now()
        cutoff = now - timedelta(days=PENDING_TTL_DAYS)
        expired = 0
        for it in self.items:
            if it["status"] == "pending" and datetime.fromisoformat(it["proposed_at"]) < cutoff:
                it["status"] = "expired"
                it["decided_at"] = now.isoformat(timespec="seconds")
                expired += 1
        decided = [i for i in self.items if i["status"] != "pending"]
        if len(decided) > REMEMBER_DECIDED:
            drop = {id(i) for i in decided[: len(decided) - REMEMBER_DECIDED]}
            self.state["items"] = [i for i in self.items if id(i) not in drop]
        return expired

    def propose(self, items: list[dict], origin: str) -> list[dict]:
        """Add new proposals. Each item: title, note, due, source (+ any extras).
        Skips titles already known. Returns the items that were added, with ids."""
        self.expire()
        added: list[dict] = []
        for it in items:
            title = (it.get("title") or "").strip()
            if not title or self.is_known(title):
                continue
            row = {
                "id": self.state["next_id"],
                "title": title[:120],
                "note": (it.get("note") or "")[:600],
                "due": it.get("due") or "",
                "source": (it.get("source") or "")[:200],
                "origin": origin,
                "proposed_at": datetime.now().isoformat(timespec="seconds"),
                "status": "pending",
            }
            for k in ("url", "meeting", "priority"):
                if it.get(k):
                    row[k] = it[k]
            self.state["next_id"] += 1
            self.items.append(row)
            added.append(row)
        return added

    def _select(self, selector: list[str]) -> list[dict]:
        pend = self.pending()
        if any(s.lower() == "all" for s in selector):
            return pend
        want: set[int] = set()
        for s in selector:
            for tok in s.replace(",", " ").split():
                tok = tok.lstrip("#")
                if tok.isdigit():
                    want.add(int(tok))
        return [i for i in pend if i["id"] in want]

    def approve(self, selector: list[str], create_task=None) -> tuple[list[dict], list[str]]:
        """File the selected pending items in ClickUp. Returns (filed, errors)."""
        if create_task is None:
            from integrations.clickup_api import create_task as _ct
            create_task = _ct
        from config import CLICKUP_INBOX_LIST_ID, CLICKUP_OWNER_UID

        filed: list[dict] = []
        errors: list[str] = []
        for it in self._select(selector):
            due_on = None
            if it.get("due"):
                try:
                    due_on = date.fromisoformat(it["due"])
                except ValueError:
                    due_on = None
            desc = it.get("note", "")
            if it.get("url"):
                desc += f"\n{it['url']}"
            desc += f"\n\nFiled by Ricky after your approval — source: {it.get('source', '')}"
            try:
                task = create_task(
                    CLICKUP_INBOX_LIST_ID, it["title"], description=desc.strip(),
                    due_on=due_on, assignees=[int(CLICKUP_OWNER_UID)] if CLICKUP_OWNER_UID else [],
                    priority=it.get("priority"),
                )
                it["status"] = "approved"
                it["decided_at"] = datetime.now().isoformat(timespec="seconds")
                it["clickup_task_id"] = getattr(task, "id", None) or (
                    task.get("id") if isinstance(task, dict) else None)
                it["clickup_url"] = getattr(task, "url", None) or (
                    task.get("url") if isinstance(task, dict) else None)
                filed.append(it)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"#{it['id']} {it['title'][:50]}: {str(exc)[:80]}")
        return filed, errors

    def reject(self, selector: list[str]) -> list[dict]:
        out = []
        for it in self._select(selector):
            it["status"] = "rejected"
            it["decided_at"] = datetime.now().isoformat(timespec="seconds")
            out.append(it)
        return out


# ── message formatting (shared by the jobs) ──────────────────────────────
def format_proposal(added: list[dict], origin_label: str) -> str:
    lines = [f"📋 {len(added)} proposed task(s) from {origin_label} — NOT filed yet:"]
    for it in added:
        due = f" (due {it['due']})" if it.get("due") else ""
        ctx = f" — {it['meeting'][:30]}" if it.get("meeting") else ""
        lines.append(f"#{it['id']} {it['title']}{due}{ctx}")
    ids = ", ".join(str(i["id"]) for i in added[:2])
    lines.append(
        f"\nReply \"add {ids}\" or \"add all\" to put them in ClickUp, "
        f"\"skip {added[0]['id']}\" / \"skip all\" to drop. "
        f"Unanswered proposals expire in {PENDING_TTL_DAYS} days."
    )
    return "\n".join(lines)


def format_pending(pend: list[dict]) -> str:
    if not pend:
        return "No pending task proposals."
    lines = [f"{len(pend)} pending proposal(s):"]
    for it in pend:
        due = f" (due {it['due']})" if it.get("due") else ""
        lines.append(f"#{it['id']} [{it['origin']}] {it['title']}{due} "
                     f"— proposed {it['proposed_at'][:10]}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="show pending proposals")
    a = sub.add_parser("approve", help="file selected proposals in ClickUp")
    a.add_argument("ids", nargs="+", help="ids like 12 14, '#12', '12,14', or 'all'")
    r = sub.add_parser("reject", help="drop selected proposals")
    r.add_argument("ids", nargs="+", help="ids or 'all'")
    args = ap.parse_args(argv)

    pt = PendingTasks()
    pt.expire()
    if args.cmd == "list":
        print(format_pending(pt.pending()))
        pt.save()
        return 0
    if args.cmd == "approve":
        filed, errors = pt.approve(args.ids)
        pt.save()
        if not filed and not errors:
            print("Nothing matched. Pending:\n" + format_pending(pt.pending()))
            return 1
        for it in filed:
            link = f" {it['clickup_url']}" if it.get("clickup_url") else ""
            print(f"filed #{it['id']} {it['title']}{link}")
        for e in errors:
            print(f"ERROR {e}")
        left = pt.pending()
        if left:
            print(f"\n{len(left)} still pending: " + ", ".join(f"#{i['id']}" for i in left))
        return 0 if not errors else 2
    if args.cmd == "reject":
        dropped = pt.reject(args.ids)
        pt.save()
        if not dropped:
            print("Nothing matched. Pending:\n" + format_pending(pt.pending()))
            return 1
        for it in dropped:
            print(f"dropped #{it['id']} {it['title']}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
