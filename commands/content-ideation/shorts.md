---
description: Generate YouTube Shorts scripts from Content Engine + daily notes + web research
argument-hint: [number-of-shorts (default 5)]
---

# YouTube Shorts Generation

Generate high-performing YouTube Shorts scripts.

## Config

| Setting | Value |
|---------|-------|
| Default Count | 5 |
| Output | `Dynamous/Content-Ideation/Shorts/YYYY-MM-DD/` |

## Paths (from dynamous-engine root)

**Input:**
```
content-engine/output/DAILY_DIGEST.md        ← Read first
content-engine/output/topics/                ← List folders, read most recent
Dynamous/Daily Notes/                        ← List files, read most recent (has a space!)
```

**Skill Reference (read these for templates/guidelines):**
```
.claude/skills/yt-shorts/SKILL.md
```

**Long-form scripts (optional - for repurposing):**
```
Dynamous/Content-Ideation/YouTube/YYYY-MM-DD/
```

**Output:**
```
Dynamous/Content-Ideation/Shorts/YYYY-MM-DD/
```

## Workflow

### 1. Read Skill Guidelines

Read `.claude/skills/yt-shorts/SKILL.md` to understand:
- Short types (Quick Tip, Before-After, Myth Buster, Mini Tutorial, Hot Take, Tool Spotlight)
- Hook formulas and patterns
- Script format with visual planning
- Length and pacing requirements

### 2. Read Content Engine Data

Read `content-engine/output/DAILY_DIGEST.md`

List `content-engine/output/topics/` folders, sort by name, read all `.md` files from the most recent date folder.

### 3. Read Daily Notes

List `Dynamous/Daily Notes/` files (format: `YYYY-MM-DD.md`), sort by name, read the most recent one.

Look for IMPORTANT markers (must include) vs general ideas (context only).

### 4. Check for Long-Form Scripts

Optionally read any YouTube scripts from the same day to find repurposing opportunities:
- Extract single insights from longer scripts
- Find the "hook moments" in long-form content
- Identify tips that can stand alone

### 5. Web Research

Search 3-5 key topics from the digest for current news, trends, and hooks.

### 6. Prioritize and Select Ideas

For Shorts, prioritize:
1. IMPORTANT items from daily notes (must include)
2. Single extractable insights from digest items
3. Surprising stats or counterintuitive claims
4. Quick tips that can stand alone
5. Hot takes and contrarian angles

**Best ideas for Shorts:**
- Can be explained in ONE sentence
- Have natural hook potential (surprising, counterintuitive, impressive result)
- Don't require extensive context
- Have visual demonstration potential

### 7. Generate Shorts

Get today's date. Create folder: `Dynamous/Content-Ideation/Shorts/YYYY-MM-DD/`

For each selected idea, create a Short following the yt-shorts SKILL.md format:
- **Include Source Attribution** at the top (digest item #, original URL from topic file, deep dive path)
- Choose appropriate Short type
- Write a scroll-stopping hook (first 3 seconds)
- Plan visuals and text overlays
- Keep to 75-150 words spoken
- End abruptly, no lingering outro

Write each Short to `Dynamous/Content-Ideation/Shorts/YYYY-MM-DD/{slugified-topic}.md`

### 8. Create Index

Create `Dynamous/Content-Ideation/Shorts/YYYY-MM-DD/index.md`:

```markdown
# YouTube Shorts - YYYY-MM-DD

## Shorts Created

### 1. {Title}
- **File**: [{slug}.md](./{slug}.md)
- **Type**: {Quick Tip / Before-After / etc.}
- **Length**: {target seconds}
- **Hook**: "{first 3 seconds}"
- **One Idea**: {single takeaway}

### 2. {Title}
...

## Repurposed From
- {Long-form script title} → {Short title}
...

## Ideas for Later
- {remaining ideas that could work as Shorts}
```

## Output Structure

```
Dynamous/Content-Ideation/Shorts/2026-01-04/
├── index.md
├── claude-code-one-hour-tip.md
├── ai-agent-failure-myth.md
├── zero-config-deployment-demo.md
├── developer-divide-hot-take.md
└── google-engineer-validation.md
```

## Platform Notes

- Shorts reward retention over everything else
- First 3 seconds determine 50-60% of performance
- ONE idea per Short - never try to cover multiple points
- 30-45 seconds is sweet spot for educational content
- Visual variety every 2-4 seconds
- Strong captions for silent viewing
- No "subscribe" CTAs in the video (algorithm penalty)
- Can repurpose across TikTok and Reels with minor adjustments
