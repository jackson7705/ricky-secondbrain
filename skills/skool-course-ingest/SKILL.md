---
name: skool-course-ingest
description: Watch, transcribe and mine a Skool.com classroom, then turn the course into working assets — distilled notes, SOPs, and a new Claude skill. Handles the Skool login once (persistent browser profile, no stored password), crawls every course/module/lesson, pulls captions or transcribes the audio with Gemini, and synthesises the result. Use when Jason says "transcribe the Skool course", "rip the classroom in that group", "turn that Skool SEO course into a skill or SOP", or wants any paid community's curriculum converted into repeatable process.
---

# skool-course-ingest

Turn a Skool classroom into **operating capability**: transcripts → distilled notes →
SOPs → a working skill. Five phases, each resumable, each writing to disk.

```
login (once, human)  →  crawl  →  transcribe  →  distill  →  SOPs + new skill
      agent-browser      JSON      captions/Gemini   Ricky      sop-creator /
      Chrome profile    manifest    transcripts/     notes/     skill-creator
```

Code lives in `.claude/scripts/skool/`. Run everything from `.claude/scripts`:

```bash
cd ~/SecondBrain/.claude/scripts
uv run python -m skool.cli <command>
```

---

## Ground rules

- **Course material is someone else's paid IP.** Transcripts land in
  `deliverables/skool/<group>/`, which is gitignored. Never commit transcripts,
  never publish them, never repost the creator's material verbatim. What ships is
  *Jason's* SOP and skill — process distilled and rewritten, with the source
  credited in the frontmatter.
- **No Skool password is ever stored.** Jason signs in once in a visible browser;
  the session lives in a Chrome profile at `~/.secondbrain/skool/` (outside the repo).
- **Only groups Jason is a member of.** This is a logged-in member reading their own
  classroom at human-ish pace (1.5s between pages), not a scraper hitting paywalls.
- **Resume, don't restart.** Every phase caches. Re-running skips completed work.

---

## Phase 0 — one-time setup (needs Jason for ~60 seconds)

```bash
uv run python -m skool.cli doctor     # deps + session check
uv run python -m skool.cli login      # opens a real browser window
```

`login` opens skool.com/login **headed** and waits (default 7 min) while Jason signs in
— email, Google SSO, 2FA, whatever Skool asks. Nothing is typed for him. When the page
reports a signed-in member, the session is saved and every later run is headless.

If Ricky is running this from chat, say exactly this and wait:
> "I've opened a browser window on skool.com/login — sign in there and tell me when
> you're done. I never see the password; I just reuse the session afterwards."

Verify and list what he can see:

```bash
uv run python -m skool.cli status
uv run python -m skool.cli groups          # → group slugs, e.g. "the-seo-lab"
```

Sessions last weeks. When it expires, `doctor` says `signed out` → re-run `login`.

---

## Phase 1 — crawl the classroom

```bash
uv run python -m skool.cli crawl <group-slug>
# smoke test a big classroom first:
uv run python -m skool.cli crawl <group-slug> --max-courses 1 --max-lessons 3
```

Writes to `deliverables/skool/<group>/`:

| Path | What |
|---|---|
| `manifest.json` | courses → lessons → lesson URL + every video source found |
| `lessons/NNN-<slug>.md` | lesson text: description, written content, page copy |
| `raw/*.json` | untouched Skool page JSON (for when a shape surprises us) |

**If a crawl returns 0 courses or 0 videos**, Skool changed shape. Don't guess — probe:

```bash
uv run python -m skool.cli probe "https://www.skool.com/<group>/classroom/<courseId>"
```

That prints the pageProps keys plus every node the harvester found and dumps the full
JSON. Read it, then widen `TITLE_KEYS` / `BODY_KEYS` / `VIDEO_KEYS` in
`scripts/skool/crawl.py`. The harvester matches on *shape* (`id` + `metadata`/title),
not exact key names, so drift usually costs one key, not a rewrite.

---

## Phase 2 — transcribe

```bash
uv run python -m skool.cli transcribe <group-slug>
uv run python -m skool.cli transcribe <group-slug> --course "SEO" --limit 5   # scoped
```

Per lesson, cheapest path first:

1. **Existing captions** via yt-dlp (`--write-auto-subs`) — free, instant, covers most
   YouTube-hosted lessons.
2. **Audio → Gemini** when there are no captions (Loom, Vimeo, Wistia, Skool-native
   uploads): downloads bestaudio, re-encodes to 16 kHz mono Opus, splits into 20-minute
   chunks, transcribes each with `gemini-2.5-flash`, and stitches with corrected
   timestamps. Roughly **$0.03–0.05 per hour of video** — a 40-hour classroom is a
   couple of dollars, so don't over-plan the cost.

