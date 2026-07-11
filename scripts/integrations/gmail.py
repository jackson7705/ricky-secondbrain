"""
Gmail Direct Integration for Second Brain.

Access to Gmail via Google API. Shares OAuth token with Calendar.
Supports reading emails and creating drafts (gmail.readonly + gmail.compose).

Usage:
    uv run python -m integrations.gmail list --max 5
    uv run python -m integrations.gmail unread
    uv run python -m integrations.gmail urgent --hours 2
    uv run python -m integrations.gmail search --query "from:someone"
"""

from __future__ import annotations

import base64
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

# Add parent dir for config imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import LOCAL_TZ, now_local  # noqa: E402
from sanitize import sanitize_external_text  # noqa: E402
from shared import with_retry  # noqa: E402


@dataclass
class Email:
    """Represents an email message."""

    id: str
    thread_id: str
    subject: str
    sender: str
    sender_email: str
    date: datetime
    snippet: str
    body: str | None = None
    labels: list[str] = field(default_factory=list)
    is_unread: bool = False


def get_gmail_service() -> Any:
    """Build authenticated Gmail API service."""
    from googleapiclient.discovery import build  # type: ignore[import-untyped]

    from integrations.auth import get_google_credentials

    creds = get_google_credentials()
    service: Any = build("gmail", "v1", credentials=creds)
    return service


def _parse_sender(sender_full: str) -> tuple[str, str]:
    """Parse 'Name <email>' format into (name, email)."""
    if "<" in sender_full:
        sender = sender_full.split("<")[0].strip().strip('"')
        sender_email = sender_full.split("<")[1].rstrip(">")
    else:
        sender = sender_full
        sender_email = sender_full
    return sender, sender_email


def _extract_body(payload: dict[str, Any]) -> str:
    """Extract email body text from payload (handles multipart MIME)."""
    body_data = payload.get("body", {}).get("data")
    if body_data:
        return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")

    parts = payload.get("parts", [])
    for part in parts:
        mime_type = part.get("mimeType", "")
        if mime_type == "text/plain":
            data = part.get("body", {}).get("data")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        elif mime_type in ("multipart/alternative", "multipart/mixed"):
            result = _extract_body(part)
            if result:
                return result

    return ""


def get_email_details(service: Any, msg_id: str, include_body: bool = False) -> Email | None:
    """Get details for a single email."""
    try:
        fmt = "full" if include_body else "metadata"
        msg: dict[str, Any] = with_retry(
            lambda: service.users()
            .messages()
            .get(
                userId="me",
                id=msg_id,
                format=fmt,
                metadataHeaders=["From", "Subject", "Date"],
            )
            .execute()
        )

        headers: dict[str, str] = {
            h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])
        }

        sender, sender_email = _parse_sender(headers.get("From", ""))

        # Parse date robustly
        date_str = headers.get("Date", "")
        try:
            date = parsedate_to_datetime(date_str)
        except Exception:
            date = now_local()

        body = None
        if include_body:
            body = _extract_body(msg.get("payload", {}))

        label_ids: list[str] = msg.get("labelIds", [])

        return Email(
            id=msg["id"],
            thread_id=msg["threadId"],
            subject=headers.get("Subject", "(no subject)"),
            sender=sender,
            sender_email=sender_email,
            date=date,
            snippet=msg.get("snippet", ""),
            body=body,
            labels=label_ids,
            is_unread="UNREAD" in label_ids,
        )
    except Exception as e:
        print(f"Error getting email {msg_id}: {e}")
        return None


