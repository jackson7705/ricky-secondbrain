---
description: Generate X posts/threads from Content Engine + daily notes + web research
argument-hint: [number-of-posts (default 10)]
---

# X Post Generation

Generate engaging X posts and threads.

## Config

| Setting | Value |
|---------|-------|
| Default Count | 10 |
| Output | `Dynamous/Content-Ideation/X/YYYY-MM-DD/` |

## Paths (from dynamous-engine root)

**Input:**
```
content-engine/output/DAILY_DIGEST.md        ← Read first
content-engine/output/topics/                ← List folders, read most recent
Dynamous/Daily Notes/                        ← List files, read most recent (has a space!)
```

**Skill Reference (read these for templates/guidelines):**
```
.claude/skills/x-post/SKILL.md
.claude/skills/x-post/references/templates.md
```

**Output:**
```
Dynamous/Content-Ideation/X/YYYY-MM-DD/
```

## Workflow

### 1. Read Skill Guidelines

Read these files to understand X post format, templates, and tone:
- `.claude/skills/x-post/SKILL.md`
- `.claude/skills/x-post/references/templates.md`

These define: tweet vs thread format, character limits, hook formulas, thread structure.

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

### 6. Generate Posts

Get today's date. Create folder: `Dynamous/Content-Ideation/X/YYYY-MM-DD/`

For each selected idea, create a post following the x-post SKILL.md format:
- **Include Source Attribution** at the top (digest item #, original URL from topic file, deep dive path)
- Decide: single tweet (under 280 chars) or thread (7-10 tweets)
- Apply hook formulas from the skill
- Follow character limits and formatting rules

Write each post to `Dynamous/Content-Ideation/X/YYYY-MM-DD/{slugified-topic}.md`

### 7. Create Index

Create `Dynamous/Content-Ideation/X/YYYY-MM-DD/index.md`:

```markdown
# X Posts - YYYY-MM-DD

## Posts Created
### 1. {Topic}
- **File**: [{slug}.md](./{slug}.md)
- **Format**: {tweet/thread}
- **Hook**: "{first line}"

## Summary
- Single tweets: {count}
- Threads: {count}

## Ideas for Later
- {remaining ideas}
```

## Output Structure

```
Dynamous/Content-Ideation/X/2026-01-03/
├── index.md
├── ai-agent-failure-hot-take.md
├── claude-opus-thread.md
├── rag-tip.md
├── memory-scaling-insight.md
└── ... (10 posts)
```

## Platform Notes

- X rewards volume - 10 posts is good for a day
- Single tweets: under 280 chars
- Threads: 7-10 tweets max, one point per tweet
- Hot takes and contrarian angles perform well
- No links in main tweet - put in reply
- No hashtags - they hurt reach on X
