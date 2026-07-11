---
description: Generate LinkedIn posts from Content Engine + daily notes + web research
argument-hint: [number-of-posts (default 5)]
---

# LinkedIn Post Generation

Generate high-performing LinkedIn posts.

## Config

| Setting | Value |
|---------|-------|
| Default Count | 5 |
| Output | `Dynamous/Content-Ideation/LinkedIn/YYYY-MM-DD/` |

## Paths (from dynamous-engine root)

**Input:**
```
content-engine/output/DAILY_DIGEST.md        ← Read first
content-engine/output/topics/                ← List folders, read most recent
Dynamous/Daily Notes/                        ← List files, read most recent (has a space!)
```

**Skill Reference (read these for templates/guidelines):**
```
.claude/skills/linkedin-post/SKILL.md
.claude/skills/linkedin-post/references/style-guide.md
```

**Output:**
```
Dynamous/Content-Ideation/LinkedIn/YYYY-MM-DD/
```

## Workflow

### 1. Read Skill Guidelines

Read these files to understand LinkedIn post philosophy and voice:
- `.claude/skills/linkedin-post/SKILL.md`
- `.claude/skills/linkedin-post/references/style-guide.md`

These define: content modes (story, observation, take, teach, react, ask), specificity requirements, anti-patterns to avoid, and voice guidelines.

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

Get today's date. Create folder: `Dynamous/Content-Ideation/LinkedIn/YYYY-MM-DD/`

For each selected idea, create a post following the linkedin-post SKILL.md guidelines:
- **Include Source Attribution** at the top (digest item #, original URL from topic file, deep dive path)
- Choose appropriate content mode (story, observation, take, teach, react, or ask)
- Include at least 2 concrete details (dates, numbers, names, specific context)
- Write in authentic voice - no template phrases or engagement bait
- No hashtags
- End naturally - no formulaic CTAs

Write each post to `Dynamous/Content-Ideation/LinkedIn/YYYY-MM-DD/{slugified-topic}.md`

### 7. Create Index

Create `Dynamous/Content-Ideation/LinkedIn/YYYY-MM-DD/index.md`:

```markdown
# LinkedIn Posts - YYYY-MM-DD

## Posts Created
### 1. {Topic}
- **File**: [{slug}.md](./{slug}.md)
- **Mode**: {story/observation/take/teach/react/ask}
- **Core insight**: {one sentence summary}

## Ideas for Later
- {remaining ideas not used this batch}
```

## Output Structure

```
Dynamous/Content-Ideation/LinkedIn/2026-01-03/
├── index.md
├── ai-agent-orchestration.md
├── developer-divide-opinion.md
├── rag-optimization-tips.md
├── claude-opus-review.md
└── memory-scaling-insight.md
```

## Platform Notes

- Extract single insight per post, don't summarize entire topics
- First 2 lines matter, but don't use formulaic hooks - be specific and authentic
- Links are fine in post body (one max)
- No hashtags
- No engagement bait CTAs ("Agree?", "What would you add?")
- Posts should sound like you talking to a colleague, not like "a LinkedIn post"
