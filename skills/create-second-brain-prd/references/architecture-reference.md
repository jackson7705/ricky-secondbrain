# Second Brain Architecture Reference

This is the reference architecture for a fully-featured AI Second Brain built with Claude Code and the Claude Agent SDK. Use this as the blueprint when generating personalized PRDs.

## Project Configuration

### CLAUDE.md (Project Instructions)
`CLAUDE.md` at the repo root is Claude Code's project-level instruction file — it's automatically loaded into every conversation. This is where the agent learns about the project's structure, available commands, and conventions. It should contain:
- **Key paths**: Where memory files, scripts, hooks, skills, data, and config live
- **Build commands**: Every runnable command in the project (memory search, indexing, integration queries, heartbeat, reflection, notifications, scheduler setup, chat bot, security tests, vault sync). These serve as a quick reference so the agent knows exactly how to invoke any part of the system without guessing.
- **Project conventions**: PRD as source of truth, phase-by-phase execution, memory file conciseness rules, checkbox syntax, YAML frontmatter requirements, timezone, advisor mode behavior, no-secrets-in-vault rule
- **Completed phases**: Brief summary of what was built in each phase, with gotchas and notes discovered during implementation

**Critical rule**: Every phase must update CLAUDE.md with any new paths, commands, or conventions introduced. CLAUDE.md is a living document that grows with the project — if a command exists but isn't in CLAUDE.md, the agent won't know about it.

## Core Components

### Memory Layer (Foundation)
- Memory vault at `<VaultName>/Memory/` (a local folder of markdown files — Obsidian can be used as a viewer but is optional)
- **SOUL.md**: Agent personality, behavioral rules, communication style, boundaries
- **USER.md**: User profile, account IDs, integration config, preferences, team info
- **MEMORY.md**: Key decisions, lessons learned, active projects, important facts (must stay concise — loaded into every conversation)
- **BOOTSTRAP.md**: First-run onboarding script — on the user's very first session, this file drives an interactive conversation (asking about name, timezone, role, communication style, integrations, proactivity preferences one question at a time) to personalize USER.md, SOUL.md, and HEARTBEAT.md. Deletes itself after onboarding is complete. If a session ends mid-onboarding, the file persists and picks up where it left off next time.
- **daily/YYYY-MM-DD.md**: Append-only timestamped logs — everything goes here first
- **HEARTBEAT.md**: Checklist of what the heartbeat should monitor
- Why local files: zero latency, no API auth, no rate limits, native LLM read/write

### Hooks (Context Persistence)
Three lifecycle hooks in `.claude/hooks/`, plus a background summarizer:
- **SessionStart** (`session-start-context.py`): Reads SOUL.md + USER.md + MEMORY.md + recent daily logs → injects into conversation context
- **PreCompact** (`pre-compact-flush.py`): Before auto-compaction, extracts conversation context → writes to temp file → spawns background `memory_flush.py`
- **SessionEnd** (`session-end-flush.py`): On session end, same pattern — extracts context and spawns background flush
- **Memory Flush** (`memory_flush.py`): Background Agent SDK script spawned by PreCompact/SessionEnd. Reads conversation context from a temp file, uses Claude (with `allowed_tools=[]`, pure reasoning) to intelligently decide what decisions, lessons, and facts are worth saving. Writes bullet-point summary to daily log, or "FLUSH_OK" if nothing important. Has deduplication (skips if same session flushed <60s ago) and file locking for concurrency safety. This is what makes the daily logs contain *intelligent* summaries rather than mechanical transcript excerpts.
- **Hook recursion prevention**: Every Agent SDK session (heartbeat, reflection, chat, memory flush) must set `CLAUDE_INVOKED_BY` env var to its name (e.g., `os.environ["CLAUDE_INVOKED_BY"] = "heartbeat"`). SessionEnd and PreCompact hooks check this and skip if set — otherwise, every Agent SDK exit spawns another flush, which creates another session, which triggers another SessionEnd. Without this, you get duplicate daily log entries or infinite recursion.
- Configured in `.claude/settings.json`

