#!/usr/bin/env python3
"""notify_owner.py — send a one-way notification to the owner on whatever chat
surface they use. This is how autonomous jobs (loose_ends, fathom_sweep,
eod_email, briefs) ping the owner WITHOUT assuming a Mac / BlueBubbles.

Routing: OWNER_NOTIFY_CHANNEL in .env picks the surface
    bluebubbles | telegram | discord | slack
If unset, the first configured surface is auto-selected (bluebubbles first for
back-compat, then telegram, discord, slack).

Programmatic:
    from notify_owner import notify_owner
    notify_owner("your message")           # returns True on success

CLI (handy for testing a teammate's setup):
    uv run python notify_owner.py "hello from Ricky"
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent / ".env")

import config  # noqa: E402


def _post_json(url: str, payload: dict, headers: dict | None = None, timeout: int = 20) -> bool:
    body = json.dumps(payload).encode()
    hdrs = {"Content-Type": "application/json", **(headers or {})}
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=body, headers=hdrs), timeout=timeout)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  [notify] POST failed: {str(exc)[:80]}")
        return False


# ── per-surface senders ──────────────────────────────────────────────────────
def _send_bluebubbles(text: str) -> bool:
    if not (config.BLUEBUBBLES_URL and config.BLUEBUBBLES_PASSWORD and config.OWNER_IMESSAGE_GUID):
        return False
    import time
    url = (f"{config.BLUEBUBBLES_URL}/api/v1/message/text"
           f"?password={urllib.parse.quote(config.BLUEBUBBLES_PASSWORD)}")
    return _post_json(url, {
        "chatGuid": config.OWNER_IMESSAGE_GUID, "message": text[:1600],
        "method": "apple-script", "tempGuid": f"notify-{int(time.time() * 1000)}",
    })


def _send_telegram(text: str) -> bool:
    if not (config.TELEGRAM_BOT_TOKEN and config.OWNER_TELEGRAM_CHAT_ID):
        return False
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    return _post_json(url, {"chat_id": config.OWNER_TELEGRAM_CHAT_ID,
                            "text": text[:4096], "disable_web_page_preview": True})


def _send_discord(text: str) -> bool:
    if not config.OWNER_DISCORD_WEBHOOK_URL:
        return False
    return _post_json(config.OWNER_DISCORD_WEBHOOK_URL, {"content": text[:2000]})


def _send_slack(text: str) -> bool:
    if not (config.SLACK_BOT_TOKEN and config.OWNER_SLACK_NOTIFY_CHANNEL):
        return False
    return _post_json("https://slack.com/api/chat.postMessage",
                      {"channel": config.OWNER_SLACK_NOTIFY_CHANNEL, "text": text},
                      headers={"Authorization": f"Bearer {config.SLACK_BOT_TOKEN}"})


_SENDERS = {
    "bluebubbles": _send_bluebubbles,
    "telegram": _send_telegram,
    "discord": _send_discord,
    "slack": _send_slack,
}
# Auto-detect order when OWNER_NOTIFY_CHANNEL is unset (bluebubbles first = back-compat)
_AUTO_ORDER = ["bluebubbles", "telegram", "discord", "slack"]


def _configured(channel: str) -> bool:
    return {
        "bluebubbles": bool(config.BLUEBUBBLES_URL and config.BLUEBUBBLES_PASSWORD and config.OWNER_IMESSAGE_GUID),
        "telegram": bool(config.TELEGRAM_BOT_TOKEN and config.OWNER_TELEGRAM_CHAT_ID),
        "discord": bool(config.OWNER_DISCORD_WEBHOOK_URL),
        "slack": bool(config.SLACK_BOT_TOKEN and config.OWNER_SLACK_NOTIFY_CHANNEL),
    }.get(channel, False)


def resolve_channel() -> str | None:
    """The surface job notifications will use, or None if nothing is configured."""
    pref = config.OWNER_NOTIFY_CHANNEL
    if pref and _configured(pref):
        return pref
    if pref and not _configured(pref):
        print(f"  [notify] OWNER_NOTIFY_CHANNEL='{pref}' not fully configured — falling back")
    for ch in _AUTO_ORDER:
        if _configured(ch):
            return ch
    return None


def notify_owner(text: str) -> bool:
    """Send `text` to the owner on their configured surface. True on success."""
    channel = resolve_channel()
    if channel is None:
        print("  [notify] no notification surface configured — message not sent:\n" + text)
        return False
    ok = _SENDERS[channel](text)
    print(f"  [notify] {'sent via ' + channel + ' ✓' if ok else 'send via ' + channel + ' FAILED'}")
    return ok


if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]) or "Test notification from Ricky."
    print(f"resolved channel: {resolve_channel()}")
    sys.exit(0 if notify_owner(msg) else 1)
