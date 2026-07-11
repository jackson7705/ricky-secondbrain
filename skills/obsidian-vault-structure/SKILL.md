---
name: obsidian-vault-structure
description: |
  Reference for the Dynamous Obsidian vault organization and file structure.
  Use when Claude needs to understand where content is stored, how files are organized,
  or where to save new content. Helpful for: (1) Finding existing notes or content,
  (2) Understanding date-based folder conventions, (3) Knowing where to save new
  content ideas, daily notes, or media assets, (4) Understanding the relationship
  between different content types.
---

# Dynamous Obsidian Vault Structure

**Location:** `Dynamous/` (relative to project root)

## Directory Overview

```
Dynamous/
|-- .obsidian/                          # Obsidian configuration
|-- Agentic Coding Course/              # Course materials with Excalidraw diagrams
|-- AI Agent Mastery Course/            # Course materials with Excalidraw diagrams
|-- Content-Ideation/                   # Content planning organized by platform
|   |-- LinkedIn/                       # LinkedIn post ideas (date folders)
|   |-- Shorts/                         # YouTube Shorts scripts (date folders)
|   |-- Thumbnails/                     # Thumbnail images and concepts (date folders)
|   |-- X/                              # X/Twitter post ideas (date folders)
|   |-- YouTube/                        # YouTube video ideas (date folders)
|   +-- Presentations/                  # Presentation files (.pptx)
|-- Daily Notes/                        # Daily journal entries
|-- Excalidraw/                         # Visual diagrams for videos and office hours
|-- Meeting Notes/                      # Meeting notes and research files
|-- Permanent Notes/                    # Evergreen notes - video ideas, topic research
|-- Personal/                           # Personal strategy and planning documents
|-- Recordings/                         # Media assets - logos, images, screenshots
|-- Reference Notes/                    # External references and tutorial summaries
|-- Templates/                          # Note templates
|-- Workflows/                          # Workflow tracking files (.base)
+-- Workshops/                          # Workshop Excalidraw materials
```

## Date-Based Organization

### Content-Ideation Platform Folders

Each platform folder (LinkedIn, Shorts, X, YouTube) uses **YYYY-MM-DD date folders**:

```
Content-Ideation/LinkedIn/
|-- 2026-01-21/
|   |-- index.md                        # Summary of all ideas for this date
|   |-- topic-name-1.md                 # Individual content idea
|   +-- topic-name-2.md
+-- 2026-01-23/
    +-- ...
```

- Each date folder contains an `index.md` summarizing all ideas generated that day
- Individual `.md` files are named by topic using kebab-case

### Thumbnails Folder

```
Content-Ideation/Thumbnails/
|-- 2026-01-23/
|   |-- thumbnail.png
|   |-- thumbnail_1.png
|   +-- linkedin-infographic.png
+-- agent-browser/                      # Named concept folders also allowed
    |-- idea-1-split-screen/
    +-- idea-2-vercel-github/
```

### Daily Notes

Daily notes use **YYYY-MM-DD.md** filename format:

```
Daily Notes/
|-- 2026-01-21.md
|-- 2026-01-22.md
+-- 2026-01-23.md
```

## Folder Purposes

| Folder | Purpose | File Types |
|--------|---------|------------|
| **Permanent Notes** | Evergreen video ideas, topic research, book notes | `.md` |
| **Reference Notes** | Tutorial summaries, external documentation | `.md` |
| **Meeting Notes** | Meeting notes, research summaries | `.md` |
| **Excalidraw** | Visual diagrams for videos, office hours, topics | `.md`, `.excalidraw` |
| **Recordings** | Media assets for thumbnails and content | `.png`, `.jpg`, `.gif`, `.svg` |
| **Templates** | Reusable note templates | `.md` |
| **Workflows** | Workflow tracking (YouTube Production, Ideation) | `.base` |
| **Personal** | Strategy docs, roadmaps, personal planning | `.md` |

## Course Folders

Both course folders contain Excalidraw diagram files for course modules:

```
Agentic Coding Course/
|-- Excal-1-CourseIntroduction.md
|-- Excal-2-SystemGap.md
|-- Excal-3-PIVLoop.md
|-- Module 3 Speaking Notes.md
+-- ...

AI Agent Mastery Course/
|-- Excal-1-Evaluation-Framework.md
|-- Excal-2-Golden-Dataset.md
+-- ...
```

## Workshop Materials

```
Workshops/
|-- Excal-1-Workshop-Guide.md
|-- Excal-2-SystemGap.md
+-- ...
```

## Key Naming Conventions

1. **Date folders:** `YYYY-MM-DD`
2. **Daily notes:** `YYYY-MM-DD.md`
3. **Content ideas:** `kebab-case-topic-name.md`
4. **Excalidraw files:** `Excal-{number}-{TopicName}.md` or `Drawing YYYY-MM-DD HH.MM.SS.excalidraw.md`
5. **Office hours:** `YYYY-MM-DD-DynamousOfficeHours.md` (in Excalidraw folder)

## Common Operations

**Find today's content ideas:**
- LinkedIn: `Content-Ideation/LinkedIn/YYYY-MM-DD/`
- YouTube: `Content-Ideation/YouTube/YYYY-MM-DD/`
- Shorts: `Content-Ideation/Shorts/YYYY-MM-DD/`
- X: `Content-Ideation/X/YYYY-MM-DD/`

**Find media assets:** `Recordings/` (logos, screenshots, images)

**Find video research:** `Permanent Notes/` (evergreen topic notes)

**Find today's daily note:** `Daily Notes/YYYY-MM-DD.md`
