"""Turn every lesson video into a timestamped transcript.

Cheapest path first:
  1. Existing captions (YouTube auto-subs etc.) via yt-dlp — free, instant.
  2. Otherwise download the audio, chunk it, and transcribe with Gemini.

Every step is cached on disk, so a run that dies at lesson 47 of 120 picks up
where it left off.
"""

from __future__ import annotations

import base64
import json
import re
import shutil
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import crawl, settings

TS_RE = re.compile(r"\[\s*(\d{1,2}):(\d{2})(?::\s*(\d{2}))?\s*\]")

PROMPT = (
    "Transcribe this audio verbatim. Rules:\n"
    "- Insert a [MM:SS] timestamp at the start of every new topic or roughly every 30 seconds.\n"
    "- Label distinct speakers as Speaker 1 / Speaker 2 when more than one person talks.\n"
    "- Keep every specific: tool names, URLs, numbers, thresholds, prompts read aloud.\n"
    "- Do not summarise, do not add commentary, do not skip filler content — verbatim only.\n"
    "- If a stretch is silence or music, write [silence] once and continue.\n"
    "Output the transcript text only."
)


class TranscribeError(RuntimeError):
    pass


# --------------------------------------------------------------------------- tools


def ytdlp_cmd() -> list[str]:
    exe = shutil.which("yt-dlp")
    if exe:
        return [exe]
    uv = shutil.which("uv")
    if uv:
        return [uv, "tool", "run", "yt-dlp"]
    raise TranscribeError("yt-dlp not available (install uv or `brew install yt-dlp`)")


def _ytdlp(args: list[str], *, timeout: int = 1800) -> subprocess.CompletedProcess[str]:
    cmd = ytdlp_cmd() + ["--no-playlist", "--no-warnings", "--ignore-config"]
    if settings.COOKIES_FILE.exists():
        cmd += ["--cookies", str(settings.COOKIES_FILE)]
    return subprocess.run(cmd + args, capture_output=True, text=True, timeout=timeout)


def _ffprobe_duration(path: Path) -> float:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 0.0


# --------------------------------------------------------------------------- captions


def _vtt_to_text(path: Path) -> str:
    lines: list[str] = []
    stamp = ""
    last = ""
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line in {"WEBVTT"} or line.startswith(("Kind:", "Language:", "NOTE")):
            continue
        if "-->" in line:
            start = line.split("-->")[0].strip().split(".")[0]
            parts = start.split(":")
            stamp = f"[{parts[0]}:{parts[1]}:{parts[2]}]" if len(parts) == 3 else f"[{start}]"
            continue
        text = re.sub(r"<[^>]+>", "", line).strip()
        if not text or text == last:
            continue
        last = text
        lines.append(f"{stamp} {text}" if stamp and (len(lines) % 8 == 0) else text)
        stamp = ""
    return "\n".join(lines)


def try_captions(url: str, workdir: Path, slug: str) -> str | None:
    out = workdir / f"{slug}"
    proc = _ytdlp(
        [
            "--skip-download",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            "en.*,en",
            "--sub-format",
            "vtt",
            "-o",
            str(out) + ".%(ext)s",
            url,
        ],
        timeout=300,
    )
    vtts = sorted(workdir.glob(f"{slug}*.vtt"))
    if not vtts:
        if proc.returncode != 0:
            err = proc.stderr.strip().splitlines()
            print(f"    (no captions: {err[-1][:120] if err else 'none published'})")
        return None
    text = _vtt_to_text(vtts[0])
    for extra in vtts:
        extra.unlink(missing_ok=True)
    return text if len(text) > 200 else None


# --------------------------------------------------------------------------- audio


def download_audio(url: str, workdir: Path, slug: str) -> Path | None:
    target = workdir / f"{slug}.src"
    existing = sorted(workdir.glob(f"{slug}.src.*"))
    if existing:
        return existing[0]
    proc = _ytdlp(["-f", "bestaudio/best", "-o", str(target) + ".%(ext)s", url])
    files = sorted(workdir.glob(f"{slug}.src.*"))
    if not files:
        tail = (proc.stderr or proc.stdout).strip().splitlines()
        print(f"    ! download failed: {tail[-1][:160] if tail else 'unknown error'}")
        return None
    return files[0]


def chunk_audio(source: Path, workdir: Path, slug: str) -> list[tuple[Path, int]]:
    duration = _ffprobe_duration(source)
    span = settings.CHUNK_SECONDS
    chunks: list[tuple[Path, int]] = []
    starts = list(range(0, max(int(duration), 1), span)) or [0]
    for i, start in enumerate(starts):
        out = workdir / f"{slug}.chunk{i:03d}.ogg"
        if not out.exists():
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-y",
                    "-ss",
                    str(start),
                    "-t",
                    str(span),
                    "-i",
                    str(source),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "libopus",
                    "-b:a",
                    "16k",
                    str(out),
                ],
                capture_output=True,
                text=True,
            )
        if out.exists() and out.stat().st_size > 2000:
            chunks.append((out, start))
    return chunks


# --------------------------------------------------------------------------- gemini


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001 - any cert lookup failure falls back to defaults
        return ssl.create_default_context()