def list_emails(
    max_results: int = 10,
    query: str = "",
    unread_only: bool = False,
    hours_ago: int | None = None,
) -> list[Email]:
    """
    List emails matching criteria.

    Args:
        max_results: Maximum emails to return
        query: Gmail search query (e.g. "from:someone subject:important")
        unread_only: Only return unread emails
        hours_ago: Only emails from last N hours
    """
    service = get_gmail_service()

    q_parts: list[str] = []
    if query:
        q_parts.append(query)
    if unread_only:
        q_parts.append("is:unread")
    if hours_ago:
        after_date = now_local() - timedelta(hours=hours_ago)
        q_parts.append(f"after:{after_date.strftime('%Y/%m/%d')}")

    full_query = " ".join(q_parts) if q_parts else None

    result: dict[str, Any] = with_retry(
        lambda: service.users()
        .messages()
        .list(userId="me", maxResults=max_results, q=full_query)
        .execute()
    )

    messages: list[dict[str, str]] = result.get("messages", [])
    emails: list[Email] = []

    for msg in messages:
        email = get_email_details(service, msg["id"])
        if email:
            emails.append(email)

    return emails


def get_unread_count() -> int:
    """Get count of unread emails in the Primary inbox tab.

    Scope is intentionally limited to `category:primary` — social,
    promotions, updates, and forums tabs are ignored per user preference.
    """
    service = get_gmail_service()

    result: dict[str, Any] = with_retry(
        lambda: service.users()
        .messages()
        .list(userId="me", q="is:unread in:inbox category:primary", maxResults=1)
        .execute()
    )

    count: int = result.get("resultSizeEstimate", 0)
    return count


def check_for_urgent_emails(
    important_senders: list[str] | None = None,
    hours_ago: int = 2,
) -> list[Email]:
    """
    Check for urgent emails that need attention.

    Flags emails from important senders or with urgent keywords in subject.
    Scoped to the Primary inbox tab only.
    """
    recent = list_emails(
        max_results=20,
        unread_only=True,
        hours_ago=hours_ago,
        query="category:primary",
    )

    urgent_keywords = ["urgent", "asap", "important", "action required", "deadline"]
    urgent: list[Email] = []

    for email in recent:
        reason = ""

        # Check important senders
        if important_senders:
            for sender in important_senders:
                if sender.lower() in email.sender_email.lower():
                    reason = f"From important sender: {email.sender}"
                    break

        # Check urgent keywords in subject
        if not reason:
            subject_lower = email.subject.lower()
            for keyword in urgent_keywords:
                if keyword in subject_lower:
                    reason = f"Urgent keyword: {keyword}"
                    break

        if reason:
            email.body = reason
            urgent.append(email)

    return urgent


@dataclass
class Attachment:
    """Represents an email attachment."""

    id: str
    filename: str
    mime_type: str
    size: int


def list_attachments(msg_id: str) -> list[Attachment]:
    """List all attachments on a Gmail message."""
    service = get_gmail_service()

    msg: dict[str, Any] = with_retry(
        lambda: service.users()
        .messages()
        .get(userId="me", id=msg_id, format="full")
        .execute()
    )

    attachments: list[Attachment] = []

    def _walk_parts(parts: list[dict[str, Any]]) -> None:
        for part in parts:
            body = part.get("body", {})
            attachment_id = body.get("attachmentId")
            filename = part.get("filename", "")
            if attachment_id and filename:
                attachments.append(Attachment(
                    id=attachment_id,
                    filename=filename,
                    mime_type=part.get("mimeType", "application/octet-stream"),
                    size=body.get("size", 0),
                ))
            # Recurse into nested multipart
            if part.get("parts"):
                _walk_parts(part["parts"])

    payload = msg.get("payload", {})
    _walk_parts(payload.get("parts", []))

    return attachments


