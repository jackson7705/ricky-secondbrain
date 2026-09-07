"""Walk a Skool classroom and capture every course, module and lesson.

Skool is a Next.js app, so each page ships its own data as JSON in
``window.__NEXT_DATA__``. We read that (resilient to CSS changes), and fall
back to the rendered DOM for page text and video embeds.

Output per group (under deliverables/skool/<group>/):
    manifest.json        courses + lessons + video sources
    raw/<page>.json      untouched pageProps, for when a shape surprises us
    lessons/<id>.md      lesson text content
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from . import browser, settings

LOCAL_TZ = UTC

ID_RE = re.compile(
    r"^(?:[0-9a-f]{16,40}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
    re.I,
)
URL_RE = re.compile(r"https?://[^\s\"'<>\\)]+")

VIDEO_HOSTS = (
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "loom.com",
    "wistia.com",
    "wistia.net",
    "vidyard.com",
    "cloudflarestream.com",
    "videodelivery.net",
    "video.skool.com",
    "d1z2jf7jlzjs58.cloudfront.net",
)
VIDEO_EXTS = (".mp4", ".m3u8", ".webm", ".mov", ".m4v")

TITLE_KEYS = ("title", "name", "displayName", "label")
BODY_KEYS = ("description", "content", "richContent", "body", "text", "markdown")
VIDEO_KEYS = ("videoLink", "videoLinkData", "videoUrl", "video", "videoLinks", "attachments")


def slugify(text: str, limit: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return (slug[:limit] or "untitled").strip("-")


def is_video_url(url: str) -> bool:
    low = url.lower().split("?")[0]
    return any(h in url.lower() for h in VIDEO_HOSTS) or low.endswith(VIDEO_EXTS)


def urls_in(value: Any) -> list[str]:
    """Every URL buried anywhere inside a JSON blob."""
    found: list[str] = []
    if isinstance(value, str):
        found.extend(URL_RE.findall(value))
    elif isinstance(value, dict):
        for v in value.values():
            found.extend(urls_in(v))
    elif isinstance(value, list):
        for v in value:
            found.extend(urls_in(v))
    return found


SKOOL_REFERER = "https://www.skool.com/"


def mux_url(video: dict[str, Any] | None) -> str | None:
    """Skool hosts video on Mux; the page hands us a signed playback token.

    The token is Referer-restricted (send SKOOL_REFERER) and expires in ~24h,
    so transcribe soon after crawling or re-crawl to refresh.
    """
    if not isinstance(video, dict):
        return None
    playback_id = video.get("playbackId")
    token = video.get("playbackToken")
    if playback_id and token:
        return f"https://stream.mux.com/{playback_id}.m3u8?token={token}"
    return None


def parse_rich_text(desc: str) -> str:
    """Skool lesson bodies are '[v2]' + a JSON rich-text doc."""
    if not desc:
        return ""
    raw = desc.strip()
    if raw.startswith("[v2]"):
        raw = raw[4:]
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        return desc
    parts: list[str] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            text = node.get("text")
            if isinstance(text, str):
                parts.append(text)
            url = node.get("url") or node.get("href")
            if isinstance(url, str) and url.startswith("http"):
                parts.append(f"<{url}>")
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(doc)
    return "\n".join(p for p in parts if p.strip())


def _first(meta: dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        val = meta.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def harvest_nodes(payload: Any) -> list[dict[str, Any]]:
    """Pull every course/module/lesson-shaped object out of pageProps.

    Skool objects look like {id, name, metadata: {...}, children: [...]}. We
    match on that shape rather than on exact key names so a Skool-side rename
    degrades to "fewer fields", not "pipeline broken".
    """
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(obj: Any) -> None:
        if isinstance(obj, list):
            for item in obj:
                visit(item)
            return
        if not isinstance(obj, dict):
            return
        node_id = obj.get("id")
        raw_meta = obj.get("metadata")
        meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
        looks_like_node = bool(meta) or any(isinstance(obj.get(k), str) for k in TITLE_KEYS)
        if isinstance(node_id, str) and ID_RE.match(node_id) and looks_like_node:
            if node_id not in seen:
                seen.add(node_id)
                title = _first(meta, TITLE_KEYS) or _first(obj, TITLE_KEYS)
                shallow = {k: v for k, v in obj.items() if k != "children"}
                videos = [
                    u
                    for u in urls_in({k: meta.get(k) or obj.get(k) for k in VIDEO_KEYS})
                    if is_video_url(u)
                ]
                if not videos:
                    videos = [u for u in urls_in(shallow) if is_video_url(u)]
                nodes.append(
                    {
                        "id": node_id,
                        "title": title,
                        "body": _first(meta, BODY_KEYS),
                        "kind": obj.get("type") or meta.get("type") or "",
                        "child_ids": [
                            c.get("id")
                            for c in (obj.get("children") or [])
                            if isinstance(c, dict) and isinstance(c.get("id"), str)
                        ],
                        "video_urls": sorted(set(videos)),
                    }
                )
        for value in obj.values():
            visit(value)

    visit(payload)
    return nodes


def _dump_raw(group: str, name: str, payload: Any) -> None:
    path = settings.group_dir(group) / "raw" / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False)[:8_000_000], encoding="utf-8")


def discover_courses(group: str) -> list[dict[str, Any]]:
    """Courses in /<group>/classroom, read from the page's own allCourses list."""
    browser.open_url(f"{settings.BASE_URL}/{group}/classroom")
    props = browser.next_data() or {}
    if props:
        _dump_raw(group, "classroom", props)

    courses: list[dict[str, Any]] = []
    for entry in props.get("allCourses") or []:
        if not isinstance(entry, dict):
            continue
        meta = entry.get("metadata") or {}
        slug = entry.get("name") or ""
        courses.append(
            {
                "id": entry.get("id", ""),
                "slug": slug,
                "title": meta.get("title") or slug,
                "modules": meta.get("numModules"),
                "has_access": bool(meta.get("hasAccess")),
                "url": f"{settings.BASE_URL}/{group}/classroom/{slug}",
            }
        )

    if courses:
        return courses

    # Fallback: older/other Skool layouts that render real course links.
    seen: dict[str, dict[str, Any]] = {}
    for url in browser.media_urls():
        pattern = rf"skool\.com/{re.escape(group)}/classroom/([0-9a-z]{{6,40}})"
        match = re.search(pattern, url, re.I)
        if match:
            cid = match.group(1)
            seen.setdefault(
                cid,
                {
                    "id": cid,
                    "slug": cid,
                    "title": cid,
                    "has_access": True,
                    "url": url.split("?")[0],
                },
            )
    for node in harvest_nodes(props):
        if node["id"] in seen and node["title"]:
            seen[node["id"]]["title"] = node["title"]
    return list(seen.values())


