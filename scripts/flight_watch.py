#!/usr/bin/env python3
"""flight_watch.py — hourly fare watcher that pings the owner when a route
drops significantly or a flash deal shows up.

Deterministic: no LLM in the loop. Reads Google Flights through an MCP Scraper
hosted browser session, compares the cheapest bookable itinerary against the
lowest price seen so far, and only notifies when a threshold is actually crossed.

Watches are declared in WATCHES below. State (best price seen, last alerted
price, history) lives in .claude/data/state/flight-watch-state.json.

    uv run python flight_watch.py              # normal hourly run
    uv run python flight_watch.py --dry-run    # check prices, never notify
    uv run python flight_watch.py --force      # notify with the current best
    uv run python flight_watch.py --status     # print state, no network call
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent / ".env")

import config  # noqa: E402
from integrations.mcp_scraper import read_page  # noqa: E402
from shared import append_to_daily_log, load_state, save_state  # noqa: E402

STATE_FILE = config.STATE_DIR / "flight-watch-state.json"
FLIGHTS_URL = "https://www.google.com/travel/flights?q={query}&hl=en&gl=us&curr=USD"

# Itineraries longer than this are ignored when picking "cheapest" — a $430 fare
# that takes 24 hours is not a deal worth waking someone up for.
MAX_REASONABLE_MINUTES = 12 * 60

WATCHES = [
    {
        "key": "stl-msy-oct1-oct4-nonstop",
        "label": "St. Louis to New Orleans (nonstop only)",
        "origin": "STL",
        "destination": "MSY",
        "depart": "2026-10-01",
        "return": "2026-10-04",
        "adults": 1,
        "cabin": "economy",
        # Jason only wants nonstop. Connecting itineraries are discarded before
        # any price is scored, so every threshold below refers to a nonstop fare.
        "nonstop_only": True,
        # Alert when the cheapest nonstop beats the best seen so far by either of
        # these. Whichever is easier to hit wins.
        "drop_pct": 0.07,
        "drop_abs": 50,
        # Absolute "stop what you are doing" numbers.
        "flash_any": 600,
        "flash_nonstop": 600,
    },
]


# ── google flights via mcp scraper ───────────────────────────────────────────
_TIME = re.compile(r"^\d{1,2}:\d{2}\s?[AP]M(\+\d)?$")
_PRICE = re.compile(r"^\$([\d,]+)$")
_STOPS = re.compile(r"^(\d+) stops?$")
_DURATION = re.compile(r"^(?:(\d+) hr)?\s*(?:(\d+) min)?$")
_RESULTS = re.compile(r"\b\d+ results? returned")


def search_url(watch: dict) -> str:
    """Google Flights reads the trip from a plain-language query. Asking for
    nonstop there applies the stops filter, so a nonstop watch never has its
    fares pushed below the fold by cheaper connections."""
    query = "Nonstop flights" if watch.get("nonstop_only") else "Flights"
    query += f" from {watch['origin']} to {watch['destination']} on {watch['depart']}"
    if watch.get("return"):
        query += f" through {watch['return']}"
    if watch.get("cabin", "economy") != "economy":
        query += f" {watch['cabin']} class"
    if watch.get("adults", 1) > 1:
        query += f" for {watch['adults']} adults"
    return FLIGHTS_URL.format(query=quote(query))


def _minutes(text: str) -> int:
    match = _DURATION.match(text)
    if not match or not any(match.groups()):
        return 0
    return int(match.group(1) or 0) * 60 + int(match.group(2) or 0)


def parse_fares(text: str, watch: dict) -> list[dict]:
    """Itineraries from the visible text of a Google Flights results page.

    Each result is a run of lines: departure, dash, arrival, airline, duration,
    route, stops, (layover), emissions, bag counts, price. Anything that does
    not match the watched route is ignored.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    route = f"{watch['origin']}–{watch['destination']}"
    url = search_url(watch)
    items: list[dict] = []
    i = 0
    while i < len(lines) - 3:
        if not (_TIME.match(lines[i]) and lines[i + 1] in ("–", "-") and _TIME.match(lines[i + 2])):
            i += 1
            continue
        block = lines[i + 3 : i + 16]
        for j, line in enumerate(block):  # a result ends where the next one starts
            if _TIME.match(line) and j + 1 < len(block) and block[j + 1] in ("–", "-"):
                block = block[:j]
                break
        price = next((m.group(1) for ln in block if (m := _PRICE.match(ln))), None)
        stops = next(
            (0 if ln == "Nonstop" else int(m.group(1)) for ln in block
             if ln == "Nonstop" or (m := _STOPS.match(ln))),
            None,
        )
        if price and stops is not None and route in block and block:
            duration = next((ln for ln in block[1:] if _minutes(ln)), "")
            items.append(
                {
                    "price": float(price.replace(",", "")),
                    "stops": stops,
                    "airline": block[0].split("Operated by")[0].strip(),
                    "duration": duration,
                    "durationMinutes": _minutes(duration),
                    "departureTime": lines[i],
                    "url": url,
                }
            )
        i += 3
    return items


