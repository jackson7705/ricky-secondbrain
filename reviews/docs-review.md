# Documentation Review Report

**Date:** 2026-02-08
**Reviewer:** docs-reviewer (automated)
**Scope:** `.claude/` directory — CLAUDE.md, memory system, chat interface, scripts, integrations, skills, hooks

---

## Executive Summary

The dynamous-engine codebase has **strong documentation overall**. CLAUDE.md is comprehensive and well-structured, the memory system files are thoughtful, and inline documentation (docstrings, module-level docs) is consistently present across all Python files. The codebase is above average for a personal/internal project.

**Key strengths:**
- Excellent module-level docstrings with usage examples on every Python file
- CLAUDE.md is thorough with setup instructions for all three major platforms
- Memory system docs (SOUL.md, USER.md, MEMORY.md, HEARTBEAT.md) are well-conceived
- All integration APIs have clear dataclass definitions and formatted context helpers

**Key issues:**
- One data inconsistency: Asana YouTube Project ID mismatch between `master.env.example`/`setup_workspace.py` and the rest of the codebase
- Missing documentation for hooks (no docs in CLAUDE.md about hook files)
- Some chat system modules lack context about the Agent SDK import names
- `linkedin-post` and `x-post` skills use lowercase `skill.md` instead of `SKILL.md` (inconsistent naming)

**Documentation Health Score: 8.2/10**

---

## Findings

### Category: Accurate

#### F1. CLAUDE.md File Paths Match Actual Code
- **Location:** `CLAUDE.md` (throughout)
- **Description:** All documented file paths in CLAUDE.md were verified against the filesystem. Key files confirmed to exist:
  - `.claude/scripts/heartbeat.py` — exists
  - `.claude/scripts/memory_index.py` — exists
  - `.claude/scripts/memory_search.py` — exists
  - `.claude/scripts/memory_reflect.py` — exists
  - `.claude/scripts/config.py` — exists
  - `.claude/scripts/notifications.py` — exists
  - `.claude/scripts/embeddings.py` — exists
  - `.claude/scripts/run_heartbeat.bat` / `.sh` — both exist
  - `.claude/scripts/run_reflect.bat` / `.sh` — both exist
  - `.claude/scripts/setup_scheduler.ps1` — exists
  - `.claude/scripts/setup_reflect_scheduler.ps1` — exists
  - `.claude/scripts/.env` and `.env.example` — both exist
  - `.claude/skills/direct-integrations/scripts/query.py` — exists
  - `.claude/memory/plans/heartbeat-v2.md` — exists
  - `.claude/memory/state/` directory — exists
  - `.claude/data/` directory — used for databases
- **Recommendation:** No action needed. File references are accurate.

#### F2. CLAUDE.md Heartbeat System Section Accurately Describes Code
- **Location:** `CLAUDE.md:54-160`, `.claude/scripts/heartbeat.py`
- **Description:** The documented heartbeat workflow (Python gathers API data → feeds to Claude → Claude reasons → notification) accurately matches `heartbeat.py` implementation. The `gather_heartbeat_context()` function calls Gmail, Calendar, Asana, and Slack APIs directly, then injects results into the Agent SDK prompt. Tools list in code (`Read`, `Bash`, `Glob`, `Grep`) matches what's described.
- **Recommendation:** No action needed.

#### F3. Memory Search Documentation Matches Implementation
- **Location:** `CLAUDE.md:163-236`, `.claude/scripts/memory_search.py`, `.claude/scripts/memory_index.py`
- **Description:** Documented chunk size (~400 tokens), overlap (80 tokens), embedding model (all-MiniLM-L6-v2, 384-dim), hybrid weights (0.7 vector + 0.3 keyword), and CLI flags all match the actual `config.py` constants and code behavior.
- **Recommendation:** No action needed.

#### F4. Direct Integrations CLI Commands Match Code
- **Location:** `CLAUDE.md:356-378`, integration `.py` files
- **Description:** CLI commands documented in CLAUDE.md (e.g., `gmail list`, `calendar today`, `asana overdue`, `slack check`) match the argparse configurations in each integration module. The `query.py` wrapper script exists at the documented path.
- **Recommendation:** No action needed.