def walk_tree(
    node: Any, section: str = "", out: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Flatten Skool's {course, children} tree into an ordered lesson list.

    unitType 'set' is a module/section header; unitType 'module' is a lesson.
    """
    lessons = [] if out is None else out
    if not isinstance(node, dict):
        return lessons
    raw_unit = node.get("course")
    unit: dict[str, Any] = raw_unit if isinstance(raw_unit, dict) else {}
    raw_meta = unit.get("metadata")
    meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
    title = meta.get("title") or unit.get("name") or ""
    kind = unit.get("unitType")

    child_section = section
    if kind == "set":
        child_section = title
    elif kind == "module":
        lessons.append(
            {
                "id": unit.get("id", ""),
                "title": title,
                "section": section,
                "video_id": meta.get("videoId"),
                "has_access": bool(meta.get("hasAccess", 1)),
                "body": parse_rich_text(meta.get("desc") or ""),
            }
        )

    for child in node.get("children") or []:
        walk_tree(child, child_section, lessons)
    return lessons


def crawl_course(
    group: str, course: dict[str, Any], *, max_lessons: int | None = None
) -> dict[str, Any]:
    """Open a course, flatten its tree, then visit each lesson for video + text."""
    browser.open_url(course["url"])
    props = browser.next_data() or {}
    _dump_raw(group, f"course-{course['slug'] or course['id']}", props)

    found = walk_tree(props.get("course") or {})
    if not found:  # shape drift — fall back to the generic harvester
        found = [
            {
                "id": n["id"],
                "title": n["title"],
                "section": "",
                "video_id": None,
                "has_access": True,
                "body": n["body"],
            }
            for n in harvest_nodes(props)
            if n["id"] != course["id"]
        ]
    if max_lessons:
        found = found[:max_lessons]

    lessons: list[dict[str, Any]] = []
    for index, node in enumerate(found, start=1):
        lesson = _capture_lesson(group, course, node, index)
        if lesson:
            lessons.append(lesson)
        time.sleep(settings.POLITE_DELAY_S)

    course["lessons"] = lessons
    return course


def _capture_lesson(
    group: str, course: dict[str, Any], node: dict[str, Any], index: int
) -> dict[str, Any] | None:
    lesson_url = f"{course['url']}?md={node['id']}"
    try:
        browser.open_url(lesson_url)
        props = browser.next_data() or {}
        text = browser.read_text()
    except browser.BrowserError as exc:
        print(f"  ! lesson {node['id'][:10]}: {exc}")
        return None

    # The open lesson carries its own full metadata + signed video token.
    live: dict[str, Any] = next(
        (x for x in walk_tree(props.get("course") or {}) if x["id"] == node["id"]), node
    )
    title = live.get("title") or node["title"] or f"lesson-{index}"
    body = live.get("body") or node.get("body") or ""

    videos: list[str] = []
    signed = mux_url(props.get("video"))
    if signed:
        videos.append(signed)
    videos.extend(u for u in browser.media_urls() if is_video_url(u))
    videos.extend(u for u in urls_in(props) if is_video_url(u))

    slug = f"{index:03d}-{slugify(title)}"
    md_path = settings.group_dir(group) / "lessons" / f"{slug}.md"
    md_path.write_text(
        "\n".join(
            [
                "---",
                f"course: {course.get('title')}",
                f"section: {node.get('section', '')}",
                f"lesson: {title}",
                f"lesson_id: {node['id']}",
                f"url: {lesson_url}",
                "---",
                "",
                f"# {title}",
                "",
                body,
                "",
                "## Page text",
                "",
                text,
            ]
        ),
        encoding="utf-8",
    )

    marker = "video" if signed else ("link" if videos else "text-only")
    print(f"  · {index:>3}. {title[:52]:<54} [{marker}]")
    return {
        "index": index,
        "id": node["id"],
        "title": title,
        "section": node.get("section", ""),
        "slug": slug,
        "url": lesson_url,
        "markdown": str(md_path.relative_to(settings.group_dir(group))),
        "video_urls": list(dict.fromkeys(videos)),
        "needs_referer": bool(signed),
    }


def crawl(
    group: str, *, max_courses: int | None = None, max_lessons: int | None = None
) -> dict[str, Any]:
    root = settings.ensure_dirs(group)
    manifest_path = root / "manifest.json"
    manifest: dict[str, Any] = {
        "group": group,
        "crawled_at": datetime.now(LOCAL_TZ).isoformat(timespec="seconds"),
        "courses": [],
    }

    def save() -> None:
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    print(f"Discovering courses in /{group}/classroom ...")
    courses = discover_courses(group)
    if max_courses:
        courses = courses[:max_courses]
    print(f"Found {len(courses)} course(s).")
    save()
    if not courses:
        print(
            "  (none visible — signed out, wrong group slug, or Skool changed shape.\n"
            f"   Check: python -m skool.cli status  |  probe {settings.BASE_URL}/{group}/classroom)"
        )

    for course in courses:
        if not course.get("has_access", True):
            print(f"\n▸ {course.get('title')} — LOCKED (needs a higher level), skipping")
            continue
        modules = course.get("modules")
        print(f"\n▸ {course.get('title')}" + (f"  ({modules} modules)" if modules else ""))
        crawled = crawl_course(group, course, max_lessons=max_lessons)
        manifest["courses"].append(crawled)
        save()

    total = sum(len(c.get("lessons", [])) for c in manifest["courses"])
    videos = sum(
        1 for c in manifest["courses"] for lesson in c.get("lessons", []) if lesson["video_urls"]
    )
    print(
        f"\n✓ {len(manifest['courses'])} courses / {total} lessons / "
        f"{videos} with video → {manifest_path}"
    )
    return manifest


def load_manifest(group: str) -> dict[str, Any]:
    path = settings.group_dir(group) / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(
            f"no manifest for '{group}' — run: python -m skool.cli crawl {group}"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"manifest for '{group}' is malformed: {path}")
    return data