def download_attachment(msg_id: str, attachment_id: str, output_path: Path) -> Path:
    """
    Download a Gmail attachment to disk.

    Args:
        msg_id: Gmail message ID containing the attachment
        attachment_id: Attachment ID from list_attachments()
        output_path: Full path (including filename) to save the attachment

    Returns:
        Path to the downloaded file
    """
    service = get_gmail_service()

    result: dict[str, Any] = with_retry(
        lambda: service.users()
        .messages()
        .attachments()
        .get(userId="me", messageId=msg_id, id=attachment_id)
        .execute()
    )

    file_data = base64.urlsafe_b64decode(result["data"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(file_data)
    return output_path


def get_thread_id(msg_id: str) -> str | None:
    """Resolve a Gmail message ID to its thread ID."""
    service = get_gmail_service()
    try:
        msg: dict[str, Any] = with_retry(
            lambda: service.users()
            .messages()
            .get(userId="me", id=msg_id, format="minimal")
            .execute()
        )
        return msg.get("threadId")
    except Exception:
        return None


def delete_gmail_draft(draft_id: str) -> bool:
    """Delete a Gmail draft by its ID. Returns True if deleted, False on error."""
    service = get_gmail_service()
    try:
        with_retry(
            lambda: service.users().drafts().delete(userId="me", id=draft_id).execute()
        )
        return True
    except Exception as e:
        print(f"Warning: failed to delete Gmail draft {draft_id}: {e}")
        return False


def _extract_email_address(addr: str) -> str:
    """Extract bare email address from 'Name <email>' format."""
    if "<" in addr:
        return addr.split("<")[1].rstrip(">").strip().lower()
    return addr.strip().lower()


def _encode_address(addr: str) -> str:
    """Encode an email address with non-ASCII display name for MIME headers.

    Handles addresses like '"Display Name" <user@example.com>' by RFC 2047
    encoding the display name while keeping the email address intact.
    """
    from email.header import Header
    from email.utils import formataddr, parseaddr

    name, email_addr = parseaddr(addr)
    if not email_addr:
        return addr
    # Only encode if the display name has non-ASCII characters
    try:
        name.encode("ascii")
        return addr  # Pure ASCII, no encoding needed
    except UnicodeEncodeError:
        return formataddr((str(Header(name, "utf-8")), email_addr))


def create_gmail_draft(
    to: str,
    subject: str,
    body: str,
    thread_id: str | None = None,
    message_id: str | None = None,
    attachments: list[str] | None = None,
) -> dict[str, str]:
    """
    Create a Gmail draft, optionally threaded on an existing conversation.

    When message_id is provided (reply mode), builds a Reply-All draft by
    fetching the original message's From/To/Cc headers and including all
    participants (excluding the authenticated user's own email).

    Args:
        to: Recipient email (e.g. "Name <email@example.com>" or just "email@example.com")
        subject: Email subject line
        body: Plain text body of the draft
        thread_id: Gmail thread ID to attach the draft to (for replies)
        message_id: Gmail message ID of the message being replied to (for In-Reply-To header)
        attachments: List of file paths to attach to the draft

    Returns:
        Dict with 'draft_id', 'message_id', and 'thread_id' of the created draft.
    """
    import email.mime.base
    import email.mime.multipart
    import email.mime.text
    import mimetypes

    service = get_gmail_service()

    # Build the MIME message - use multipart if attachments, plain text otherwise
    if attachments:
        mime_msg = email.mime.multipart.MIMEMultipart()
        mime_msg.attach(email.mime.text.MIMEText(body))
        for filepath in attachments:
            path = Path(filepath)
            content_type, _ = mimetypes.guess_type(str(path))
            if content_type is None:
                content_type = "application/octet-stream"
            main_type, sub_type = content_type.split("/", 1)
            with open(path, "rb") as f:
                att = email.mime.base.MIMEBase(main_type, sub_type)
                att.set_payload(f.read())
            import email.encoders
            email.encoders.encode_base64(att)
            att.add_header("Content-Disposition", "attachment", filename=path.name)
            mime_msg.attach(att)
    else:
        mime_msg = email.mime.text.MIMEText(body)
    mime_msg["subject"] = subject

    # Set threading headers and build Reply-All recipients if replying
    if message_id:
        try:
            original = with_retry(
                lambda: service.users()
                .messages()
                .get(
                    userId="me",
                    id=message_id,
                    format="metadata",
                    metadataHeaders=["Message-ID", "From", "To", "Cc"],
                )
                .execute()
            )
            headers = {h["name"]: h["value"] for h in original.get("payload", {}).get("headers", [])}

            # Threading headers
            original_msg_id = headers.get("Message-ID")
            if original_msg_id:
                mime_msg["In-Reply-To"] = original_msg_id
                mime_msg["References"] = original_msg_id

            # Reply-All: gather all participants, exclude the authenticated user's email
            profile = with_retry(
                lambda: service.users().getProfile(userId="me").execute()
            )
            my_email = profile.get("emailAddress", "").lower()

            # To = original sender (the person we're replying to)
            # If the original message was sent by us, reply to the original
            # recipients instead (first address in the To header)
            original_from = headers.get("From", to)
            if _extract_email_address(original_from) == my_email:
                # We're replying to our own sent message - use original To as reply target
                original_to = headers.get("To", to)
                first_to = original_to.split(",")[0].strip()
                reply_to = first_to if "@" in first_to else to
            else:
                reply_to = original_from

            # Cc = everyone else on the thread (original To + Cc, minus us and the sender)
            seen = {_extract_email_address(reply_to), my_email}
            cc_addrs: list[str] = []
            for header_name in ("To", "Cc"):
                raw = headers.get(header_name, "")
                if raw:
                    for addr in raw.split(","):
                        addr = addr.strip()
                        # Skip non-address entries like "undisclosed-recipients:;"
                        if not addr or "@" not in addr:
                            continue
                        if _extract_email_address(addr) not in seen:
                            cc_addrs.append(addr)
                            seen.add(_extract_email_address(addr))

            mime_msg["to"] = _encode_address(reply_to)
            if cc_addrs:
                mime_msg["cc"] = ", ".join(_encode_address(a) for a in cc_addrs)
        except Exception:
            # Fallback: just use the provided 'to' address
            mime_msg["to"] = _encode_address(to)
    else:
        mime_msg["to"] = _encode_address(to)

    # Encode as base64url
    raw = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode("ascii")

    # Build the draft body
    draft_body: dict[str, Any] = {"message": {"raw": raw}}
    if thread_id:
        draft_body["message"]["threadId"] = thread_id

    result: dict[str, Any] = with_retry(
        lambda: service.users().drafts().create(userId="me", body=draft_body).execute()
    )

    return {
        "draft_id": result["id"],
        "message_id": result["message"]["id"],
        "thread_id": result["message"].get("threadId", ""),
    }


def send_draft(draft_id: str) -> dict[str, str]:
    """Send an existing Gmail draft (gmail.compose scope covers this).

    HIGH-STAKES / OUTWARD-FACING: only ever call this AFTER Jason has explicitly
    approved this specific draft. Never send autonomously — the end-of-day sweep
    only creates drafts; sending is a separate, human-approved step.
    """
    service = get_gmail_service()
    sent: dict[str, Any] = with_retry(
        lambda: service.users().drafts().send(userId="me", body={"id": draft_id}).execute()
    )
    return {"message_id": sent.get("id", ""), "thread_id": sent.get("threadId", "")}


def create_gmail_draft_from_file(filepath: str | Path) -> dict[str, str]:
    """
    Create a Gmail draft by reading a markdown draft file.

    Parses YAML frontmatter for recipient, subject, source_id (message ID),
    and extracts the reply body from the '## Draft Reply' section.
    Writes gmail_draft_id back into the frontmatter to prevent duplicates.

    Args:
        filepath: Path to the markdown draft file in drafts/active/

    Returns:
        Dict with 'draft_id', 'message_id', and 'thread_id' of the created draft.

    Raises:
        ValueError: If the file is missing required fields or isn't an email draft.
    """
    filepath = Path(filepath)
    content = filepath.read_text(encoding="utf-8")

    # Parse frontmatter
    meta: dict[str, str] = {}
    body_start = 0
    if content.startswith("---"):
        end = content.index("---", 3)
        fm_block = content[3:end].strip()
        body_start = end + 3
        for line in fm_block.splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                meta[key.strip()] = val.strip()

    if meta.get("type") != "email":
        raise ValueError(f"Not an email draft (type={meta.get('type', 'unknown')})")

    if meta.get("gmail_draft_id"):
        raise ValueError(f"Gmail draft already exists: {meta['gmail_draft_id']}")

    recipient = meta.get("recipient", "")
    subject = meta.get("subject", "")
    source_id = meta.get("source_id", "")

    if not recipient or not subject:
        raise ValueError(f"Missing recipient or subject in frontmatter: {filepath.name}")

    # Extract body from ## Draft Reply section
    rest = content[body_start:]
    marker = "## Draft Reply"
    if marker not in rest:
        raise ValueError(f"No '## Draft Reply' section found in {filepath.name}")
    draft_body = rest.split(marker, 1)[1].strip()

    # Resolve thread_id and find the last message in the thread to reply to
    thread_id = get_thread_id(source_id) if source_id else None
    reply_to_msg_id = source_id  # fallback: reply to the source message

    if thread_id:
        # Get the last message in the thread so the draft appears at the bottom
        try:
            service = get_gmail_service()
            thread_data: dict[str, Any] = with_retry(
                lambda: service.users()
                .threads()
                .get(userId="me", id=thread_id, format="minimal")
                .execute()
            )
            messages = thread_data.get("messages", [])
            if messages:
                reply_to_msg_id = messages[-1]["id"]
        except Exception:
            pass  # Fall back to source_id

    # Create the Gmail draft
    result = create_gmail_draft(
        to=recipient,
        subject=subject,
        body=draft_body,
        thread_id=thread_id,
        message_id=reply_to_msg_id or None,
    )

    # Write gmail_draft_id back into frontmatter
    if result.get("draft_id"):
        import re
        updated, count = re.subn(
            r"^(status:\s*(?:active|draft))",
            rf"\1\ngmail_draft_id: {result['draft_id']}",
            content,
            count=1,
            flags=re.MULTILINE,
        )
        if count:
            filepath.write_text(updated, encoding="utf-8")

    return result


def get_thread_messages(thread_id: str) -> list[Email]:
    """Get all messages in a Gmail thread, ordered chronologically."""
    service = get_gmail_service()

    thread_data: dict[str, Any] = with_retry(
        lambda: service.users()
        .threads()
        .get(userId="me", id=thread_id, format="full")
        .execute()
    )

    emails: list[Email] = []
    for msg in thread_data.get("messages", []):
        headers: dict[str, str] = {
            h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])
        }
        sender, sender_email = _parse_sender(headers.get("From", ""))

        date_str = headers.get("Date", "")
        try:
            date = parsedate_to_datetime(date_str)
        except Exception:
            date = now_local()

        body = _extract_body(msg.get("payload", {}))
        label_ids: list[str] = msg.get("labelIds", [])

        emails.append(Email(
            id=msg["id"],
            thread_id=msg["threadId"],
            subject=headers.get("Subject", "(no subject)"),
            sender=sender,
            sender_email=sender_email,
            date=date,
            snippet=msg.get("snippet", ""),
            body=body,
            labels=label_ids,
            is_unread="UNREAD" in label_ids,
        ))

    # Sort chronologically (oldest first)
    emails.sort(key=lambda e: e.date)
    return emails