def _post_json(url: str, body: bytes) -> tuple[int, bytes]:
    """POST JSON, preferring curl.

    The python.org/uv Pythons on macOS often ship without a usable root-cert
    bundle, which kills urllib against Google's API. curl uses the system trust
    store and always works here; urllib is the fallback.
    """
    curl = shutil.which("curl")
    if curl:
        with tempfile.TemporaryDirectory() as tmp:
            payload = Path(tmp) / "payload.json"
            payload.write_bytes(body)
            out = Path(tmp) / "resp.json"
            proc = subprocess.run(
                [
                    curl, "-sS", "-X", "POST", url,
                    "-H", "Content-Type: application/json",
                    "--data-binary", f"@{payload}",
                    "-o", str(out), "-w", "%{http_code}",
                    "--max-time", "900",
                ],
                capture_output=True, text=True, timeout=960,
            )
            if proc.returncode != 0:
                raise TranscribeError(f"curl failed: {proc.stderr.strip()[:200]}")
            status = int(proc.stdout.strip() or 0)
            return status, out.read_bytes() if out.exists() else b""

    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=900, context=_ssl_context()) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except urllib.error.URLError as exc:
        raise TranscribeError(f"Gemini unreachable: {exc}") from exc


def gemini_transcribe(chunk: Path, *, retries: int = 4) -> str:
    key = settings.gemini_key()
    if not key:
        raise TranscribeError(
            "GEMINI_API_KEY not found (checked scripts/.env and ai-seo-agent-skills/.env)"
        )
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": PROMPT},
                    {
                        "inline_data": {
                            "mime_type": "audio/ogg",
                            "data": base64.b64encode(chunk.read_bytes()).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 65536},
    }
    url = f"{settings.GEMINI_ENDPOINT}/{settings.TRANSCRIBE_MODEL}:generateContent?key={key}"
    body = json.dumps(payload).encode("utf-8")

    for attempt in range(retries):
        status, raw = _post_json(url, body)
        if status == 200:
            data = json.loads(raw.decode("utf-8"))
            candidates = data.get("candidates") or []
            if not candidates:
                raise TranscribeError(f"Gemini returned no candidates: {str(data)[:200]}")
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts).strip()
            if candidates[0].get("finishReason") == "MAX_TOKENS":
                text += "\n\n[transcript truncated — lower SKOOL_CHUNK_SECONDS and re-run]"
            return text
        if status in (429, 500, 503) and attempt < retries - 1:
            time.sleep(8 * (attempt + 1))
            continue
        raise TranscribeError(f"Gemini {status}: {raw[:300].decode('utf-8', 'ignore')}")
    return ""


def _shift_timestamps(text: str, offset: int) -> str:
    if not offset:
        return text

    def bump(match: re.Match[str]) -> str:
        h, m, s = match.groups()
        total = (int(h) * 3600 + int(m) * 60 + int(s)) if s else (int(h) * 60 + int(m))
        total += offset
        return f"[{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}]"

    return TS_RE.sub(bump, text)


# --------------------------------------------------------------------------- pipeline


def pick_source(lesson: dict[str, Any]) -> str | None:
    """Prefer hosts with free captions; fall back to whatever we found."""
    urls: list[str] = [str(u) for u in (lesson.get("video_urls") or [])]
    for host in ("youtube.com", "youtu.be", "loom.com", "vimeo.com", "wistia"):
        for url in urls:
            if host in url.lower():
                return url
    return urls[0] if urls else None


def transcribe_lesson(group: str, course: dict[str, Any], lesson: dict[str, Any]) -> Path | None:
    root = settings.group_dir(group)
    slug = f"{crawl.slugify(course.get('title') or course['id'], 40)}--{lesson['slug']}"
    out_path = root / "transcripts" / f"{slug}.md"
    if out_path.exists() and out_path.stat().st_size > 400:
        print(f"  = {slug} (cached)")
        return out_path

    url = pick_source(lesson)
    if not url:
        print(f"  – {slug} (no video — text lesson)")
        return None

    workdir = root / "audio"
    print(f"  ↓ {slug}\n    source: {url[:110]}")
    method = "captions"
    text = try_captions(url, workdir, slug)

    if not text:
        method = f"gemini:{settings.TRANSCRIBE_MODEL}"
        source = download_audio(url, workdir, slug)
        if not source:
            return None
        chunks = chunk_audio(source, workdir, slug)
        if not chunks:
            print("    ! no audio chunks produced")
            return None
        pieces: list[str] = []
        for chunk_path, offset in chunks:
            size_kb = chunk_path.stat().st_size // 1024
            print(f"    · transcribing {chunk_path.name} (+{offset // 60}m, {size_kb}KB)")
            pieces.append(_shift_timestamps(gemini_transcribe(chunk_path), offset))
        text = "\n\n".join(p for p in pieces if p)
        for chunk_path, _ in chunks:
            chunk_path.unlink(missing_ok=True)
        source.unlink(missing_ok=True)

    if not text:
        print("    ! empty transcript")
        return None

    out_path.write_text(
        "\n".join(
            [
                "---",
                f"group: {group}",
                f"course: {course.get('title') or course['id']}",
                f"lesson: {lesson['title']}",
                f"lesson_url: {lesson['url']}",
                f"video: {url}",
                f"method: {method}",
                f"words: {len(text.split())}",
                "---",
                "",
                f"# {lesson['title']}",
                "",
                text,
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"    ✓ {len(text.split()):,} words → {out_path.name}")
    return out_path


def transcribe_group(group: str, *, course_filter: str = "", limit: int | None = None) -> int:
    manifest = crawl.load_manifest(group)
    settings.ensure_dirs(group)
    done = 0
    for course in manifest.get("courses", []):
        title = course.get("title") or course["id"]
        if course_filter and course_filter.lower() not in title.lower():
            continue
        print(f"\n▸ {title}")
        for lesson in course.get("lessons", []):
            if limit and done >= limit:
                print(f"\nStopping at limit={limit}.")
                return done
            try:
                if transcribe_lesson(group, course, lesson):
                    done += 1
            except TranscribeError as exc:
                print(f"    ! {exc}")
            except subprocess.TimeoutExpired:
                print("    ! timed out")
    print(f"\n✓ {done} transcript(s) in {settings.group_dir(group) / 'transcripts'}")
    return done