#### F5. Module-Level Docstrings Are Consistently Present and Accurate
- **Location:** All `.py` files under `.claude/scripts/` and `.claude/chat/`
- **Description:** Every Python file has a module-level docstring with:
  - Brief description of purpose
  - Usage examples with correct CLI commands
  - Architecture notes where relevant (e.g., `heartbeat.py` Phase 5 architecture)
- Files with particularly good docstrings: `heartbeat.py`, `memory_flush.py`, `memory_index.py`, `memory_search.py`, `shared.py`, `notifications.py`, all integration files.
- **Recommendation:** No action needed. This is a strength of the codebase.

#### F6. Chat System Has Good Inline Documentation
- **Location:** `.claude/chat/*.py`
- **Description:** All chat modules have:
  - Module-level docstrings (e.g., `engine.py`: "Conversation engine wrapping Claude Agent SDK with session persistence.")
  - Class-level docstrings explaining the design pattern (e.g., `ConversationEngine` explains session key mapping)
  - Method-level docstrings for public APIs
  - `models.py` has clean dataclass definitions with meaningful field names
  - `adapters/base.py` uses a Protocol class with method docstrings
- **Recommendation:** No action needed.

#### F7. Memory System Files Are Thoughtfully Written
- **Location:** `.claude/memory/SOUL.md`, `USER.md`, `MEMORY.md`, `HEARTBEAT.md`
- **Description:** All four memory files serve their documented purpose:
  - `SOUL.md` — Identity, values, behavioral guidelines, proactivity rules
  - `USER.md` — User profile, schedule, team, integrations
  - `MEMORY.md` — Decisions, lessons learned, active projects
  - `HEARTBEAT.md` — Detailed proactive checklist with notification thresholds
- **Recommendation:** No action needed.

---

### Category: Inconsistent

#### F8. Asana YouTube Project ID Mismatch (CRITICAL)
- **Location:** `master.env.example:70`, `setup_workspace.py:137` vs `CLAUDE.md:392`, `config.py:58`, `USER.md:64`, `.env.example:29`
- **Description:** Two different Asana project IDs are used:
  - `<project_id_1>` in `master.env.example` and `setup_workspace.py` (as `ASANA_YOUTUBE_PROJECT_ID`)
  - `<project_id_2>` everywhere else (as `ASANA_PROJECT_ID`)

  The env variable name also differs: `ASANA_YOUTUBE_PROJECT_ID` vs `ASANA_PROJECT_ID`. This could cause the wrong project to be queried after a fresh setup with `setup_workspace.py`.
- **Recommendation:** **HIGH PRIORITY.** Verify which ID is correct and unify across all files. Also unify the env variable name.

#### F9. Skill Filename Inconsistency: `SKILL.md` vs `skill.md`
- **Location:** `.claude/skills/*/SKILL.md` vs `.claude/skills/*/skill.md`
- **Description:** Most skills (18) use uppercase `SKILL.md`, but four skills use lowercase `skill.md`:
  - `remotion/skill.md`
  - `linkedin-post/skill.md`
  - `x-post/skill.md`
  - `intro-polish/skill.md`

  The `skill-creator` SKILL.md documents the convention as `SKILL.md` (uppercase).
- **Recommendation:** Rename the four lowercase files to `SKILL.md` for consistency. This is cosmetic but helps with pattern matching and `Glob` searches.

#### F10. Settings.json Uses Windows-Specific Paths
- **Location:** `.claude/settings.json`
- **Description:** Hook commands use Windows-specific syntax (`cd /d "%CLAUDE_PROJECT_DIR%\\.claude\\scripts"`) which won't work on macOS/Linux. Since CLAUDE.md documents cross-platform support, the hooks should ideally be cross-platform too.
- **Recommendation:** Document in CLAUDE.md that `settings.json` is Windows-specific and needs manual adaptation for macOS/Linux, or provide platform-specific settings templates.

---

### Category: Missing Documentation