def _sanitize_text(text: str) -> str:
    """Replace unicode whitespace chars that break Windows charmap encoding."""
    return text.replace("\u202f", " ").replace("\u00a0", " ")


def format_thread_for_context(emails: list[Email], max_body_chars: int = 1500) -> str:
    """Format a thread of emails as a readable conversation."""
    if not emails:
        return "No messages in thread."

    subject = sanitize_external_text(emails[0].subject, "gmail")
    lines: list[str] = [f"Thread: {subject} ({len(emails)} messages)\n"]

    for i, email in enumerate(emails, 1):
        date_local = email.date.astimezone(LOCAL_TZ) if email.date.tzinfo else email.date
        if "DRAFT" in email.labels:
            sent_tag = " [DRAFT]"
        elif "SENT" in email.labels:
            sent_tag = " [SENT]"
        else:
            sent_tag = ""
        sender = sanitize_external_text(email.sender, "gmail")
        lines.append(
            f"[{i}] From: {sender} <{email.sender_email}>{sent_tag}\n"
            f"    Date: {date_local.strftime('%Y-%m-%d %H:%M')}"
        )
        body = email.body or email.snippet
        if body:
            if len(body) > max_body_chars:
                body = body[:max_body_chars] + "..."
            lines.append(sanitize_external_text(_sanitize_text(body), "gmail"))
        lines.append("")  # blank line between messages

    return "\n".join(lines)