def fetch_fares(watch: dict) -> list[dict]:
    text = read_page(search_url(watch), ready=lambda t: bool(_RESULTS.search(t)))
    # Refuse to score a page we cannot tie to this trip: a misread query would
    # otherwise report another day's fares as a price drop.
    if watch["origin"] not in text or watch["destination"] not in text:
        raise RuntimeError("results page does not show the watched route")
    if f"departing {watch['depart']}" not in text:
        raise RuntimeError("results page does not show the watched departure date")
    if watch.get("return") and f"returning {watch['return']}" not in text:
        raise RuntimeError("results page does not show the watched return date")
    return parse_fares(text, watch)


# ── scoring ──────────────────────────────────────────────────────────────────
def _price(item: dict) -> float | None:
    try:
        value = float(item.get("price"))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def summarize(items: list[dict], *, nonstop_only: bool = False) -> dict:
    """Cheapest reasonable fare overall, and cheapest nonstop.

    With nonstop_only, connecting itineraries are dropped entirely so that
    min_price (the number every alert threshold is measured against) IS the
    cheapest nonstop. Otherwise a $430 one-stop would hide a nonstop drop.
    """
    reasonable, nonstop = [], []
    for item in items:
        price = _price(item)
        if price is None:
            continue
        minutes = item.get("durationMinutes") or 0
        if minutes and minutes > MAX_REASONABLE_MINUTES:
            continue
        is_nonstop = item.get("stops") == 0
        if nonstop_only and not is_nonstop:
            continue
        reasonable.append((price, item))
        if is_nonstop:
            nonstop.append((price, item))

    best = min(reasonable, key=lambda p: p[0]) if reasonable else None
    best_nonstop = min(nonstop, key=lambda p: p[0]) if nonstop else None
    return {
        "checked": len(items),
        "usable": len(reasonable),
        "min_price": best[0] if best else None,
        "min_item": best[1] if best else None,
        "min_nonstop": best_nonstop[0] if best_nonstop else None,
        "min_nonstop_item": best_nonstop[1] if best_nonstop else None,
    }


def describe(item: dict | None) -> str:
    if not item:
        return "n/a"
    airline = item.get("airline") or "?"
    stops = item.get("stops")
    hop = "nonstop" if stops == 0 else f"{stops} stop" + ("s" if (stops or 0) > 1 else "")
    return f"{airline}, {hop}, {item.get('duration') or '?'}, departs {item.get('departureTime') or '?'}"


def decide(watch: dict, now: dict, prior: dict) -> tuple[bool, list[str]]:
    """Returns (should_alert, reasons)."""
    reasons: list[str] = []
    price = now["min_price"]
    if price is None:
        return False, reasons

    best_seen = prior.get("best_seen")
    last_alert = prior.get("last_alert_price")
    # Only alert on a price that also beats whatever we last shouted about, so a
    # fare bouncing around the same level does not ping every hour.
    floor = min(x for x in (best_seen, last_alert) if x is not None) if (
        best_seen is not None or last_alert is not None
    ) else None

    if floor is not None:
        drop = floor - price
        if drop >= watch["drop_abs"] or (floor and drop / floor >= watch["drop_pct"]):
            reasons.append(f"down ${drop:.0f} from ${floor:.0f} (best seen before now)")

    if price <= watch["flash_any"]:
        reasons.append(f"at or under the ${watch['flash_any']:.0f} flash-deal line")

    nonstop = now["min_nonstop"]
    if nonstop is not None and nonstop <= watch["flash_nonstop"]:
        prior_ns = prior.get("last_alert_nonstop")
        if prior_ns is None or nonstop < prior_ns:
            reasons.append(f"nonstop at ${nonstop:.0f}, under the ${watch['flash_nonstop']:.0f} line")

    return bool(reasons), reasons


