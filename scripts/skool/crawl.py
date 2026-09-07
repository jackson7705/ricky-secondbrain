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
from typing import Any

from . import browser, settings

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


def discover_courses(group: str) -> list[dict[str, str]]:
    """Course cards on /<group>/classroom."""
    browser.open_url(f"{settings.BASE_URL}/{group}/classroom")
    props = browser.next_data()
    if props:
        _dump_raw(group, "classroom", props)
    courses: dict[str, dict[str, str]] = {}

    for url in browser.media_urls():
        match = re.search(rf"skool\.com/{re.escape(group)}/classroom/([0-9a-f]{{8,40}})", url)
        if match:
            cid = match.group(1)
            courses.setdefault(cid, {"id": cid, "title": "", "url": url.split("?")[0]})

    for node in harvest_nodes(props or {}):
        cid = node["id"]
        if cid in courses and node["title"]:
            courses[cid]["title"] = node["title"]

    return list(courses.values())


def crawl_course(
    group: str, course: dict[str, str], *, max_lessons: int | None = None
) -> dict[str, Any]:
    """Open a course, enumerate its lessons, capture text + video sources."""
    course_url = course.get("url") or f"{settings.BASE_URL}/{group}/classroom/{course['id']}"
    browser.open_url(course_url)
    props = browser.next_data() or {}
    _dump_raw(group, f"course-{course['id']}", props)

    nodes = harvest_nodes(props)
    title_by_id = {n["id"]: n["title"] for n in nodes if n["title"]}
    course["title"] = course.get("title") or title_by_id.get(course["id"], "") or course["id"]

    # Lesson candidates: every node that isn't the course itself, in page order.
    lesson_ids = [n["id"] for n in nodes if n["id"] != course["id"]]
    for url in browser.media_urls():
        match = re.search(r"[?&]md=([0-9a-f]{8,40})", url)
        if match and match.group(1) not in lesson_ids:
            lesson_ids.append(match.group(1))
    if max_lessons:
        lesson_ids = lesson_ids[:max_lessons]

    node_by_id = {n["id"]: n for n in nodes}
    lessons: list[dict[str, Any]] = []
    for index, lesson_id in enumerate(lesson_ids, start=1):
        node = node_by_id.get(
            lesson_id, {"id": lesson_id, "title": "", "body": "", "video_urls": []}
        )
        lesson = _capture_lesson(group, course, node, index)
        if lesson:
            lessons.append(lesson)
        time.sleep(settings.POLITE_DELAY_S)

    course["lessons"] = lessons  # type: ignore[assignment]
    return course


def _capture_lesson(
    group: str, course: dict[str, str], node: dict[str, Any], index: int
) -> dict[str, Any] | None:
    lesson_url = f"{settings.BASE_URL}/{group}/classroom/{course['id']}?md={node['id']}"
    try:
        browser.open_url(lesson_url)
        text = browser.read_text()
        page_urls = browser.media_urls()
        props = browser.next_data() or {}
    except browser.BrowserError as exc:
        print(f"  ! lesson {node['id']}: {exc}")
        return None

    page_nodes = harvest_nodes(props)
    this_node = next((n for n in page_nodes if n["id"] == node["id"]), None) or node
    title = this_node.get("title") or node.get("title") or f"lesson-{index}"

    videos = set(node.get("video_urls") or [])
    videos.update(this_node.get("video_urls") or [])
    videos.update(u for u in page_urls if is_video_url(u))
    videos.update(u for u in urls_in(props) if is_video_url(u))

    slug = f"{index:03d}-{slugify(title)}"
    body = this_node.get("body") or node.get("body") or ""
    md_path = settings.group_dir(group) / "lessons" / f"{slug}.md"
    md_path.write_text(
        "\n".join(
            [
                "---",
                f"course: {course.get('title') or course['id']}",
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

    print(f"  · {slug}  ({len(videos)} video source{'s' if len(videos) != 1 else ''})")
    return {
        "index": index,
        "id": node["id"],
        "title": title,
        "slug": slug,
        "url": lesson_url,
        "markdown": str(md_path.relative_to(settings.group_dir(group))),
        "video_urls": sorted(videos),
    }


def crawl(
    group: str, *, max_courses: int | None = None, max_lessons: int | None = None
) -> dict[str, Any]:
    root = settings.ensure_dirs(group)
    manifest_path = root / "manifest.json"
    manifest: dict[str, Any] = {"group": group, "courses": []}

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
        print(f"\n▸ {course.get('title') or course['id']}")
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