#### F11. Hooks Not Documented in CLAUDE.md
- **Location:** `.claude/hooks/` (3 files), `CLAUDE.md` (mentions hooks inline but has no dedicated section)
- **Description:** CLAUDE.md references hooks conceptually ("A `PreCompact` hook automatically saves...", "A `SessionEnd` hook automatically saves...", "A `SessionStart` hook injects...") but there is no dedicated section documenting:
  - The three hook files and their exact behavior
  - How hooks are configured in `settings.json`
  - How to troubleshoot hooks (check `state/hook-execution.log`)
  - The hook execution log format and location
- The hooks themselves have excellent internal documentation (module-level docstrings).
- **Recommendation:** Add a "## Hooks" section to CLAUDE.md documenting the three hooks, their configuration in `settings.json`, and the hook execution log at `.claude/memory/state/hook-execution.log`.

#### F12. `memory_flush.py` Not Listed in CLAUDE.md Key Files Tables
- **Location:** `CLAUDE.md:62-71` (Heartbeat Key Files table)
- **Description:** `memory_flush.py` is a critical script spawned by both hooks, but it's not listed in any "Key Files" table in CLAUDE.md. It's only mentioned indirectly via the PreCompact/SessionEnd hook descriptions.
- **Recommendation:** Add `memory_flush.py` to the Pre-Compaction Memory Flush section with a brief description: "Background agent that processes conversation context and saves important items to daily log."

#### F13. `shared.py` Not Listed in CLAUDE.md Key Files Tables
- **Location:** `CLAUDE.md`
- **Description:** `shared.py` is imported by virtually every script (heartbeat, memory_flush, memory_reflect, hooks, all integrations) but is never mentioned in CLAUDE.md. It contains critical shared utilities: dangerous command patterns, state management, daily log helpers, file locking, hook execution logging, and retry logic.
- **Recommendation:** Add `shared.py` to a general "Key Files" section with description: "Shared utilities — security hooks, state management, daily log helpers, file locking, retry logic."

#### F14. No Documentation for `setup_workspace.py`
- **Location:** `setup_workspace.py` (project root)
- **Description:** `master.env.example` references `setup_workspace.py` ("Run: python setup_workspace.py --env master.env") but this script is not documented anywhere in CLAUDE.md. It appears to distribute env vars to multiple sub-project `.env` files.
- **Recommendation:** Either add a brief section to CLAUDE.md or add a comment to `master.env.example` explaining what `setup_workspace.py` does and when to use it.

#### F15. Missing Documentation for `query.py` Wrapper Script
- **Location:** `.claude/skills/direct-integrations/scripts/query.py`
- **Description:** CLAUDE.md's "Usage via Skill" section shows commands like `python .claude/skills/direct-integrations/scripts/query.py gmail list`, but the actual behavior of `query.py` (how it wraps the individual integration modules) isn't documented. Someone looking at the direct-integrations skill wouldn't know it delegates to the integration modules under `.claude/scripts/integrations/`.
- **Recommendation:** Minor. Add a brief note to the direct-integrations SKILL.md explaining that `query.py` wraps the integration modules from `.claude/scripts/integrations/`.

#### F16. No Documentation for `excalidraw-diagram` SKILL.md
- **Location:** `.claude/skills/excalidraw-diagram/SKILL.md`
- **Description:** The skill is listed but I noticed it has a different filename (`skill.md` vs `SKILL.md`). The excalidraw-diagram skill actually uses `skill.md` (lowercase), but it's in the uppercase glob results. This one is actually `SKILL.md`. No issue here — just confirming the skill exists.
- **Recommendation:** No action needed.

---

### Category: Outdated / Potentially Stale

#### F17. MEMORY.md "Active Projects" May Be Stale
- **Location:** `.claude/memory/MEMORY.md:27-30`
- **Description:** Active Projects section lists:
  - "Heartbeat v2" with a reference to a saved plan at `.claude/memory/plans/heartbeat-v2.md` — plan file exists but status is unclear
  - "Phase 5 complete... Next: Phase 4B (Entity Memory)" — this next step hasn't been documented elsewhere
- **Recommendation:** The daily reflection system should keep this updated, but it may be worth a manual review. The Heartbeat v2 plan was saved but not yet executed.

