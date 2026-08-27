"""Pull an invoice PDF out of Gmail and attach it to a QuickBooks bill.

STATUS (2026-08-26): `fetch_pdf` WORKS and is verified. `attach_to_bill` is
BLOCKED — Composio cannot upload files to QuickBooks by any route:

  - No upload tool exists. `QUICKBOOKS_UPDATE_ATTACHABLE` only edits metadata on
    an attachment that already exists; there is no CREATE_ATTACHABLE.
  - `composio proxy` JSON-encodes the request body. QuickBooks received a body
    starting with `"` on a plain-text query, which is how this was confirmed.
  - `proxy()` inside `composio run` is no better: its `normalizeFetchBody`
    base64-encodes any ArrayBuffer/TypedArray and calls `.text()` on a Blob, so
    raw multipart bytes cannot survive. FormData → 415 (the wrapper replaces the
    auto Content-Type); manual bytes → 400; even pure-ASCII multipart → 400.

QuickBooks' /upload endpoint requires genuine multipart/form-data, so the fix is
an HTTP client that speaks it directly, using a token Composio does not mediate:
run `qbo auth login` (interactive, Jason only), then send the multipart below
with that access token. The body construction here is already correct — only the
transport needs replacing.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import subprocess
import tempfile
import uuid
from pathlib import Path

from bills_config import AIRSENSE_GMAIL_ACCOUNT, QUICKBOOKS_ACCOUNT

QBO_COMPANY_ID = "9130357561108566"
UPLOAD_URL = f"https://quickbooks.api.intuit.com/v3/company/{QBO_COMPANY_ID}/upload"


def fetch_pdf(message_id: str, attachment_id: str, file_name: str) -> bytes:
    """Download one Gmail attachment and return its raw bytes."""
    proc = subprocess.run(
        [
            "composio", "execute", "GMAIL_GET_ATTACHMENT",
            "--account", AIRSENSE_GMAIL_ACCOUNT,
            "-d", json.dumps(
                {
                    "message_id": message_id,
                    "attachment_id": attachment_id,
                    "file_name": file_name,
                    "user_id": "me",
                }
            ),
        ],
        capture_output=True, text=True, timeout=180,
    )
    raw = proc.stdout
    start = raw.find("{")
    if start < 0:
        raise RuntimeError(f"GMAIL_GET_ATTACHMENT: no JSON — {raw[:200]}")
    result = json.loads(raw[start:])
    if not result.get("successful"):
        raise RuntimeError(f"GMAIL_GET_ATTACHMENT failed: {str(result.get('error'))[:200]}")

    data = result.get("data") or {}
    if result.get("outputFilePath") and Path(result["outputFilePath"]).exists():
        data = json.load(open(result["outputFilePath"]))

    # Composio usually stages the attachment in temp object storage and hands
    # back a presigned URL rather than inline bytes.
    url = _find_key(data, "s3url") or _find_key(data, "url")
    if isinstance(url, str) and url.startswith("http"):
        import urllib.request

        with urllib.request.urlopen(url, timeout=180) as response:
            return response.read()

    encoded = _find_key(data, "data") or _find_key(data, "attachmentData")
    if isinstance(encoded, str) and encoded:
        return base64.urlsafe_b64decode(encoded + "==")

    # Or a path to a file it already wrote to disk.
    for key in ("filePath", "path", "local_path"):
        path = _find_key(data, key)
        if isinstance(path, str) and Path(path).exists():
            return Path(path).read_bytes()

    raise RuntimeError(f"no attachment bytes in response: {json.dumps(data)[:300]}")


def _find_key(obj, target):
    if isinstance(obj, dict):
        if target in obj:
            return obj[target]
        for value in obj.values():
            found = _find_key(value, target)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_key(item, target)
            if found is not None:
                return found
    return None


def attach_to_bill(pdf_bytes: bytes, filename: str, bill_id: str, note: str = "") -> str:
    """Upload a PDF and link it to a bill. Returns the new Attachable id."""
    boundary = f"----airsense{uuid.uuid4().hex}"
    content_type = mimetypes.guess_type(filename)[0] or "application/pdf"

    metadata = {
        "AttachableRef": [{"EntityRef": {"type": "Bill", "value": str(bill_id)}}],
        "FileName": filename,
        "ContentType": content_type,
        "Category": "Document",
    }
    if note:
        metadata["Note"] = note

    # QuickBooks expects paired parts whose names share an index suffix.
    parts = bytearray()

    def add(name: str, payload: bytes, *, ctype: str, fname: str | None = None) -> None:
        disp = f'form-data; name="{name}"'
        if fname:
            disp += f'; filename="{fname}"'
        parts.extend(f"--{boundary}\r\n".encode())
        parts.extend(f"Content-Disposition: {disp}\r\n".encode())
        parts.extend(f"Content-Type: {ctype}\r\n\r\n".encode())
        parts.extend(payload)
        parts.extend(b"\r\n")

    add("file_metadata_01", json.dumps(metadata).encode(), ctype="application/json")
    add("file_content_01", pdf_bytes, ctype=content_type, fname=filename)
    parts.extend(f"--{boundary}--\r\n".encode())

    with tempfile.NamedTemporaryFile(suffix=".multipart", delete=False) as handle:
        handle.write(bytes(parts))
        body_path = handle.name

    try:
        proc = subprocess.run(
            [
                "composio", "proxy", UPLOAD_URL,
                "--toolkit", "quickbooks",
                "--account", QUICKBOOKS_ACCOUNT,
                "-X", "POST",
                "-H", f"Content-Type: multipart/form-data; boundary={boundary}",
                "-H", "Accept: application/json",
                "-d", f"@{body_path}",
            ],
            capture_output=True, text=True, timeout=300,
        )
    finally:
        Path(body_path).unlink(missing_ok=True)

    raw = proc.stdout
    start = raw.find("{")
    if start < 0:
        raise RuntimeError(f"upload: no JSON — {raw[:300]}")
    result = json.loads(raw[start:])

    responses = result.get("AttachableResponse") or []
    if responses and responses[0].get("Attachable"):
        return str(responses[0]["Attachable"]["Id"])
    if responses and responses[0].get("Fault"):
        raise RuntimeError(f"upload rejected: {json.dumps(responses[0]['Fault'])[:300]}")
    raise RuntimeError(f"unexpected upload response: {json.dumps(result)[:300]}")