def build_message(watch: dict, now: dict, reasons: list[str], prior: dict) -> str:
    price = now["min_price"]
    lines = [
        f"Fare alert: {watch['label']} ({watch['origin']} to {watch['destination']})",
        f"{watch['depart']} out, {watch['return']} back",
        "",
        f"Cheapest now: ${price:.0f} — {describe(now['min_item'])}",
    ]
    if now["min_nonstop"]:
        lines.append(f"Cheapest nonstop: ${now['min_nonstop']:.0f} — {describe(now['min_nonstop_item'])}")
    if prior.get("first_seen_price"):
        lines.append(f"First checked at ${prior['first_seen_price']:.0f}")
    lines += ["", "Why you're getting this:"] + [f"- {r}" for r in reasons]
    link = (now["min_item"] or {}).get("url") or (
        "https://www.google.com/travel/flights?q="
        f"Flights%20from%20{watch['origin']}%20to%20{watch['destination']}"
        f"%20on%20{watch['depart']}%20through%20{watch['return']}"
    )
    lines += ["", f"Book: {link}"]
    return "\n".join(lines)


# ── main ─────────────────────────────────────────────────────────────────────
def run_watch(watch: dict, state: dict, *, dry_run: bool, force: bool) -> str:
    key = watch["key"]
    prior = state.setdefault("watches", {}).setdefault(key, {})

    try:
        items = fetch_fares(watch)
    except Exception as exc:  # noqa: BLE001
        prior["last_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        prior["last_run"] = datetime.now(timezone.utc).isoformat()
        return f"{key}: FETCH FAILED — {prior['last_error']}"

    now = summarize(items, nonstop_only=watch.get("nonstop_only", False))
    prior.pop("last_error", None)
    prior["last_run"] = datetime.now(timezone.utc).isoformat()

    if now["min_price"] is None:
        return f"{key}: no usable fares in {now['checked']} results"

    should_alert, reasons = decide(watch, now, prior)
    if force and not should_alert:
        should_alert, reasons = True, ["manual --force check"]

    if prior.get("first_seen_price") is None:
        prior["first_seen_price"] = now["min_price"]
    prior["best_seen"] = min(
        [x for x in (prior.get("best_seen"), now["min_price"]) if x is not None]
    )
    prior["last_price"] = now["min_price"]
    prior["last_nonstop"] = now["min_nonstop"]
    history = prior.setdefault("history", [])
    history.append(
        {
            "ts": prior["last_run"],
            "min_price": now["min_price"],
            "min_nonstop": now["min_nonstop"],
        }
    )
    del history[:-240]

    line = (
        f"{key}: ${now['min_price']:.0f} cheapest"
        + (f", ${now['min_nonstop']:.0f} nonstop" if now["min_nonstop"] else "")
        + f" ({now['usable']}/{now['checked']} usable)"
    )

    if not should_alert:
        return line + " — no alert"

    message = build_message(watch, now, reasons, prior)
    if dry_run:
        return line + " — WOULD ALERT:\n" + message

    from notify_owner import notify_owner

    sent = notify_owner(message)
    if sent:
        prior["last_alert_price"] = now["min_price"]
        prior["last_alert_at"] = prior["last_run"]
        if now["min_nonstop"] is not None:
            prior["last_alert_nonstop"] = now["min_nonstop"]
    return line + (" — ALERT SENT" if sent else " — ALERT FAILED TO SEND")


def main() -> int:
    ap = argparse.ArgumentParser(description="Hourly flight fare watcher")
    ap.add_argument("--dry-run", action="store_true", help="check prices, never notify")
    ap.add_argument("--force", action="store_true", help="notify with the current best price")
    ap.add_argument("--status", action="store_true", help="print stored state and exit")
    args = ap.parse_args()

    state = load_state(STATE_FILE)

    if args.status:
        print(json.dumps(state, indent=2)[:4000])
        return 0

    results = [run_watch(w, state, dry_run=args.dry_run, force=args.force) for w in WATCHES]
    save_state(state, STATE_FILE)

    for line in results:
        print(line)

    if not args.dry_run and any("ALERT SENT" in r for r in results):
        try:
            append_to_daily_log("\n".join(results), section_name="Flight Watch")
        except Exception as exc:  # noqa: BLE001
            print(f"  [log] daily log append failed: {str(exc)[:80]}")

    return 0 if all("FAILED" not in r for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