#### F18. `engine.py` References `claude_agent_sdk` Import Names That May Change
- **Location:** `.claude/chat/engine.py:46-53`
- **Description:** The engine imports `ClaudeAgentOptions`, `HookMatcher`, `ResultMessage`, `TextBlock`, `query` from `claude_agent_sdk`. These import names are not documented anywhere and could change with SDK updates. The same pattern appears in `heartbeat.py`, `memory_flush.py`, and `memory_reflect.py`.
- **Recommendation:** Low priority. Consider adding a "Dependencies" section noting the Agent SDK version/imports used, so future maintainers know what to update if the SDK changes.

#### F19. Tone-of-Voice Last Updated Date
- **Location:** `.claude/tone-of-voice.md:406`
- **Description:** Shows "*Last updated: 2026-01-13*" — about 4 weeks old. Not outdated per se, but worth noting in case tone/voice preferences have evolved.
- **Recommendation:** No action needed unless the owner's tone preferences have changed.

---

### Category: Minor Issues

#### F20. CLAUDE.md `pyproject.toml` Listed in Key Files But Not Reviewed
- **Location:** `CLAUDE.md:70`
- **Description:** `pyproject.toml` is listed as containing "UV dependencies (`win10toast-click` only installed on Windows)" but the comment implies it's simple. This is accurate but could note the other key dependencies (fastembed, sqlite-vec, slack-sdk, google-api-python-client, asana, etc.).
- **Recommendation:** Minor. No action needed — the pyproject.toml is the source of truth for deps.

#### F21. `check_for_urgent_emails()` `important_senders` Default Is None
- **Location:** `.claude/scripts/integrations/gmail.py:201-237`
- **Description:** The `check_for_urgent_emails()` function accepts an `important_senders` parameter but it defaults to `None` and the heartbeat calls it without this parameter (`check_for_urgent_emails(hours_ago=2)`). Important senders are never configured anywhere — the function only catches emails by keyword matching. This is a documentation gap — nowhere does it explain how to configure important senders.
- **Recommendation:** Minor. Consider documenting how to configure important senders (e.g., via `.env` or config) or removing the parameter if it's not used.

#### F22. CLAUDE.md Direct Integrations Section Shows `python` Instead of `uv run python`
- **Location:** `CLAUDE.md:357-378`
- **Description:** The "Usage via Skill" section uses bare `python` commands: `python .claude/skills/direct-integrations/scripts/query.py gmail list`. All other sections in CLAUDE.md consistently use `uv run python`. While the skill's `query.py` may work with either, using `python` is inconsistent with the rest of CLAUDE.md.
- **Recommendation:** Change to `uv run python` for consistency, or add a note that the skill is invoked through the Skill tool which handles the environment.

---

## Documentation Health Score

| Category | Score | Weight | Notes |
|----------|-------|--------|-------|
| Completeness | 8/10 | 30% | Missing hooks section, a few unlisted key files |
| Accuracy | 9/10 | 30% | One project ID mismatch, otherwise very accurate |
| Consistency | 7/10 | 15% | Skill naming, python vs uv run, env var naming |
| Inline Docs | 9/10 | 15% | Excellent docstrings on every file |
| Maintainability | 8/10 | 10% | Good structure, memory system auto-curates |

**Overall: 8.2/10**

---

## Priority Recommendations

1. **CRITICAL:** Fix Asana YouTube Project ID mismatch between `master.env.example`/`setup_workspace.py` (`<project_id_1>`) and rest of codebase (`<project_id_2>`). Unify env variable name.

2. **HIGH:** Add a "## Hooks" section to CLAUDE.md documenting the three hook files, their settings.json configuration, and the hook execution log.

3. **MEDIUM:** Add `memory_flush.py` and `shared.py` to CLAUDE.md key files listings.

4. **LOW:** Rename 4 lowercase `skill.md` files to `SKILL.md` for consistency.

5. **LOW:** Standardize CLAUDE.md direct-integrations commands to use `uv run python` instead of bare `python`.

6. **LOW:** Document that `settings.json` hook commands are Windows-specific.