def check_sent_reply(thread_id: str, after_timestamp: str) -> str | None:
    """
    Check if the authenticated user sent a reply in a Gmail thread after a given time.

    Args:
        thread_id: The Gmail thread ID to check
        after_timestamp: ISO format timestamp — only look for replies after this time

    Returns:
        The reply text if a reply was sent, None otherwise.
    """
    service = get_gmail_service()

    try:
        thread_data: dict[str, Any] = with_retry(
            lambda: service.users()
            .threads()
            .get(userId="me", id=thread_id, format="full")
            .execute()
        )
    except Exception as e:
        print(f"Error fetching thread {thread_id}: {e}")
        return None

    after_dt = datetime.fromisoformat(after_timestamp)

    # Normalize after_dt to LOCAL_TZ for timezone-safe comparison
    if after_dt.tzinfo:
        after_tz = after_dt.astimezone(LOCAL_TZ)
    else:
        after_tz = after_dt.replace(tzinfo=LOCAL_TZ)

    messages: list[dict[str, Any]] = thread_data.get("messages", [])
    for msg in messages:
        label_ids: list[str] = msg.get("labelIds", [])
        # Only look at messages actually sent - must have SENT, must NOT be a DRAFT
        if "SENT" not in label_ids or "DRAFT" in label_ids:
            continue

        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        date_str = headers.get("Date", "")
        try:
            msg_date = parsedate_to_datetime(date_str)
        except Exception:
            continue

        # Ensure msg_date is timezone-aware for comparison
        if msg_date.tzinfo is None:
            msg_date = msg_date.replace(tzinfo=LOCAL_TZ)

        # Check if this sent message is after our timestamp
        if msg_date > after_tz:
            body = _extract_body(msg.get("payload", {}))
            if body:
                return body

    return None


