#!/usr/bin/env python3
"""boot_report.py — after a restart, tell Jason whether Ricky actually came back.

The point of this script is the bad news, not the good news. A restart used to
mean a drive to the office to find out what died; now the Mac says so itself.

Fires once per boot from com.jasonsecondbrain.boot-report (RunAtLoad). It waits
for the stack to settle, then sends ONE message naming anything still broken.

Three things have to be true for Ricky to be alive:
    BlueBubbles  — bound to :1234, or no iMessage reaches him
    Tailscale    — BackendState "Running", or the Mac is off the tailnet
                   and unreachable from outside the office
    chat engine  — com.jasonsecondbrain.chat holding a PID

Delivery is deliberately two-path. notify_owner routes through BlueBubbles,
which is one of the things that may be broken — so if that send fails we fall
back to driving Messages.app directly over AppleScript. Same iMessage thread,
completely independent of the BlueBubbles server.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent / ".env")

import config  # noqa: E402
from notify_owner import notify_owner  # noqa: E402

STATE_FILE = Path("/tmp/jasonsecondbrain/boot-report-last.txt")
LOG_FILE = Path("/tmp/jasonsecondbrain/boot-report.log")

# Only report if we're genuinely near a boot. launchd also runs RunAtLoad jobs
# when an agent is reloaded by hand, and a "Ricky's back!" text every time
# someone bootstraps the plist would train Jason to ignore the message.
BOOT_WINDOW_SECONDS = 900

SETTLE_TIMEOUT_SECONDS = 300  # how long to give the stack before judging it
POLL_INTERVAL_SECONDS = 10

TAILSCALE_BIN = "/Applications/Tailscale.app/Contents/MacOS/tailscale"
CHAT_LABEL = "com.jasonsecondbrain.chat"


def log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}\n")


def boot_epoch() -> int:
    """Seconds-since-epoch of the last boot, from kern.boottime."""
    out = subprocess.run(["sysctl", "-n", "kern.boottime"],
                         capture_output=True, text=True, timeout=10).stdout
    # e.g. '{ sec = 1758464061, usec = 0 } Sun Sep 21 09:34:21 2026'
    m = re.search(r"sec\s*=\s*(\d+)", out)
    if not m:
        raise RuntimeError(f"could not parse kern.boottime: {out!r}")
    return int(m.group(1))


# ── health probes ────────────────────────────────────────────────────────────
def bluebubbles_up() -> bool:
    """Any HTTP response means the server is binding the port. 401 counts —
    we're checking that it's alive, not that we're authorised."""
    try:
        urllib.request.urlopen("http://localhost:1234/", timeout=3)
        return True
    except urllib.error.HTTPError:
        return True  # it answered, which is the whole question
    except Exception:
        return False


def tailscale_up() -> bool:
    try:
        out = subprocess.run([TAILSCALE_BIN, "status", "--json"],
                             capture_output=True, text=True, timeout=15)
        if out.returncode != 0:
            return False
        import json
        return json.loads(out.stdout).get("BackendState") == "Running"
    except Exception:
        return False


def chat_engine_up() -> bool:
    """launchctl prints '<pid>\t<status>\t<label>'; a '-' in the PID column
    means loaded but not running."""
    try:
        out = subprocess.run(["/bin/launchctl", "list"],
                             capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return False
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[2].strip() == CHAT_LABEL:
            return parts[0].strip().isdigit()
    return False


CHECKS = [
    ("BlueBubbles", bluebubbles_up),
    ("Tailscale", tailscale_up),
    ("chat engine", chat_engine_up),
]


def wait_for_settle() -> tuple[dict[str, bool], int]:
    """Poll until everything is green or we run out of patience.

    Returns the final state and how long it took. Slow is normal here: after a
    cold boot BlueBubbles needs ~30s to bind and Tailscale a few seconds to
    negotiate, so an early snapshot would cry wolf.
    """
    started = time.time()
    state: dict[str, bool] = {}
    while True:
        state = {name: probe() for name, probe in CHECKS}
        elapsed = int(time.time() - started)
        if all(state.values()):
            return state, elapsed
        if elapsed >= SETTLE_TIMEOUT_SECONDS:
            return state, elapsed
        time.sleep(POLL_INTERVAL_SECONDS)


# ── delivery ─────────────────────────────────────────────────────────────────
def send_via_messages_app(text: str) -> bool:
    """Fallback path: drive Messages.app directly, so a dead BlueBubbles can
    still tell us it's dead. OWNER_IMESSAGE_GUID looks like
    'iMessage;-;+15551234567' — the handle is the last ';'-delimited field.
    """
    guid = (config.OWNER_IMESSAGE_GUID or "").strip()
    if not guid:
        return False
    handle = guid.split(";")[-1]
    if not handle:
        return False
    script = (
        'on run {targetHandle, targetText}\n'
        '  tell application "Messages"\n'
        '    set svc to 1st account whose service type = iMessage\n'
        '    send targetText to participant targetHandle of svc\n'
        '  end tell\n'
        'end run'
    )
    try:
        res = subprocess.run(["osascript", "-e", script, handle, text],
                             capture_output=True, text=True, timeout=60)
        if res.returncode == 0:
            return True
        log(f"Messages.app fallback failed: {res.stderr.strip()[:200]}")
        return False
    except Exception as exc:  # noqa: BLE001
        log(f"Messages.app fallback errored: {str(exc)[:200]}")
        return False


def compose(state: dict[str, bool], elapsed: int) -> str:
    down = [name for name, ok in state.items() if not ok]
    if not down:
        return (f"Back up after a restart — BlueBubbles, Tailscale and the chat "
                f"engine are all running. Took {elapsed}s.")
    # Name what's broken first; that's the part worth reading.
    up = [name for name, ok in state.items() if ok]
    broken = " and ".join(down)
    still_ok = ", ".join(up) if up else "nothing else"
    return (f"Restarted, but {broken} did not come back after {elapsed}s. "
            f"Running: {still_ok}. The watchdogs keep retrying — if this doesn't "
            f"clear on its own the Mac needs a look.")


def main() -> int:
    try:
        booted = boot_epoch()
    except Exception as exc:  # noqa: BLE001
        log(f"cannot read boot time, skipping: {exc}")
        return 0

    uptime = int(time.time() - booted)
    if uptime > BOOT_WINDOW_SECONDS:
        log(f"uptime {uptime}s > {BOOT_WINDOW_SECONDS}s — agent reload, not a boot; staying quiet")
        return 0

    # One report per boot, even if the agent is reloaded inside the window.
    if STATE_FILE.exists():
        try:
            if STATE_FILE.read_text().strip() == str(booted):
                log(f"already reported boot {booted} — staying quiet")
                return 0
        except Exception:  # noqa: BLE001
            pass

    log(f"boot {booted} detected (uptime {uptime}s) — waiting for stack to settle")
    state, elapsed = wait_for_settle()
    log(f"settled after {elapsed}s: {state}")

    message = compose(state, elapsed)

    if notify_owner(message):
        log("sent via notify_owner")
    elif send_via_messages_app(message):
        log("notify_owner failed — sent via Messages.app fallback")
    else:
        # Nothing got through. Leave the evidence on disk; this log is the only
        # remaining record that the boot happened and the alert never landed.
        log(f"ALL DELIVERY FAILED — message was: {message}")

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(str(booted))
    return 0


if __name__ == "__main__":
    sys.exit(main())
