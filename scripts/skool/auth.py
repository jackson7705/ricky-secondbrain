"""Skool login + session management.

Jason signs in once in a visible browser window (email/password, Google SSO,
2FA — whatever Skool asks for). The session persists in a Chrome profile dir
outside the repo, and every later run is headless and unattended.
"""

from __future__ import annotations

import time
from typing import Any

from . import browser, settings


def whoami() -> dict[str, Any] | None:
    """Return the logged-in Skool member object, or None when signed out."""
    browser.open_url(settings.BASE_URL + "/")
    props = browser.next_data()
    if not props:
        return None
    me = props.get("self") or props.get("currentUser") or props.get("user")
    return me if isinstance(me, dict) and me.get("id") else None


def describe(me: dict[str, Any] | None) -> str:
    if not me:
        return "signed out"
    meta = me.get("metadata") or {}
    name = me.get("name") or meta.get("fullName") or meta.get("firstName") or me.get("id")
    email = me.get("email") or meta.get("email") or ""
    return f"{name}{f' <{email}>' if email else ''}"


def login(wait_seconds: int = 420) -> bool:
    """Open a visible browser and wait for a human to finish signing in."""
    settings.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    print("Opening a browser window on skool.com/login ...")
    browser.open_url(settings.BASE_URL + "/login", headed=True, wait_ms=3000)
    print(
        "\n  → Sign in to Skool in that window (email, Google, 2FA — whatever it asks).\n"
        "    Ricky is watching; nothing is typed for you and no password is stored.\n"
    )
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        time.sleep(6)
        try:
            props = browser.next_data()
        except browser.BrowserError:
            continue
        me = (props or {}).get("self")
        if isinstance(me, dict) and me.get("id"):
            print(f"✓ Signed in as {describe(me)}")
            persist()
            return True
    print("✗ Timed out waiting for sign-in. Re-run `login` when you're ready.")
    return False


def persist() -> None:
    """Snapshot cookies + storage so yt-dlp and future runs can reuse them."""
    browser.save_state()
    count = browser.export_cookies_txt()
    print(f"✓ Session saved: {settings.STATE_FILE} ({count} cookies → {settings.COOKIES_FILE})")


def status() -> bool:
    me = whoami()
    print(f"Skool session: {describe(me)}")
    print(f"Profile dir:   {settings.PROFILE_DIR}")
    if me:
        persist()
    return bool(me)


def groups() -> list[dict[str, str]]:
    """Groups this account is a member of (used to pick the course source)."""
    browser.open_url(settings.BASE_URL + "/")
    found: dict[str, dict[str, str]] = {}
    for url in browser.media_urls():
        if "skool.com/" not in url:
            continue
        slug = url.split("skool.com/", 1)[1].split("?")[0].strip("/")
        if not slug or "/" in slug:
            continue
        if slug in {"login", "signup", "discovery", "settings", "pricing", "about", "help"}:
            continue
        found[slug] = {"slug": slug, "url": f"{settings.BASE_URL}/{slug}"}
    return sorted(found.values(), key=lambda g: g["slug"])
