"""
Publish an approved LinkedIn draft to Jason's LinkedIn feed.

Hard rules (per the "always confirm before filing" memory):

1. The draft file's YAML frontmatter MUST have `status: approved`. Any other
   value and this script refuses.
2. The script prints the post body first and requires one of:
   - the `--yes` flag (for chat-driven flows where Ricky confirmed with Jason
     verbally before calling this script)
   - OR an interactive `y` on stdin
3. Once posted, the frontmatter is updated with the LinkedIn URN + URL, and
   the file is moved from `drafts/active/` to `drafts/sent/`. No double-post.

Usage:
    uv run python publish.py path/to/draft.md          # interactive confirm
    uv run python publish.py path/to/draft.md --yes    # chat-approved
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SKILL_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _SKILL_DIR.parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))


def parse_frontmatter(content: str) -> tuple[dict[str, str], str]:
    """Minimal YAML frontmatter parser (flat key:value only)."""
    if not content.startswith("---"):
        raise ValueError("Draft is missing a YAML frontmatter block.")
    try:
        end = content.index("---", 3)
    except ValueError as e:
        raise ValueError("Draft frontmatter block is not closed with '---'.") from e

    meta: dict[str, str] = {}
    for line in content[3:end].splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    body = content[end + 3:].lstrip("\n")
    return meta, body


def extract_post_text(body: str) -> str:
    """Extract the actual LinkedIn post text from the body.

    Convention: the draft file has a `## Draft Post` header followed by the
    post text, and ends before any `Suggested hashtags:` / `Word count:` /
    `Creative brief:` metadata lines.
    """
    marker = "## Draft Post"
    if marker not in body:
        raise ValueError("Draft body must contain a '## Draft Post' section.")
    post = body.split(marker, 1)[1].strip()

    # Trim off trailing metadata lines if present (same convention the skill
    # uses for output). Anything starting with 'Suggested hashtags:',
    # 'Word count:', 'Creative brief:' ends the post body.
    stop_patterns = (
        r"^Suggested hashtags:",
        r"^Word count:",
        r"^Creative brief:",
        r"^Data anchor:",
    )
    lines: list[str] = []
    for line in post.splitlines():
        if any(re.match(p, line.strip()) for p in stop_patterns):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def update_frontmatter(content: str, updates: dict[str, str]) -> str:
    """Return `content` with frontmatter updated/appended with keys from `updates`."""
    meta, body = parse_frontmatter(content)
    meta.update(updates)
    fm_lines = ["---"]
    for k, v in meta.items():
        # Wrap values that contain special chars in double quotes.
        if any(c in v for c in ":#[]{}"):
            v_out = f'"{v}"'
        else:
            v_out = v
        fm_lines.append(f"{k}: {v_out}")
    fm_lines.append("---")
    return "\n".join(fm_lines) + "\n\n" + body


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish an approved LinkedIn draft.")
    parser.add_argument("draft", type=Path, help="Path to the draft markdown file.")
    parser.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Skip the interactive confirmation (use only when Jason has just "
            "explicitly said 'ship it' in chat)."
        ),
    )
    parser.add_argument(
        "--visibility",
        default="PUBLIC",
        choices=["PUBLIC", "CONNECTIONS"],
        help="LinkedIn post visibility.",
    )
    args = parser.parse_args()

    if not args.draft.exists():
        print(f"[error] draft file not found: {args.draft}")
        return 2

    content = args.draft.read_text()
    meta, body = parse_frontmatter(content)

    # Gate 1: file must be a linkedin draft
    if meta.get("type") != "linkedin":
        print(f"[error] draft type is {meta.get('type')!r}, not 'linkedin'. Refusing to publish.")
        return 2

    # Gate 2: status must be approved
    if meta.get("status") != "approved":
        print(
            f"[error] draft status is {meta.get('status')!r}. Must be 'approved' before publishing.\n"
            f"        Jason: edit the file, change 'status: active' → 'status: approved', save, re-run."
        )
        return 2

    # Gate 3: don't re-post a draft that was already posted
    if meta.get("linkedin_post_urn"):
        print(
            f"[error] draft was already published at {meta['linkedin_post_urn']}. "
            "Refusing to double-post."
        )
        return 2

    post_text = extract_post_text(body)
    if not post_text:
        print("[error] post body is empty. Nothing to publish.")
        return 2
    if len(post_text) > 3000:
        print(f"[error] post body is {len(post_text)} chars; LinkedIn's max is 3000.")
        return 2

    # Gate 4: interactive or --yes
    print("=" * 60)
    print("LinkedIn post preview")
    print("=" * 60)
    print(post_text)
    print("=" * 60)
    print(f"Visibility: {args.visibility}")
    print(f"Length:     {len(post_text)} chars")
    print()

    if not args.yes:
        try:
            reply = input("Publish to LinkedIn now? [y/N] ").strip().lower()
        except EOFError:
            reply = ""
        if reply != "y":
            print("Aborted. No post was sent.")
            return 1

    # Actually post
    from integrations.linkedin_api import post_text_share

    try:
        result = post_text_share(post_text, visibility=args.visibility)
    except Exception as e:
        print(f"[error] LinkedIn POST failed: {e}")
        return 3

    # Write the LinkedIn metadata back into the frontmatter
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    updates = {
        "status": "sent",
        "linkedin_post_urn": result["post_urn"],
        "linkedin_url": result["url"],
        "published_at": now,
    }
    updated = update_frontmatter(content, updates)

    # Move from drafts/active/ to drafts/sent/ if it's in active
    drafts_dir = args.draft.parent
    if drafts_dir.name == "active":
        sent_dir = drafts_dir.parent / "sent"
        sent_dir.mkdir(parents=True, exist_ok=True)
        dest = sent_dir / args.draft.name
        dest.write_text(updated)
        args.draft.unlink()
        final_path = dest
    else:
        args.draft.write_text(updated)
        final_path = args.draft

    print()
    print("Posted.")
    print(f"  URN:  {result['post_urn']}")
    print(f"  URL:  {result['url']}")
    print(f"  File: {final_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
