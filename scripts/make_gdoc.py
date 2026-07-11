"""Create or update a Google Doc from a markdown file, via Drive HTML-import conversion.

Reuses the direct-integrations Google credentials (drive.file scope). This is the
reliable path while the gog CLI's OAuth client is broken (invalid_client).

CLI:
    uv run python make_gdoc.py create <markdown_path> <folder_id> "<title>"
    uv run python make_gdoc.py update <markdown_path> <doc_id>

Library:
    from make_gdoc import create_doc, update_doc
    link = create_doc(md_path, folder_id, title)
"""
from __future__ import annotations

import html
import sys
import tempfile
import time

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from integrations.drive_api import get_drive_service

DOC_MIME = "application/vnd.google-apps.document"


def _md_to_html(md_path: str) -> str:
    lines = open(md_path, encoding="utf-8").read().splitlines()
    out = ["<html><body>"]
    for ln in lines:
        s = ln.rstrip()
        if not s.strip():
            out.append("<p></p>")
        elif s.startswith("### "):
            out.append(f"<h3>{html.escape(s[4:])}</h3>")
        elif s.startswith("## "):
            out.append(f"<h2>{html.escape(s[3:])}</h2>")
        elif s.startswith("# "):
            out.append(f"<h1>{html.escape(s[2:])}</h1>")
        else:
            out.append(f"<p>{html.escape(s)}</p>")
    out.append("</body></html>")
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write("\n".join(out))
        return f.name


def _with_retry(fn, attempts: int = 5, delay: int = 12):
    last = None
    for i in range(attempts):
        try:
            return fn()
        except HttpError as e:
            last = e
            time.sleep(delay)
    raise last


def create_doc(md_path: str, folder_id: str, title: str) -> str:
    svc = get_drive_service()
    html_path = _md_to_html(md_path)
    meta = {"name": title, "parents": [folder_id], "mimeType": DOC_MIME}
    media = MediaFileUpload(html_path, mimetype="text/html", resumable=False)
    res = _with_retry(lambda: svc.files().create(
        body=meta, media_body=media, fields="id,webViewLink", supportsAllDrives=True).execute())
    return res.get("webViewLink")


def update_doc(md_path: str, doc_id: str) -> str:
    svc = get_drive_service()
    html_path = _md_to_html(md_path)
    media = MediaFileUpload(html_path, mimetype="text/html", resumable=False)
    res = _with_retry(lambda: svc.files().update(
        fileId=doc_id, media_body=media, fields="id,webViewLink", supportsAllDrives=True).execute())
    return res.get("webViewLink")


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "create":
        print(create_doc(sys.argv[2], sys.argv[3], sys.argv[4]))
    elif action == "update":
        print(update_doc(sys.argv[2], sys.argv[3]))
    else:
        sys.exit(f"unknown action: {action}")