def _owner_replied_in_thread(service: Any, thread_id: str, after: datetime) -> bool:
    """Check if the authenticated user sent any reply in a thread after the given datetime."""
    try:
        thread_data: dict[str, Any] = with_retry(
            lambda: service.users()
            .threads()
            .get(userId="me", id=thread_id, format="minimal")
            .execute()
        )
    except Exception:
        return False

    for msg in thread_data.get("messages", []):
        label_ids: list[str] = msg.get("labelIds", [])
        if "SENT" not in label_ids:
            continue
        # Check if the sent message is after the incoming email
        # internalDate is ms since epoch
        internal_date = msg.get("internalDate")
        if internal_date:
            msg_dt = datetime.fromtimestamp(int(internal_date) / 1000, tz=LOCAL_TZ)
            # Normalize both to LOCAL_TZ for comparison
            after_tz = after.astimezone(LOCAL_TZ) if after.tzinfo else after.replace(tzinfo=LOCAL_TZ)
            if msg_dt > after_tz:
                return True
    return False


def get_important_unreplied_emails(
    hours_ago: int = 4,
    max_results: int = 10,
) -> list[Email]:
    """
    Get recent emails that the authenticated user hasn't replied to yet.

    Returns emails from the inbox that are:
    - Received in the last N hours
    - Not sent by the authenticated user
    - In threads where the user hasn't already replied

    Importance filtering is done by Claude based on USER.md criteria.
    """
    service = get_gmail_service()

    after_date = now_local() - timedelta(hours=hours_ago)
    q = (
        f"in:inbox category:primary after:{after_date.strftime('%Y/%m/%d')} "
        "-from:me"
    )

    try:
        result: dict[str, Any] = with_retry(
            lambda: service.users()
            .messages()
            .list(userId="me", maxResults=max_results, q=q)
            .execute()
        )
    except Exception as e:
        print(f"Error listing unreplied emails: {e}")
        return []

    messages_list: list[dict[str, str]] = result.get("messages", [])
    emails: list[Email] = []

    # Track threads we've already seen to avoid duplicates
    seen_threads: set[str] = set()

    for msg_ref in messages_list:
        email = get_email_details(service, msg_ref["id"], include_body=True)
        if not email:
            continue

        # Skip if we already have a message from this thread
        if email.thread_id in seen_threads:
            continue
        seen_threads.add(email.thread_id)

        # Skip threads where the owner already replied — fetch thread metadata
        # and check if any message after this one has the SENT label
        if _owner_replied_in_thread(service, email.thread_id, email.date):
            continue

        emails.append(email)

    return emails