### Memory Search (Hybrid RAG)
Pipeline: Markdown files → chunking (~400 tokens, overlapping) → FastEmbed ONNX (all-MiniLM-L6-v2, 384-dim) → index → hybrid merge (0.7 vector + 0.3 keyword)
- **SQLite**: sqlite-vec for vectors, FTS5 for keywords
- **Postgres**: pgvector for vectors, tsvector+GIN for keywords
- Key files: `db.py` (abstraction), `embeddings.py`, `memory_index.py`, `memory_search.py`
- Incremental: only changed files re-indexed

### Integrations (Platform Connections)
Pattern: Each integration is a Python module in `.claude/scripts/integrations/`:
- Data model (dataclass) → Auth function → Query functions → Context formatter → CLI
- Registry (`registry.py`): Tracks available integrations, checks which are enabled
- CLI wrapper (`query.py`): Unified interface — `query.py gmail list`, `query.py asana overdue`
- Auth: Google OAuth2 (shared token) or API tokens in `.env`
- Template: `integration_template.py` — copy, rename, fill in TODOs
- LLM never sees API tokens — Python handles auth, passes only data

### Skills (Extensible Capabilities)
Modular packages at `.claude/skills/*/SKILL.md`:
- **SKILL.md**: YAML frontmatter (name, description) + markdown instructions
- **scripts/**: Executable code for deterministic tasks
- **references/**: Documentation loaded on demand
- **assets/**: Files used in output (templates, images)
- Progressive disclosure: metadata always loaded (~100 words), body on trigger, resources on demand
- Invoked via `/skill-name` or automatically by the agent

### Heartbeat (Proactive Monitoring)
Scheduled script at `.claude/scripts/heartbeat.py`:
- Runs every 30 minutes during active hours
- Python gathers data from all integrations BEFORE invoking Claude
- Claude Agent SDK reasons over pre-loaded context → decides what needs attention
- Notifications: Windows Toast / macOS osascript / Linux notify-send + Slack
- State diffing: build_snapshot() → diff_snapshot() → only notify on changes
- Cost: ~$0.05/run (vs $0.38 with MCP tool calls)
- State: `.claude/data/state/heartbeat-state.json`

### Daily Reflection (Memory Curation)
Scheduled script at `.claude/scripts/memory_reflect.py`:
- Runs daily at 8 AM
- Reviews yesterday's daily log
- Promotes important items (decisions, lessons, facts) to MEMORY.md
- **SOUL.md write-protection**: The reflection agent must have a PreToolUse hook that blocks Edit/Write on SOUL.md. If the reflection wants to suggest changes to the agent's identity or behavioral rules, it writes those suggestions to the daily log instead. This prevents "soul drift" where the agent gradually rewrites its own personality without the user's explicit approval.
- Mirrors human memory: short-term experiences → sleep consolidation → long-term storage

### Habits Tracking
File at `Dynamous/Memory/HABITS.md`:
- 3-5 customizable "pillars" representing areas of daily improvement (e.g., main project, community, relationships, health, side project)
- Each pillar has auto-detection rules: objective achievements can be auto-checked by the heartbeat, personal/relational pillars require self-reporting
- Daily reset: heartbeat archives yesterday's checklist to a History section and creates a fresh checklist each morning
- Heartbeat integration: suggests specific actions for unchecked pillars using calendar/tasks/email context, nudges late in the day if pillars are still unchecked
- Inspired by James Clear's Atomic Habits - the goal is one intentional improvement per day per pillar

### Draft Management (Email/Message Drafting)
Lifecycle system for auto-generated reply drafts:
- **Active** (`Dynamous/Memory/drafts/active/`): Heartbeat scans emails, community posts, and DMs that need a reply, then generates a draft in the user's voice
- **Sent** (`Dynamous/Memory/drafts/sent/`): When the user replies on the actual platform, the heartbeat captures their real reply text (not the draft) and moves the file here
- **Expired** (`Dynamous/Memory/drafts/expired/`): Drafts older than 24 hours with no reply get moved here automatically
- **Voice-matching via RAG**: When drafting new replies, search `drafts/sent/` with `memory_search.py --path-prefix drafts/sent` to find similar past replies and match the user's tone
- **File format**: `YYYY-MM-DD_<type>_<slugified-name>.md` with YAML frontmatter (type, source_id, recipient, subject, context, created, status) + Original Message section + Draft Reply section
- Drafting criteria defined in USER.md (what to draft, what to skip)

### Chat Interface (Conversational Access)
Located at `.claude/chat/`:
- Slack DM or @mention → platform-agnostic message → Agent SDK conversation → response
- Each thread = separate persistent conversation (survives restarts)
- PlatformAdapter protocol: SlackAdapter today, extensible to Discord/Teams
- Session store: SQLite database at `.claude/data/chat.db`
- Socket Mode: outbound WebSocket, no public URL needed

### Security (Four Layers)
1. **Credential Protection** (`block-secrets.py`): PreToolUse hook that intercepts Read, Bash, Grep, Edit, Write, and Glob tool calls. Blocks access to sensitive files (.env, .pem, .key, credentials.json, google_token.json, SSH keys, etc.). Blocks Bash commands that would expose environment variables (cat .env, printenv, echo $TOKEN, python -c os.environ, etc.). Blocks *writing* scripts that would exfiltrate secrets to stdout. Recursively checks subshell content. This is the most critical security layer — without it, the LLM can accidentally read and expose every API key.
2. **Sanitize** (`sanitize.py`): Pattern detection → markdown escaping → XML trust boundaries for all external text
3. **Guardrails** (`shared.py`): Deterministic pre-check (dangerous command patterns) + LLM evaluation (pass/fail/suspicious)
4. **API Key Isolation**: Python CLI wrapper handles auth, LLM only sees data — never tokens

### Infrastructure
- **Local (Windows/Mac/Linux)**: SQLite + sqlite-vec, FTS5, OS scheduler, ~80MB model cache
- **VPS (Linux, optional)**: Postgres + pgvector, tsvector + GIN, systemd timers, headless OAuth
- **Vault Sync**: git-sync (2-min intervals) between local ↔ VPS
- **Cost**: Claude Max ~$100/mo + VPS $5-24/mo + Obsidian (free) ≈ $105-128/mo

### Shared Utilities (Cross-Cutting Concerns)
Reusable module at `.claude/scripts/shared.py`:
- **Cross-platform file locking**: A `file_lock()` context manager using `msvcrt` on Windows and `fcntl` on Unix. Required because multiple processes write to the same files concurrently — heartbeat writes to daily log and state files, reflection writes to MEMORY.md and daily log, memory flush writes to daily log, chat writes to daily log, and vault sync pulls remote changes. Without file locking, concurrent writes corrupt state files or produce garbled daily log entries. Use it around every `append_to_daily_log()` call, every `save_state()` call, and in the reflection's MEMORY.md update.
- **Retry with exponential backoff**: A `with_retry()` wrapper for all external API calls (Gmail, Slack, Asana, Calendar, Circle). Handles HTTP 429 (rate limit), 500, 502, 503 with configurable max retries and backoff. Without this, a single rate-limited API call crashes the entire heartbeat run.
- **Atomic state writes**: Write to a `.tmp` file then `os.replace()` to the final path — prevents partial writes from corrupting JSON state files on crash.

## Key Design Principles
1. **Local files are king** — Zero latency, no API auth, no rate limits
2. **Deterministic + LLM hybrid** — Python gathers data, Claude reasons
3. **Security-first** — Read-only by default, API key isolation, sanitize everything
4. **Evolve, don't over-engineer** — Start simple, add capabilities as trust grows
5. **Everything is a file** — Markdown for memory, Python for logic, JSON for state
