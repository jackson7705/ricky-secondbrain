"""
LinkedIn Direct Integration for Second Brain.

Posting on Jason's behalf via LinkedIn's REST API. OAuth 2.0 with the
`w_member_social` + `openid profile` scopes. Token is stored locally at
`integrations/linkedin_token.json` — same convention as Google.

Critically: **this module never posts automatically.** It exposes functions
that a caller (aeo-authority-content's publish.py) invokes only after an
explicit approval step. See `docs/LINKEDIN_SETUP.md` for the one-time app
creation flow.

Usage pattern:
    from integrations.linkedin_api import post_text_share
    result = post_text_share("post body here", visibility="PUBLIC")
    # result = {"post_urn": "urn:li:share:...", "url": "https://linkedin.com/..."}
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import (  # noqa: E402
    INTEGRATIONS_DIR,
    LINKEDIN_CLIENT_ID,
    LINKEDIN_CLIENT_SECRET,
    LINKEDIN_SCOPES,
)

LINKEDIN_API_BASE = "https://api.linkedin.com"
LINKEDIN_AUTH_BASE = "https://www.linkedin.com/oauth/v2"
LINKEDIN_TOKEN_FILE = INTEGRATIONS_DIR / "linkedin_token.json"


def _load_token() -> dict[str, Any]:
    if not LINKEDIN_TOKEN_FILE.exists():
        raise RuntimeError(
            "LinkedIn token not found. Run `uv run python setup_auth.py --linkedin` "
            "to authenticate."
        )
    return json.loads(LINKEDIN_TOKEN_FILE.read_text())


def _save_token(data: dict[str, Any]) -> None:
    LINKEDIN_TOKEN_FILE.write_text(json.dumps(data, indent=2))


def _refresh_if_needed(token: dict[str, Any]) -> dict[str, Any]:
    """LinkedIn access tokens last ~60 days. If we're within 1 day of expiry and
    we have a refresh token, swap it. Otherwise the caller re-auths."""
    import httpx

    expires_at = int(token.get("expires_at", 0))
    if expires_at - time.time() > 86400:  # >1 day left
        return token
    refresh_token = token.get("refresh_token")
    if not refresh_token:
        # LinkedIn doesn't always issue refresh tokens — caller needs to re-auth.
        raise RuntimeError(
            "LinkedIn token expired and no refresh_token available. "
            "Re-run setup_auth.py --linkedin to renew."
        )
    resp = httpx.post(
        f"{LINKEDIN_AUTH_BASE}/accessToken",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": LINKEDIN_CLIENT_ID,
            "client_secret": LINKEDIN_CLIENT_SECRET,
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    token["access_token"] = data["access_token"]
    token["expires_at"] = int(time.time()) + int(data.get("expires_in", 5184000))
    if "refresh_token" in data:
        token["refresh_token"] = data["refresh_token"]
    _save_token(token)
    return token


def _headers(token: dict[str, Any]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token['access_token']}",
        "X-Restli-Protocol-Version": "2.0.0",
        "Content-Type": "application/json",
        "LinkedIn-Version": "202504",
    }


def get_member_urn() -> str:
    """Return Jason's LinkedIn member URN (cached in the token file on first fetch)."""
    import httpx

    token = _refresh_if_needed(_load_token())
    if token.get("member_urn"):
        return token["member_urn"]

    # OIDC `userinfo` endpoint returns the user's `sub` field which LinkedIn maps
    # to the member ID. Requires the `openid profile` scopes on the token.
    resp = httpx.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {token['access_token']}"},
        timeout=20,
    )
    resp.raise_for_status()
    info = resp.json()
    member_id = info.get("sub")
    if not member_id:
        raise RuntimeError(f"Couldn't resolve LinkedIn member URN from userinfo: {info}")
    urn = f"urn:li:person:{member_id}"
    token["member_urn"] = urn
    _save_token(token)
    return urn


def post_text_share(
    text: str,
    visibility: str = "PUBLIC",
) -> dict[str, str]:
    """Post a plain-text LinkedIn share on the authenticated user's behalf.

    Args:
        text: The post body. Max ~3000 chars per LinkedIn's limits.
        visibility: "PUBLIC" or "CONNECTIONS".

    Returns:
        dict with:
          - `post_urn`: the LinkedIn URN of the created post
          - `url`: a public URL to the post (best-effort; LinkedIn's rewrite
                   of the share URN is sometimes delayed, the URN is authoritative)
    """
    import httpx

    if not text or not text.strip():
        raise ValueError("Cannot post empty text to LinkedIn.")
    if len(text) > 3000:
        raise ValueError(f"LinkedIn text is {len(text)} chars; max is 3000.")
    if visibility not in ("PUBLIC", "CONNECTIONS"):
        raise ValueError("visibility must be 'PUBLIC' or 'CONNECTIONS'")

    token = _refresh_if_needed(_load_token())
    author = get_member_urn()

    body = {
        "author": author,
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": text},
                "shareMediaCategory": "NONE",
            },
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": visibility},
    }

    resp = httpx.post(
        f"{LINKEDIN_API_BASE}/v2/ugcPosts",
        headers=_headers(token),
        json=body,
        timeout=30,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"LinkedIn POST failed ({resp.status_code}): {resp.text}")

    post_urn = resp.headers.get("x-restli-id") or resp.json().get("id")
    if not post_urn:
        raise RuntimeError(f"LinkedIn accepted the post but returned no URN: {resp.text}")

    # Best-effort URL — the numeric activity ID embedded in the share URN maps to
    # /feed/update/<urn>/.
    public_url = f"https://www.linkedin.com/feed/update/{post_urn}/"
    return {"post_urn": post_urn, "url": public_url}


def build_authorization_url(redirect_uri: str, state: str) -> str:
    """Return the OAuth authorization URL that setup_auth.py opens in a browser."""
    from urllib.parse import urlencode

    params = {
        "response_type": "code",
        "client_id": LINKEDIN_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": " ".join(LINKEDIN_SCOPES),
    }
    return f"{LINKEDIN_AUTH_BASE}/authorization?{urlencode(params)}"


def exchange_code_for_token(code: str, redirect_uri: str) -> dict[str, Any]:
    """Called by setup_auth.py after LinkedIn redirects back with the auth code."""
    import httpx

    resp = httpx.post(
        f"{LINKEDIN_AUTH_BASE}/accessToken",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": LINKEDIN_CLIENT_ID,
            "client_secret": LINKEDIN_CLIENT_SECRET,
        },
        timeout=20,
    )
    if resp.status_code >= 400:
        # LinkedIn puts the real reason in the response body — surface it so
        # setup_auth.py can tell Jason exactly what LinkedIn rejected.
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise RuntimeError(
            f"LinkedIn token exchange failed ({resp.status_code}): {detail}"
        )
    data = resp.json()
    token = {
        "access_token": data["access_token"],
        "expires_at": int(time.time()) + int(data.get("expires_in", 5184000)),
    }
    if "refresh_token" in data:
        token["refresh_token"] = data["refresh_token"]
    if "refresh_token_expires_in" in data:
        token["refresh_token_expires_at"] = int(time.time()) + int(
            data["refresh_token_expires_in"]
        )
    _save_token(token)
    # Populate the member URN so we don't need an extra roundtrip on first post
    try:
        get_member_urn()
    except Exception:
        pass
    return token


def is_authenticated() -> bool:
    try:
        _refresh_if_needed(_load_token())
        return True
    except Exception:
        return False
