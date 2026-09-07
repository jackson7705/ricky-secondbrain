"""Thin wrapper around the `agent-browser` CLI.

One persistent Chrome profile holds the Skool login, so the crawler runs
headless forever after a single human sign-in. No Skool password is ever
stored by this code.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from typing import Any

from . import settings


class BrowserError(RuntimeError):
    pass


def _exe() -> str:
    exe = shutil.which("agent-browser")
    if not exe:
        raise BrowserError(
            "agent-browser not found. Install with: npm i -g agent-browser"
            "  (then: agent-browser install)"
        )
    return exe


def _cmd(args: list[str], *, headed: bool = False) -> list[str]:
    base = [
        _exe(),
        "--session",
        settings.SESSION,
        "--profile",
        str(settings.PROFILE_DIR),
    ]
    if headed:
        base.append("--headed")
    return base + args


def run(args: list[str], *, headed: bool = False, timeout: int = 120) -> str:
    proc = subprocess.run(
        _cmd(args, headed=headed),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise BrowserError(
            f"agent-browser {' '.join(args[:2])} failed: {proc.stderr.strip()[:400]}"
        )
    return proc.stdout


def open_url(url: str, *, headed: bool = False, wait_ms: int | None = None) -> None:
    run(["open", url], headed=headed)
    time.sleep((wait_ms if wait_ms is not None else settings.NAV_WAIT_MS) / 1000)


def eval_js(js: str, *, timeout: int = 120) -> Any:
    """Run JS in the page; returns parsed JSON when the result is JSON."""
    out = run(["eval", js], timeout=timeout).strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return out


def read_text(max_chars: int = 200_000) -> str:
    out = run(["--max-output", str(max_chars), "read"])
    return out.strip()


def current_url() -> str:
    out = run(["get", "url"]).strip()
    return out.splitlines()[-1].strip() if out else ""


def next_data() -> dict[str, Any] | None:
    """Return window.__NEXT_DATA__.props.pageProps (Skool is a Next.js app)."""
    raw = eval_js(
        "(() => { try { return JSON.stringify(window.__NEXT_DATA__.props.pageProps); }"
        " catch (e) { return ''; } })()"
    )
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def media_urls() -> list[str]:
    """Every iframe/video/source src on the page (video embeds live here)."""
    result = eval_js(
        "(() => JSON.stringify([...document.querySelectorAll('iframe,video,source,a')]"
        ".map(e => e.src || e.href || '').filter(Boolean)))()"
    )
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            return []
    return [u for u in (result or []) if isinstance(u, str)]


def save_state() -> None:
    settings.STATE_HOME.mkdir(parents=True, exist_ok=True)
    run(["state", "save", str(settings.STATE_FILE)])


def export_cookies_txt() -> int:
    """Write a Netscape cookies.txt (for yt-dlp on gated video hosts)."""
    out = run(["cookies", "get", "--json"])
    try:
        payload = json.loads(out)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise BrowserError(f"could not parse cookies output: {exc}") from exc
    cookies = payload.get("data", {}).get("cookies", payload.get("cookies", []))
    lines = ["# Netscape HTTP Cookie File", "# written by skool.browser"]
    for c in cookies:
        domain = c.get("domain", "")
        if not domain:
            continue
        include_sub = "TRUE" if domain.startswith(".") else "FALSE"
        expires = int(c.get("expires") or 0)
        if expires <= 0:
            expires = int(time.time()) + 86400 * 30
        lines.append(
            "\t".join(
                [
                    domain,
                    include_sub,
                    c.get("path", "/") or "/",
                    "TRUE" if c.get("secure") else "FALSE",
                    str(expires),
                    c.get("name", ""),
                    c.get("value", ""),
                ]
            )
        )
    settings.STATE_HOME.mkdir(parents=True, exist_ok=True)
    settings.COOKIES_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    settings.COOKIES_FILE.chmod(0o600)
    return len(cookies)


def close() -> None:
    try:
        run(["close"], timeout=30)
    except (BrowserError, subprocess.TimeoutExpired):
        pass
