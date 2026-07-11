---
description: Generate YouTube scripts from Content Engine + daily notes + web research
argument-hint: [number-of-scripts (default 3)]
---

# YouTube Script Generation

Generate production-ready YouTube scripts.

## Config

| Setting | Value |
|---------|-------|
| Default Count | 3 |
| Output | `Dynamous/Content-Ideation/YouTube/YYYY-MM-DD/` |

## Paths (from dynamous-engine root)

**Input:**
```
content-engine/output/DAILY_DIGEST.md        ← Read first
content-engine/output/topics/                ← List folders, read most recent
Dynamous/Daily Notes/                        ← List files, read most recent (has a space!)
```

**Skill Reference (read these for templates/guidelines):**
```
.claude/skills/yt-script/SKILL.md
.claude/skills/yt-script/references/style-guide.md
```

**Output:**
```
Dynamous/Content-Ideation/YouTube/YYYY-MM-DD/
```

## Workflow

### 1. Read Skill Guidelines

Read these files to understand YouTube script format, templates, and tone:
- `.claude/skills/yt-script/SKILL.md`
- `.claude/skills/yt-script/references/style-guide.md`

These define the script structure: Tags, Research, Audience Reactions, Title, Thumbnail Text, Thumbnail Ideas, Description, Links, Outline, Intro.

### 2. Read Content Engine Data

Read `content-engine/output/DAILY_DIGEST.md`

List `content-engine/output/topics/` folders, sort by name, read all `.md` files from the most recent date folder.

### 3. Read Daily Notes

List `Dynamous/Daily Notes/` files (format: `YYYY-MM-DD.md`), sort by name, read the most recent one.

Look for IMPORTANT markers (must include) vs general ideas (context only).

### 4. Web Research

Search 5-7 key topics from the digest for current news and trends.

### 5. Prioritize

1. IMPORTANT items from daily notes (must include)
2. Digest items (primary source)
3. General daily note ideas (use to weight digest items)

### 6. Generate Scripts

Get today's date. Create folder: `Dynamous/Content-Ideation/YouTube/YYYY-MM-DD/`

For each selected idea, create a script following the yt-script SKILL.md format:
- **Include Source Attribution** at the top (digest item #, original URL from topic file, deep dive path)
- Fill all sections per the skill guidelines
- Use the style-guide.md patterns for titles, hooks, tone
- Apply the user's characteristic phrases

Write each script to `Dynamous/Content-Ideation/YouTube/YYYY-MM-DD/{slugified-topic}.md`

### 7. Create Index

Create `Dynamous/Content-Ideation/YouTube/YYYY-MM-DD/index.md`:

```markdown
# YouTube Scripts - YYYY-MM-DD

## Scripts Created
### 1. {Title}
- **File**: [{slug}.md](./{slug}.md)
- **Hook**: "{hook}"
- **Cohort**: {cohort}

## Ideas for Later
- {remaining ideas}
```

## Output Structure

```
Dynamous/Content-Ideation/YouTube/2026-01-03/
├── index.md
├── ai-agent-failure-modes.md
├── claude-opus-review.md
└── vibe-kanban-workflow.md
```
