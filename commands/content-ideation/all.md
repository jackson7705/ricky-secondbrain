---
description: Generate content for all platforms (YouTube, LinkedIn, X, Shorts) from shared research
argument-hint: [youtube-count linkedin-count x-count shorts-count] (defaults: 3 5 10 5)
---

# All Platforms Content Generation

Generate content for YouTube, LinkedIn, X, and YouTube Shorts from a single research pass.

## Config

| Platform | Default Count | Output Folder |
|----------|---------------|---------------|
| YouTube | 3 | `Dynamous/Content-Ideation/YouTube/YYYY-MM-DD/` |
| LinkedIn | 5 | `Dynamous/Content-Ideation/LinkedIn/YYYY-MM-DD/` |
| X | 10 | `Dynamous/Content-Ideation/X/YYYY-MM-DD/` |
| Shorts | 5 | `Dynamous/Content-Ideation/Shorts/YYYY-MM-DD/` |

## Paths (from dynamous-engine root)

**Input:**
```
content-engine/output/DAILY_DIGEST.md
content-engine/output/topics/
Dynamous/Daily Notes/                        ← Note the space
```

**Platform Commands (read for generation steps):**
```
.claude/commands/content-ideation/youtube.md
.claude/commands/content-ideation/linkedin.md
.claude/commands/content-ideation/x.md
.claude/commands/content-ideation/shorts.md
```

**Skill References:**
```
.claude/skills/yt-script/SKILL.md
.claude/skills/yt-script/references/style-guide.md
.claude/skills/linkedin-post/SKILL.md
.claude/skills/linkedin-post/references/style-guide.md
.claude/skills/x-post/SKILL.md
.claude/skills/x-post/references/templates.md
.claude/skills/yt-shorts/SKILL.md
```

## Workflow

### Phase 1: Read All References (Do This First)

Read all skill files to understand each platform's format:
- `.claude/skills/yt-script/SKILL.md` + `references/style-guide.md`
- `.claude/skills/linkedin-post/SKILL.md` + `references/style-guide.md`
- `.claude/skills/x-post/SKILL.md` + `references/templates.md`
- `.claude/skills/yt-shorts/SKILL.md`

Read the platform command files to understand the generation and output steps:
- `.claude/commands/content-ideation/youtube.md`
- `.claude/commands/content-ideation/linkedin.md`
- `.claude/commands/content-ideation/x.md`
- `.claude/commands/content-ideation/shorts.md`

### Phase 2: Shared Data Gathering (Once)

**2.1** Read `content-engine/output/DAILY_DIGEST.md`

**2.2** List `content-engine/output/topics/` folders, sort by name, read all `.md` files from the most recent date folder

**2.3** List `Dynamous/Daily Notes/` files, sort by name, read the most recent one

**2.4** Look for IMPORTANT markers in daily notes

### Phase 3: Web Research (Once)

Search 5-7 key topics from the digest for current news and trends.

This research is shared across all platforms.

**IMPORTANT: Verify Current Status**
When researching, verify that any specific tools, frameworks, or products mentioned are still current. AI/tech moves fast - tools from 6-12 months ago may be outdated, renamed, or deprecated. Search for "[tool name] 2026 status" if uncertain.

### Phase 4: Prioritize Ideas (Once)

1. IMPORTANT items from daily notes (must include)
2. Digest items (primary source)
3. General daily note ideas (use to weight digest items)

Select enough ideas to cover all platforms. Some ideas work better for certain platforms:
- Deep technical topics → YouTube scripts
- Single insights/hot takes → LinkedIn posts
- Quick tips/contrarian takes → X posts
- Visual demos, quick tips, hook-worthy moments → Shorts

### Phase 5: Generate All Content

Get today's date. Create all four output folders:
- `Dynamous/Content-Ideation/YouTube/YYYY-MM-DD/`
- `Dynamous/Content-Ideation/LinkedIn/YYYY-MM-DD/`
- `Dynamous/Content-Ideation/X/YYYY-MM-DD/`
- `Dynamous/Content-Ideation/Shorts/YYYY-MM-DD/`

