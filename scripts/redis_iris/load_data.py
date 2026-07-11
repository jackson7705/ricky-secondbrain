#!/usr/bin/env python3
"""Load Ricky's structured data into Redis so Context Retriever can index it.

Reads the invoice ledger, vendor memory, and client list and writes one Redis
hash per record under the key templates in entities.py. Idempotent — re-run any
time to refresh. Does NOT touch the Obsidian vault.

    export REDIS_URL="redis://default:<password>@<host>:<port>"
    uv run python redis_iris/load_data.py            # load everything
    uv run python redis_iris/load_data.py --dry-run  # show what it WOULD write

Requires: `uv add redis`  (one-time).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

SKILLS = Path(__file__).resolve().parents[1].parent / "skills"
LEDGER = SKILLS / "invoice-router" / "pending-clarification.json"
VENDOR_MEM = SKILLS / "invoice-router" / "vendor-memory.json"

# Locafy SEO/GSC clients (from locafy-gsc-reporting known properties).
CLIENTS = [
    ("air-sense-environmental", "Air Sense Environmental", "airsenseenvironmental.com", "environmental"),
    ("trill-roofing", "Trill Roofing", "trillroofing.com", "roofing"),
    ("nikkis-heating-cooling", "Nikkis Heating & Cooling", "nikkisheatingandcooling.com", "hvac"),
    ("blue-rhino-roofing", "Blue Rhino Roofing", "bluerhinoroofing.net", "roofing"),
    ("constant-air-service-nj", "Constant Air Service NJ", "constantairservicenj.com", "hvac"),
    ("craftsmasters-co", "Craftsmasters Co", "craftsmastersco.com", "exteriors"),
    ("blue-line-works", "Blue Line Works", "bluelineworks.com", "exteriors"),
    ("elevate-exteriors", "Elevate Exteriors", "elevateexteriorsbuild.com", "exteriors"),
    ("prime-craft-exterior", "Prime Craft Exterior", "primecraftexterior.com", "exteriors"),
    ("midwest-exteriors-mn", "Midwest Exteriors MN", "midwestexteriorsmn.com", "exteriors"),
    ("reliant-exterior", "Reliant Exterior", "reliantexterior.com", "exteriors"),
    ("prime-home-exteriors", "Prime Home Exteriors", "primehomeexteriors.com", "exteriors"),
    ("mw-decks", "MW Decks", "mwdecks.com", "decks"),
    ("coastal-exteriors", "Coastal Exteriors", "getcoastalexteriors.com", "exteriors"),
    ("opptywave-ai", "Opptywave AI", "opptywaveai.com", "software"),
    ("growth-pro-agency", "Growth Pro Agency", "growthproagency.com", "agency"),
]


def _load(p: Path):
    return json.loads(p.read_text()) if p.exists() else []


def _fetch_clickup_tasks() -> list[dict]:
    """Pull open team tasks (all assignees) from ClickUp. Returns [] on any error
    (e.g. dead token) so the rest of the load still runs."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        import httpx  # noqa: PLC0415
        from integrations.clickup_api import (  # noqa: PLC0415
            CLICKUP_API_BASE, _headers, _require_workspace,
        )
        ws = _require_workspace()
        out, page = [], 0
        while page < 20:
            resp = httpx.get(
                f"{CLICKUP_API_BASE}/team/{ws}/task", headers=_headers(),
                params={"include_closed": "false", "subtasks": "true", "page": page},
                timeout=20,
            )
            resp.raise_for_status()
            batch = resp.json().get("tasks", [])
            out.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return out
    except Exception as exc:  # noqa: BLE001
        print(f"  [clickup] skipped — {str(exc)[:90]}  (fix CLICKUP_API_TOKEN in .env)")
        return []


def build_records() -> dict[str, dict]:
    """Return {redis_key: field_mapping} for every entity record."""
    out: dict[str, dict] = {}

    for e in _load(LEDGER):
        mid = e.get("message_id")
        if not mid:
            continue
        out[f"invoice:{mid}"] = {
            "vendor": (e.get("vendor") or e.get("guess_vendor") or "").lower(),
            "business": e.get("business") or e.get("guess_business") or "",
            "month": e.get("proposed_month") or "",
            "status": e.get("status") or "",
            "amount": float(e.get("amount") or e.get("guess_amount") or 0.0),
            "use": e.get("use") or e.get("guess_use") or "",
            "subject": e.get("subject") or "",
        }

    vmem = _load(VENDOR_MEM) or {}
    for slug, v in vmem.items():
        if slug.startswith("_") or not isinstance(v, dict):
            continue
        out[f"vendor:{slug.replace(' ', '-')}"] = {
            "name": slug.title(),
            "business": v.get("business", ""),
            "category": v.get("use", ""),
        }

    for t in _fetch_clickup_tasks():
        tid = str(t.get("id") or "")
        if not tid:
            continue
        st = t.get("status") or {}
        due_ymd = 0
        if t.get("due_date"):
            try:
                from datetime import datetime, timezone  # noqa: PLC0415
                due_ymd = int(datetime.fromtimestamp(int(t["due_date"]) / 1000, tz=timezone.utc).strftime("%Y%m%d"))
            except (TypeError, ValueError):
                due_ymd = 0
        assignees = t.get("assignees") or []
        prio = t.get("priority") or {}
        lst = t.get("list") or {}
        out[f"task:{tid}"] = {
            "name": t.get("name", ""),
            "status": (st.get("status") if isinstance(st, dict) else str(st)) or "",
            "status_type": (st.get("type") if isinstance(st, dict) else "") or "open",
            "assignee": (assignees[0].get("username", "") if assignees else ""),
            "list": lst.get("name", "") if isinstance(lst, dict) else "",
            "priority": (prio.get("priority") if isinstance(prio, dict) else "") or "none",
            "due_ymd": due_ymd,
        }

    for slug, name, url, industry in CLIENTS:
        out[f"client:{slug}"] = {
            "name": name, "property_url": url,
            "business": "locafy", "industry": industry,
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    records = build_records()
    counts: dict[str, int] = {}
    for k in records:
        counts[k.split(":", 1)[0]] = counts.get(k.split(":", 1)[0], 0) + 1
    print(f"built {len(records)} records: " + ", ".join(f"{v} {k}" for k, v in counts.items()))

    if args.dry_run:
        for k, m in list(records.items())[:5]:
            print(f"  {k} -> {m}")
        print("  … (dry-run; nothing written)")
        return 0

    url = os.environ.get("REDIS_URL")
    if not url:
        print("\nREDIS_URL not set — create a Redis Cloud DB, then:\n"
              '  export REDIS_URL="redis://default:<password>@<host>:<port>"\n'
              "  uv run python redis_iris/load_data.py\n"
              "(and `uv add redis` if you haven't). Use --dry-run to preview meanwhile.")
        return 1
    try:
        import redis  # noqa: PLC0415
    except ImportError:
        print("redis not installed — run: uv add redis")
        return 1

    r = redis.from_url(url, decode_responses=True)
    r.ping()
    # Context Retriever builds a JSON index ($.field paths), so write RedisJSON
    # documents (not hashes). DEL first in case an old hash exists at the key.
    pipe = r.pipeline()
    for key, mapping in records.items():
        pipe.delete(key)
        pipe.execute_command("JSON.SET", key, "$", json.dumps(mapping))
    pipe.execute()
    print(f"wrote {len(records)} JSON records to Redis at {url.split('@')[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