Gated video hosts get the exported Skool cookies automatically
(`~/.secondbrain/skool/cookies.txt`).

Output: `transcripts/<course>--NNN-<lesson>.md`, frontmatter carrying course, lesson,
source URL, method and word count. Existing transcripts are skipped, so this is safe to
run repeatedly, and safe to interrupt.

Then build the map used by the next phase:

```bash
uv run python -m skool.cli index <group-slug>   # → notes/00-corpus-index.md
```

**Long classrooms:** a 40-hour course is a multi-hour run. Kick it off as a long task
(Ricky's chat runtime supports these) and report progress per course, not per lesson.

---

## Phase 3 — distill (this is Ricky's job, not a script's)

Read `notes/00-corpus-index.md` first, then work **course by course**. For each course
write `notes/<course-slug>.md` capturing only what survives contact with real work:

```markdown
# <Course> — working notes
Source: Skool /<group>/classroom/<id> · <N> lessons · <N> words

## The claim
What this course says wins, in one paragraph.

## Frameworks (named, with the actual steps)
## Hard numbers (thresholds, timelines, volumes, prices — quote them)
## Tools + exact settings mentioned
## Prompts / templates given verbatim (these are the gold)
## Sequencing (what must happen before what, and why)
## Contradictions with how Locafy works today
## Ignore list (dated, platform-specific, or just wrong — say why)
```

Rules that make these notes worth keeping:
- **Steal specifics, not vibes.** "Publish 3× weekly" beats "publish consistently."
- **Every claim gets a lesson citation** (`— L12 [14:22]`) so it can be re-checked.
- **Flag disagreement.** Where the course contradicts Ahrefs/GSC data or the existing
  `seo`, `aeo-authority-content`, or `locafy-gsc-reporting` skills, say so explicitly.
  Jason wants the conflict surfaced, not smoothed over.

---

## Phase 4 — SOPs

Use the **`sop-creator`** skill for format. One SOP per repeatable procedure the course
teaches — not one per module. Write to `deliverables/skool/<group>/sops/<name>.md`.

Each SOP: TL;DR, Definition of Done, trigger, prerequisites, numbered steps with the
real thresholds, verification, owner, and a **Source** line naming the course + lessons.
An SOP a contractor can run without watching the course is the bar.

## Phase 5 — the new SEO skill

Use the **`skill-creator`** skill. Build it in `deliverables/skool/<group>/skill-draft/`,
review with Jason, then promote to `.claude/skills/<name>/`.

The skill must be **procedure, not summary** — if it reads like course notes, it failed.

- `name`: what it does (`seo-topical-authority`, not `skool-seo-course`)
- `description`: third person, name the triggers Jason would actually type
- Body: the decision rules, the thresholds, the exact prompts/templates, and the order
  of operations. Bundle checklists and templates as `references/` or `assets/`.
- Wire it into what already exists: the `seo`, `seo-*` sub-skills, `ai-seo-engine` MCP
  pipeline, Ahrefs MCP, and `locafy-gsc-reporting`. State where this method *replaces*
  current practice and where it merely adds to it.
- Close with a "how to verify this worked" section — the metric that proves it.

Then: `uv run python skills/skill-creator/scripts/quick_validate.py <skill-dir>`.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `signed out` after weeks | `login` again — Skool sessions expire |
| Captcha / "verify it's you" | `login` (headed) and clear it by hand once |
| 0 courses found | `probe` the classroom URL, then widen the key lists in `crawl.py` |
| Video downloads fail | Check `cookies.txt` is fresh (`status` re-exports it); some hosts need `--cookies` |
| Gemini 429 | Built-in backoff handles bursts; if it persists, lower concurrency by running `--limit` batches |
| Transcript looks truncated | Lower `SKOOL_CHUNK_SECONDS` (default 1200) and re-run after deleting that transcript |
| Browser stuck | `uv run python -m skool.cli close` |

## Environment knobs

`SKOOL_STATE_HOME` · `SKOOL_OUTPUT_ROOT` · `SKOOL_TRANSCRIBE_MODEL` (default
`gemini-2.5-flash`) · `SKOOL_CHUNK_SECONDS` · `SKOOL_POLITE_DELAY_S`.
`GEMINI_API_KEY` is read from `scripts/.env` or `~/ai-seo-agent-skills/.env`.