**5.1 YouTube Scripts**

Follow the generation steps from `youtube.md`:
- Create scripts using yt-script SKILL.md format
- Fill all sections (Source, Research, Audience Reactions, Title, Thumbnail, Description, Outline, Intro)
- Write to `Dynamous/Content-Ideation/YouTube/YYYY-MM-DD/{slug}.md`
- Create index.md

**5.2 LinkedIn Posts**

Follow the generation steps from `linkedin.md`:
- Create posts using linkedin-post SKILL.md format
- Choose appropriate post types, write hooks, add CTAs
- Write to `Dynamous/Content-Ideation/LinkedIn/YYYY-MM-DD/{slug}.md`
- Create index.md

**5.3 X Posts**

Follow the generation steps from `x.md`:
- Create posts using x-post SKILL.md format
- Decide tweet vs thread for each, follow character limits
- Write to `Dynamous/Content-Ideation/X/YYYY-MM-DD/{slug}.md`
- Create index.md

**5.4 YouTube Shorts**

Follow the generation steps from `shorts.md`:
- Create Shorts using yt-shorts SKILL.md format
- Choose Short type (Quick Tip, Before-After, Myth Buster, Mini Tutorial, Hot Take, Tool Spotlight)
- Write scroll-stopping hooks, plan visuals and text overlays
- Write to `Dynamous/Content-Ideation/Shorts/YYYY-MM-DD/{slug}.md`
- Create index.md

**Shorts from Long-Form:** After creating YouTube scripts, identify hook moments and single insights that can be extracted as Shorts. Note these repurposing opportunities in the Shorts index.

### Phase 6: Master Index

Create `Dynamous/Content-Ideation/YYYY-MM-DD-all.md`:

```markdown
# Content Batch - YYYY-MM-DD

## Source Summary
- Digest date: {date}
- Daily notes: {date}
- Topics analyzed: {count}
- Web searches: {count}

## Generated Content

### YouTube ({count} scripts)
[Link to YouTube/YYYY-MM-DD/index.md]

### LinkedIn ({count} posts)
[Link to LinkedIn/YYYY-MM-DD/index.md]

### X ({count} posts)
[Link to X/YYYY-MM-DD/index.md]

### Shorts ({count} scripts)
[Link to Shorts/YYYY-MM-DD/index.md]

## Ideas Used
- {idea 1} → YouTube, LinkedIn, Short
- {idea 2} → X (thread), Short
- {idea 3} → LinkedIn, X
...

## Repurposing Map
- YouTube: {title} → Short: {short title}
...

## Ideas for Next Batch
- {remaining ideas}
```

## Output Structure

```
Dynamous/Content-Ideation/
├── 2026-01-04-all.md              ← Master index
├── YouTube/
│   └── 2026-01-04/
│       ├── index.md
│       └── {scripts...}
├── LinkedIn/
│   └── 2026-01-04/
│       ├── index.md
│       └── {posts...}
├── X/
│   └── 2026-01-04/
│       ├── index.md
│       └── {posts...}
└── Shorts/
    └── 2026-01-04/
        ├── index.md
        └── {shorts...}
```

## Notes

- **Every content file must include Source Attribution** at the top:
  - For digest items: `**Source**: Digest #{number} - {title}` with URL from topic file
  - For daily notes: `**Source**: Daily Notes - {IMPORTANT if marked}` with path to daily note
  - For web research: `**Source**: {primary article title}` with the specific URL(s) that informed the content
- Same idea can be adapted for multiple platforms with different angles
- YouTube needs depth, LinkedIn needs single insights, X needs sharpness, Shorts need visual hooks
- Research is done once and shared - don't repeat web searches
- If an idea is marked IMPORTANT, include it on at least one platform
- Shorts can be extracted from YouTube scripts (identify "hook moments" and standalone tips)
- Shorts should be created AFTER YouTube scripts to enable repurposing
