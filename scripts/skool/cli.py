"""Skool course ingest CLI.

cd .claude/scripts
uv run python -m skool.cli doctor
uv run python -m skool.cli login
uv run python -m skool.cli crawl <group-slug>
uv run python -m skool.cli transcribe <group-slug> [--course "SEO"] [--limit 5]
uv run python -m skool.cli ingest <group-slug>       # crawl + transcribe
uv run python -m skool.cli index <group-slug>        # corpus index for synthesis
"""

from __future__ import annotations

import argparse
import shutil
import sys

from . import auth, browser, crawl, settings, transcribe


def cmd_doctor(_: argparse.Namespace) -> int:
    ok = True

    def check(label: str, good: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and good
        print(f"  [{'✓' if good else '✗'}] {label}{f' — {detail}' if detail else ''}")

    print("Skool ingest doctor\n")
    check(
        "agent-browser",
        bool(shutil.which("agent-browser")),
        shutil.which("agent-browser") or "npm i -g agent-browser",
    )
    check("ffmpeg", bool(shutil.which("ffmpeg")), shutil.which("ffmpeg") or "brew install ffmpeg")
    ytdlp = shutil.which("yt-dlp") or (shutil.which("uv") and "via `uv tool run yt-dlp`")
    check("yt-dlp", bool(ytdlp), str(ytdlp))
    key = settings.gemini_key()
    check("GEMINI_API_KEY", bool(key), f"...{key[-6:]}" if key else "add to scripts/.env")
    check("chrome profile", settings.PROFILE_DIR.exists(), str(settings.PROFILE_DIR))
    if shutil.which("agent-browser"):
        try:
            me = auth.whoami()
            check("skool session", bool(me), auth.describe(me))
        except browser.BrowserError as exc:
            check("skool session", False, str(exc)[:120])
    print("\n" + ("Ready." if ok else "Fix the ✗ rows above, then re-run."))
    return 0 if ok else 1


def cmd_login(args: argparse.Namespace) -> int:
    return 0 if auth.login(wait_seconds=args.wait) else 1


def cmd_status(_: argparse.Namespace) -> int:
    return 0 if auth.status() else 1


def cmd_groups(_: argparse.Namespace) -> int:
    for group in auth.groups():
        print(f"  {group['slug']:<32} {group['url']}")
    return 0


def cmd_crawl(args: argparse.Namespace) -> int:
    crawl.crawl(args.group, max_courses=args.max_courses, max_lessons=args.max_lessons)
    return 0


def cmd_transcribe(args: argparse.Namespace) -> int:
    transcribe.transcribe_group(args.group, course_filter=args.course, limit=args.limit)
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    crawl.crawl(args.group, max_courses=args.max_courses, max_lessons=args.max_lessons)
    transcribe.transcribe_group(args.group, course_filter=args.course, limit=args.limit)
    return cmd_index(args)


def cmd_index(args: argparse.Namespace) -> int:
    """Write a compact map of the corpus for the synthesis phase."""
    manifest = crawl.load_manifest(args.group)
    root = settings.group_dir(args.group)
    rows: list[str] = [
        f"# Skool corpus — {args.group}",
        "",
        "| Course | Lesson | Words | Transcript |",
        "| --- | --- | --- | --- |",
    ]
    total_words = 0
    for course in manifest.get("courses", []):
        ctitle = course.get("title") or course["id"]
        for lesson in course.get("lessons", []):
            slug = f"{crawl.slugify(ctitle, 40)}--{lesson['slug']}"
            path = root / "transcripts" / f"{slug}.md"
            words = len(path.read_text(encoding="utf-8").split()) if path.exists() else 0
            total_words += words
            rows.append(
                f"| {ctitle} | {lesson['title']} | {words:,} | "
                f"{'transcripts/' + path.name if path.exists() else '—'} |"
            )
    rows += ["", f"**Total transcribed words:** {total_words:,}"]
    out = root / "notes" / "00-corpus-index.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"✓ corpus index → {out}  ({total_words:,} words)")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """Dump one page's pageProps — how you learn a Skool shape you haven't seen."""
    import json
    from pathlib import Path as _Path

    browser.open_url(args.url)
    props = browser.next_data() or {}
    nodes = crawl.harvest_nodes(props)
    out = _Path(args.out or (settings.STATE_HOME / "probe.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(props, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"pageProps keys: {sorted(props.keys())[:25]}")
    print(f"harvested {len(nodes)} node(s):")
    for node in nodes[:15]:
        print(f"  {node['id'][:10]}  {node['title'][:48]:<50} videos={len(node['video_urls'])}")
    print(f"→ {out}")
    return 0


def cmd_close(_: argparse.Namespace) -> int:
    browser.close()
    print("✓ browser closed")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="skool", description="Skool course ingest for Ricky")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="check dependencies + session").set_defaults(func=cmd_doctor)

    p_login = sub.add_parser("login", help="open a browser and wait for a human sign-in")
    p_login.add_argument("--wait", type=int, default=420, help="seconds to wait (default 420)")
    p_login.set_defaults(func=cmd_login)

    sub.add_parser("status", help="who is signed in").set_defaults(func=cmd_status)
    sub.add_parser("groups", help="list groups this account can see").set_defaults(func=cmd_groups)
    sub.add_parser("close", help="close the browser session").set_defaults(func=cmd_close)

    p_probe = sub.add_parser("probe", help="dump a page's JSON (shape discovery)")
    p_probe.add_argument("url")
    p_probe.add_argument("--out", default="")
    p_probe.set_defaults(func=cmd_probe)

    def add_group(p: argparse.ArgumentParser) -> None:
        p.add_argument("group", help="Skool group slug, e.g. 'my-seo-group'")

    p_crawl = sub.add_parser("crawl", help="map classroom → manifest.json")
    add_group(p_crawl)
    p_crawl.add_argument("--max-courses", type=int, default=None)
    p_crawl.add_argument("--max-lessons", type=int, default=None)
    p_crawl.set_defaults(func=cmd_crawl)

    p_tr = sub.add_parser("transcribe", help="captions-or-Gemini transcripts for every lesson")
    add_group(p_tr)
    p_tr.add_argument("--course", default="", help="only courses whose title contains this")
    p_tr.add_argument("--limit", type=int, default=None, help="stop after N transcripts")
    p_tr.set_defaults(func=cmd_transcribe)

    p_all = sub.add_parser("ingest", help="crawl + transcribe + index")
    add_group(p_all)
    p_all.add_argument("--course", default="")
    p_all.add_argument("--limit", type=int, default=None)
    p_all.add_argument("--max-courses", type=int, default=None)
    p_all.add_argument("--max-lessons", type=int, default=None)
    p_all.set_defaults(func=cmd_ingest)

    p_idx = sub.add_parser("index", help="write notes/00-corpus-index.md")
    add_group(p_idx)
    p_idx.set_defaults(func=cmd_index)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except FileNotFoundError as exc:
        print(f"✗ {exc}")
        return 1
    except (browser.BrowserError, transcribe.TranscribeError) as exc:
        print(f"✗ {exc}")
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted — progress is on disk, re-run to resume")
        return 130


if __name__ == "__main__":
    sys.exit(main())