def format_emails_for_context(emails: list[Email], max_chars: int = 2000) -> str:
    """Format emails for inclusion in Claude's context prompt."""
    if not emails:
        return "No emails found."

    output: list[str] = []
    chars = 0

    for email in emails:
        date_local = email.date.astimezone(LOCAL_TZ) if email.date.tzinfo else email.date
        subject = sanitize_external_text(email.subject, "gmail")
        sender = sanitize_external_text(email.sender, "gmail")
        snippet = sanitize_external_text(email.snippet[:100], "gmail")
        entry = (
            f"- **{subject}** [thread_id: {email.thread_id}]\n"
            f"  From: {sender} <{email.sender_email}>\n"
            f"  Date: {date_local.strftime('%Y-%m-%d %H:%M')}\n"
            f"  {'[UNREAD] ' if email.is_unread else ''}{snippet}"
        )

        if chars + len(entry) > max_chars:
            remaining = len(emails) - len(output)
            output.append(f"\n... and {remaining} more emails")
            break

        output.append(entry)
        chars += len(entry)

    return "\n\n".join(output)


# CLI for testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Gmail integration")
    parser.add_argument("command", choices=["auth", "list", "unread", "urgent", "search"])
    parser.add_argument("--max", type=int, default=10)
    parser.add_argument("--query", default="")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--unread", action="store_true")

    args = parser.parse_args()

    if args.command == "auth":
        service = get_gmail_service()
        print("Authentication successful!")

    elif args.command == "list":
        result_emails = list_emails(
            max_results=args.max, query=args.query, unread_only=args.unread, hours_ago=args.hours
        )
        print(format_emails_for_context(result_emails))

    elif args.command == "unread":
        count = get_unread_count()
        print(f"Unread emails: {count}")

    elif args.command == "urgent":
        urgent_emails = check_for_urgent_emails(hours_ago=args.hours)
        if urgent_emails:
            print(f"Found {len(urgent_emails)} potentially urgent emails:")
            print(format_emails_for_context(urgent_emails))
        else:
            print("No urgent emails found")

    elif args.command == "search":
        if not args.query:
            print("--query required for search command")
            sys.exit(1)
        result_emails = list_emails(max_results=args.max, query=args.query)
        print(format_emails_for_context(result_emails))
