# Code Quality Review: Dynamous Engine Second Brain

**Reviewer:** quality-reviewer
**Date:** 2026-02-08
**Scope:** `.claude/chat/`, `.claude/hooks/`, `.claude/scripts/`, `.claude/scripts/integrations/`, `.claude/skills/direct-integrations/scripts/query.py`
**Files Reviewed:** 28

---

## Executive Summary

The dynamous-engine codebase demonstrates solid architecture with clear separation of concerns across its chat interface, hooks system, heartbeat/memory scripts, and platform integrations. The code is generally well-structured, follows consistent patterns, and makes good use of Python's type system. However, there are several areas where code quality can be improved: significant code duplication between hooks, inconsistent error handling patterns, some resource management gaps, and a pervasive `sys.path` manipulation pattern that creates fragile import chains.

**Overall Grade: B+** - Good foundation with room for improvement in maintainability and robustness.

### Finding Summary

| Severity | Count |
|----------|-------|
| Critical | 1 |
| High | 6 |
| Medium | 12 |
| Low | 8 |

---

## 1. Architecture & Design

### 1.1 Clean Adapter Pattern (Strength)

The chat system uses a well-designed adapter pattern with `PlatformAdapter` as a runtime-checkable Protocol. The router is platform-agnostic, and adding a new platform (Discord, Telegram) only requires implementing the protocol. Models are cleanly separated into platform-agnostic dataclasses.

**Files:** `chat/adapters/base.py`, `chat/models.py`, `chat/router.py`

### 1.2 Fragile sys.path Manipulation

**Severity:** High
**Location:** Multiple files (`chat/engine.py:15-16`, `chat/main.py:18-21`, `hooks/pre-compact-flush.py:22-23`, `hooks/session-end-flush.py:22-23`, `hooks/session-start-context.py:22-23`, `integrations/asana_api.py:22`, `integrations/auth.py:20`, `integrations/calendar_api.py:22`, `integrations/gmail.py:24`, `integrations/slack_api.py:24`, `skills/.../query.py:22-23`)

**Description:** Nearly every file manipulates `sys.path` with `sys.path.insert(0, ...)` to enable cross-module imports. This is fragile because:
- Path insertions at index 0 can shadow stdlib or installed packages
- Relative path resolution depends on file location assumptions
- Multiple insertions accumulate without deduplication
- Makes it difficult to understand the actual dependency graph

**Recommendation:** Consider one of:
1. Create a proper installable package with `pyproject.toml` and install via `pip install -e .`
2. Use a single `conftest.py`-style bootstrap that sets up paths once
3. At minimum, add guard checks: `if str(path) not in sys.path: sys.path.insert(0, str(path))`

### 1.3 Tight Coupling Between Engine and Agent SDK Types

**Severity:** Medium
**Location:** `chat/engine.py:46-53`

**Description:** The `ConversationEngine.handle_message()` method imports and directly depends on specific Agent SDK classes (`AssistantMessage`, `ClaudeAgentOptions`, `HookMatcher`, `ResultMessage`, `TextBlock`, `query`). This tightly couples the engine to a specific SDK version and makes testing impossible without the SDK installed.

**Recommendation:** Consider defining a thin adapter/interface for the agent SDK interaction, enabling mock-based testing and future SDK version migration.

### 1.4 Shared Module (`shared.py`) Does Too Much

**Severity:** Low
**Location:** `scripts/shared.py`

**Description:** `shared.py` contains security validation, state management, retry logic, daily log helpers, hook execution logging, and file locking. While consolidation avoids duplication, the module has low cohesion - these are distinct concerns that could be organized into focused modules.

**Recommendation:** Consider splitting into `security.py` (command validation), `state.py` (load/save state, file locking), `logging_utils.py` (hook execution, daily log). Current size is manageable but may grow.

---

## 2. Error Handling

### 2.1 Broad Exception Catches with Silent Swallowing

**Severity:** High
**Location:** Multiple locations

**Specific instances:**

| File | Line | Pattern |
|------|------|---------|
| `hooks/session-start-context.py` | 37-38 | `except Exception: pass` in `read_file_safe()` |
| `scripts/shared.py` | 219 | `except Exception: pass` in `log_hook_execution()` |
| `integrations/auth.py` | 112 | `except Exception: return False` in `is_google_authenticated()` |
| `integrations/slack_api.py` | 103-104 | `except Exception:` silently caches user_id as name |

**Description:** Broad `except Exception` blocks that either pass or return defaults silently swallow errors. In `read_file_safe()`, a permissions error is indistinguishable from a missing file. In `log_hook_execution()`, logging failures are invisible. While some of these are intentional (hook logging shouldn't crash the hook), they make debugging very difficult.

**Recommendation:**
- Log to stderr even when swallowing: `except Exception as e: print(f"Warning: {e}", file=sys.stderr)`
- Narrow exception types where possible (e.g., `except (OSError, PermissionError)` for file ops)
- The `read_file_safe()` function should at least distinguish between "file doesn't exist" (normal) and "permission denied" (error)

### 2.2 Error Strings Exposed to End Users

**Severity:** Medium
**Location:** `chat/engine.py:146`, `chat/router.py:84`

**Description:** Internal exception messages are sent directly to Slack users:
```python
# engine.py:146
yield OutgoingMessage(text=f"Sorry, I hit an error: {e}", ...)

# router.py:84
final_text = f"Sorry, something went wrong: {e}"
```

Exception messages can contain sensitive information (file paths, connection strings, internal state). These should not be forwarded to chat users.

**Recommendation:** Return a generic user-facing error message and log the full exception internally:
```python
print(f"[{datetime.now()}] Engine error: {e}", file=sys.stderr)
yield OutgoingMessage(text="Sorry, I encountered an error processing your request.", ...)
```

### 2.3 Unhandled Edge Cases in Email Parsing

**Severity:** Medium
**Location:** `integrations/gmail.py:56-64`

**Description:** `_parse_sender()` does basic string splitting on `<` and `>` characters but doesn't handle:
- Multiple `<` characters in the string
- Malformed email headers with missing `>`
- Empty strings

```python
def _parse_sender(sender_full: str) -> tuple[str, str]:
    if "<" in sender_full:
        sender = sender_full.split("<")[0].strip().strip('"')
        sender_email = sender_full.split("<")[1].rstrip(">")  # IndexError if malformed
```

**Recommendation:** Add defensive parsing or use `email.utils.parseaddr()` from stdlib.

### 2.4 Missing Error Handling on Lambda Closures in Gmail

**Severity:** Medium
**Location:** `integrations/gmail.py:93-101`

**Description:** The `get_email_details()` function uses a lambda passed to `with_retry()`, but the lambda captures `msg_id` from the outer loop variable. In Python, lambdas capture by reference, not by value. If `msg_id` changes before the lambda executes (e.g., in a retry), it would fetch the wrong email.

```python
msg: dict[str, Any] = with_retry(
    lambda: service.users().messages().get(userId="me", id=msg_id, ...).execute()
)
```

**Recommendation:** This particular case is safe because `msg_id` is a function parameter (not a loop variable), but the pattern should be used carefully. The same lambda-in-loop pattern in `gmail.py:168-173` is also safe but worth noting.

---

## 3. Code Patterns

### 3.1 Significant Code Duplication Between Hooks

**Severity:** High
**Location:** `hooks/pre-compact-flush.py` and `hooks/session-end-flush.py`

**Description:** These two files share ~80% identical code:
- `extract_text_from_content()` - identical (34 lines)
- `extract_conversation_context()` - nearly identical (51 vs 56 lines, only differs in return type)
- `main()` - nearly identical structure (~40 lines)
- Same imports, same constants (`MAX_TURNS`, `MAX_CONTEXT_CHARS`)

The only meaningful differences are:
1. `session-end-flush.py` returns `(context, turn_count)` instead of just `context`
2. `session-end-flush.py` has `MIN_TURNS_TO_FLUSH` gate
3. Different context file naming prefix

**Recommendation:** Extract shared logic into a common module (e.g., `hooks/shared_extraction.py`). Each hook would then be ~20 lines of hook-specific logic.

### 3.2 Repeated Agent SDK Boilerplate

**Severity:** Medium
**Location:** `scripts/heartbeat.py:358-399`, `scripts/memory_flush.py:144-161`, `scripts/memory_reflect.py:207-241`, `chat/engine.py:113-148`

**Description:** Every Agent SDK consumer repeats the same pattern:
```python
response_text = ""
async for message in query(prompt=..., options=ClaudeAgentOptions(...)):
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock):
                response_text += block.text
    elif isinstance(message, ResultMessage):
        # log completion
```

This 15-20 line block appears 4 times with minor variations.

**Recommendation:** Extract a helper like:
```python
async def run_agent(prompt: str, options: ClaudeAgentOptions) -> tuple[str, ResultMessage | None]:
    """Run agent and return (response_text, result_message)."""
```

### 3.3 Inconsistent response_text Accumulation

**Severity:** Medium
**Location:** `chat/engine.py:116-119` vs `scripts/memory_flush.py:153-156`

**Description:** The engine resets `response_text = ""` on each `AssistantMessage` (keeping only the latest turn), while `memory_flush.py` accumulates across all messages. `memory_reflect.py` also accumulates. This inconsistency could lead to bugs if the behavior assumption is wrong.

- `engine.py`: `response_text = ""` then `+=` (resets per turn - correct for chat)
- `memory_flush.py`: only `+=` (accumulates all turns)
- `heartbeat.py`: `response_text = ""` then `+=` (resets per turn)
- `memory_reflect.py`: only `+=` (accumulates all turns)

**Recommendation:** Document the intended behavior. The engine and heartbeat assume multi-turn with only the final turn mattering (correct). The flush and reflect scripts assume single-turn (also correct due to `max_turns=2`/`max_turns=20`). But if `max_turns` changes, the flush could silently lose content.

### 3.4 Unused Import in query.py

**Severity:** Low
**Location:** `skills/direct-integrations/scripts/query.py:18`

**Description:** `import json` is imported but only used in the catch-all exception handler at the bottom. This is fine functionally but could be a lazy import.

### 3.5 Dead Platform Enum Members

**Severity:** Low
**Location:** `chat/models.py:14-18`

**Description:** `Platform` enum defines `DISCORD`, `TELEGRAM`, `WEB`, `CLI` but only `SLACK` is implemented. These are forward-looking but currently dead code.

**Recommendation:** This is acceptable as design intent, but should be documented with a comment like `# Future platforms - not yet implemented`.

---

## 4. Type Safety

### 4.1 Pervasive `Any` Type Usage

**Severity:** Medium
**Location:** Throughout integration files

**Description:** Many functions return `Any` or accept `Any` parameters where more specific types would be appropriate:

| File | Function | Issue |
|------|----------|-------|
| `integrations/asana_api.py:41` | `get_asana_client() -> Any` | Could define a TypeAlias |
| `integrations/auth.py:25` | `get_google_credentials() -> Any` | Returns `Credentials` |
| `integrations/calendar_api.py:41` | `get_calendar_service() -> Any` | Returns `Resource` |
| `integrations/gmail.py:45` | `get_gmail_service() -> Any` | Returns `Resource` |
| `integrations/slack_api.py:44` | `get_slack_client() -> Any` | Returns `WebClient` |
| `chat/router.py:24` | `register(self, adapter: Any)` | Should use `PlatformAdapter` |

**Recommendation:** Use actual types or `TypeAlias` definitions:
```python
from google.oauth2.credentials import Credentials
def get_google_credentials() -> Credentials: ...
```
For untyped third-party libraries, use type stubs or `TypeAlias`.

### 4.2 Unsafe Dictionary Access Patterns

**Severity:** Medium
**Location:** `integrations/asana_api.py:62-63`, `integrations/slack_api.py:240`

**Description:** Some dict accesses use `.get()` with defaults, others use direct indexing without safety:

```python
# asana_api.py - safe
data = task_data.to_dict() if hasattr(task_data, "to_dict") else vars(task_data)

# slack_api.py:240 - unsafe, will throw if ts is not a valid float
dt = datetime.fromtimestamp(float(msg.ts))
```

**Recommendation:** Add try/except or validation around `float(msg.ts)` conversion, which could fail on malformed timestamps.

### 4.3 Type Annotation on build_alert_entry

**Severity:** Low
**Location:** `scripts/heartbeat.py:220-225`

**Description:** `build_alert_entry` returns `dict[str, str]` but stores `source_ids` as a comma-joined string. The actual value types are all strings, but the type annotation should document that `source_ids` is a CSV string, not a list.

---

## 5. Resource Management

### 5.1 SQLite Connections Not Using Context Managers Consistently

**Severity:** High
**Location:** `scripts/memory_index.py:60-145`, `scripts/memory_search.py:47-53`

**Description:** `init_database()` returns a raw `sqlite3.Connection` that the caller must manually close. In `sync_index()`, the connection is properly closed at the end (`conn.close()` on line 404), but if any exception occurs before that line, the connection leaks.

Similarly, `_open_db()` in `memory_search.py` returns a connection that the caller must close. `search()` uses try/finally which is correct, but other callers might forget.

**Recommendation:** Return connections via context managers or use `contextlib.closing()`:
```python
from contextlib import closing

with closing(init_database(db_path)) as conn:
    # ... use conn ...
```

### 5.2 File Handle Not Using Context Manager

**Severity:** Medium
**Location:** `scripts/shared.py:237`

**Description:** The file lock uses `f = open(lock_file, "w")` without a context manager. While the `finally` block does call `f.close()`, using a context manager would be more Pythonic and safer:

```python
f = open(lock_file, "w", encoding="utf-8")  # noqa: SIM115
```

The `noqa: SIM115` comment acknowledges the linter warning but the fix was skipped. This is intentional since the lock lifecycle spans the context manager boundary, but worth noting.

### 5.3 Slack Client Created Per-Call

**Severity:** Medium
**Location:** `integrations/slack_api.py:44-55`, `integrations/slack_api.py:96-97`

**Description:** `get_slack_client()` creates a new `WebClient` on every call. `resolve_user_name()` calls `get_slack_client()` for each user lookup. In `check_for_important_messages()`, this means creating a new client for each channel AND each user resolution.

**Recommendation:** Cache the client as a module-level singleton (similar to `_model` in `embeddings.py`):
```python
_client: WebClient | None = None

def get_slack_client() -> WebClient:
    global _client
    if _client is None:
        _client = WebClient(token=SLACK_BOT_TOKEN)
    return _client
```

### 5.4 Google API Services Created Per-Call

**Severity:** Medium
**Location:** `integrations/gmail.py:45-52`, `integrations/calendar_api.py:41-49`

**Description:** Same pattern as Slack - `get_gmail_service()` and `get_calendar_service()` create new API service objects on every call. The Google API `build()` function is relatively expensive.

**Recommendation:** Cache services as module-level singletons.

---

## 6. Concurrency

### 6.1 Unbounded Task Spawning in Router

**Severity:** Critical
**Location:** `chat/router.py:51`

**Description:** The router spawns a new `asyncio.Task` for every incoming message with no limit:
```python
async for incoming in adapter.listen():
    asyncio.create_task(self._handle(adapter, incoming))
```

If messages arrive faster than they can be processed (e.g., a Slack bot being flooded), this creates unbounded concurrent tasks, each running an Agent SDK session. This could:
- Exhaust memory
- Hit API rate limits
- Create runaway costs (each session uses Claude API)

**Recommendation:** Use a semaphore to limit concurrency:
```python
self._semaphore = asyncio.Semaphore(3)  # Max 3 concurrent conversations

async def _handle_with_limit(self, adapter, incoming):
    async with self._semaphore:
        await self._handle(adapter, incoming)
```

### 6.2 SQLite check_same_thread=False Without Synchronization

**Severity:** High
**Location:** `chat/session.py:38,77,89,112,130`

**Description:** Every SQLite connection uses `check_same_thread=False`, which disables SQLite's thread-safety check. Combined with the router spawning multiple concurrent tasks (6.1), multiple coroutines could write to the session database simultaneously. While SQLite handles this at the file level with WAL mode, creating separate connections per operation without explicit serialization can cause `database is locked` errors under load.

**Recommendation:** Either:
1. Use a single shared connection with an asyncio lock
2. Use `aiosqlite` for proper async SQLite support
3. Add WAL mode: `conn.execute("PRAGMA journal_mode=WAL")`

### 6.3 Race Condition in Session Persistence

**Severity:** Medium
**Location:** `chat/engine.py:150-172`

**Description:** The engine checks for an existing session at the start, then creates/updates at the end. If two messages arrive for the same thread simultaneously, both could pass the `existing is None` check and try to create the same session, causing a UNIQUE constraint violation.

**Recommendation:** Use `INSERT OR REPLACE` or add a try/except for `IntegrityError` to handle the race.

### 6.4 File Lock Doesn't Guard All State Access

**Severity:** Medium
**Location:** `scripts/memory_flush.py:88-99`

**Description:** The dedup check reads state INSIDE the file lock (line 88), but the lock is acquired in `run_flush()` which wraps `_run_flush_inner()`. However, `load_state()` in `_run_flush_inner()` opens/reads the state file without the lock being on the state file itself - the lock is on `FLUSH_STATE_FILE`, which IS the state file. So this is actually correct. The lock path and state file path are the same.

After further analysis: this is actually fine. The `file_lock` uses `FLUSH_STATE_FILE.lock` as the lock file, protecting reads/writes to `FLUSH_STATE_FILE`. Correctly implemented.

---

## 7. Configuration Management

### 7.1 Well-Structured Configuration (Strength)

The `config.py` module centralizes all configuration with clear categories, environment variable overrides with sensible defaults, and derived paths. This is clean and maintainable.

### 7.2 Hardcoded User-Specific Values

**Severity:** Medium
**Location:** `scripts/config.py:64`

**Description:** The Slack owner user ID was hardcoded rather than loaded from `.env`. While this is a single-user system, it breaks the pattern of other config values being env-configurable.

**Recommendation:** Use `os.getenv("SLACK_OWNER_USER_ID")` for consistency (now implemented).

### 7.3 Hardcoded Magic Numbers

**Severity:** Low
**Location:** Various

| File | Line | Value | Description |
|------|------|-------|-------------|
| `chat/adapters/slack.py` | 218 | `3900` | Slack message split length |
| `scripts/heartbeat.py` | 36 | `8` | Alert TTL hours |
| `scripts/memory_flush.py` | 107 | `15_000` | Max context chars |
| `scripts/shared.py` | 188-189 | `1000`/`500` | Hook log rotation |
| `hooks/pre-compact-flush.py` | 28-29 | `30`/`15_000` | Max turns/chars |

**Recommendation:** These would benefit from being named constants at the module level (most already are) or moved to `config.py` if they're cross-cutting.

### 7.4 Config Loaded at Import Time

**Severity:** Low
**Location:** `scripts/config.py:14`

**Description:** `load_dotenv()` is called at module import time, meaning `.env` is loaded whenever any module imports `config`. This is generally fine for scripts but means environment variables can't be overridden after import.

---

## 8. Testability

### 8.1 No Test Suite Exists

**Severity:** High
**Location:** N/A

**Description:** There are no test files anywhere in the codebase. Key modules with complex logic that would benefit from testing:

| Module | Testable Units |
|--------|----------------|
| `shared.py` | `validate_bash_command()`, `with_retry()`, `file_lock()` |
| `chat/adapters/slack.py` | `_markdown_to_mrkdwn()`, `_split_message()` |
| `scripts/memory_index.py` | `chunk_markdown()` |
| `scripts/memory_search.py` | `search_keyword()`, `search_hybrid()`, `_quote_fts_query()` |
| `hooks/*.py` | `extract_text_from_content()`, `extract_conversation_context()` |
| `integrations/gmail.py` | `_parse_sender()`, `_extract_body()` |
| `integrations/asana_api.py` | `_parse_task()` |

**Recommendation:** Start with unit tests for pure functions (no I/O): `_markdown_to_mrkdwn()`, `_split_message()`, `chunk_markdown()`, `_parse_sender()`, `validate_bash_command()`. These have clear inputs/outputs and complex logic prone to edge cases.

### 8.2 Hard-to-Test Components

**Severity:** Medium
**Location:** `chat/engine.py`, `scripts/heartbeat.py`

**Description:** These modules import SDK types inside methods (lazy imports) and construct options inline, making it impossible to inject mocks without monkeypatching. The heartbeat's `gather_heartbeat_context()` calls all integrations in sequence with no way to substitute test data.

**Recommendation:** Accept integration clients as constructor/function parameters for dependency injection:
```python
def gather_heartbeat_context(gmail=None, calendar=None, asana=None, slack=None) -> ...:
```

---

## 9. Additional Findings

### 9.1 Timezone Inconsistency

**Severity:** Medium
**Location:** `scripts/config.py:119`, `integrations/calendar_api.py:124-126`

**Description:** `is_within_active_hours()` uses `ZoneInfo(HEARTBEAT_TIMEZONE)` for timezone-aware comparison, but `get_today_events()` uses naive `datetime.now()` (no timezone). The Calendar API uses `datetime.now(UTC)` for API calls but formats events without timezone info. This could cause off-by-one-hour issues around DST transitions.

**Recommendation:** Use timezone-aware datetimes consistently throughout. Import `ZoneInfo` and use `datetime.now(ZoneInfo("America/Chicago"))` everywhere.

### 9.2 Potential Infinite Loop in Slack Channel Resolution

**Severity:** Low
**Location:** `integrations/slack_api.py:64-82`

**Description:** The `get_channel_id()` function paginates through all channels. If the Slack API returns an empty `next_cursor` that's truthy (e.g., whitespace), the loop could theoretically spin. In practice, the Slack SDK handles this correctly, but the pattern could be safer:

```python
cursor = metadata.get("next_cursor", "").strip()
if not cursor:
    break
```

### 9.3 Memory Flush Context Files Can Accumulate

**Severity:** Low
**Location:** `hooks/pre-compact-flush.py:148-149`, `scripts/memory_flush.py:177-181`

**Description:** If the background flush process fails to start or crashes before cleanup, context files (`flush-context-*.md`) accumulate in the state directory indefinitely. The cleanup only happens inside the flush script on success.

**Recommendation:** Add a periodic cleanup of stale context files (older than 1 hour) in the heartbeat or add a max age check at hook startup.

### 9.4 `with_retry` Uses `Any` Return Type

**Severity:** Low
**Location:** `scripts/shared.py:127-150`

**Description:** `with_retry()` accepts `func: Any` and returns `Any`, losing all type information. It also doesn't support async functions.

**Recommendation:** Use generics:
```python
from typing import TypeVar, Callable
T = TypeVar("T")
def with_retry(func: Callable[[], T], ...) -> T: ...
```

### 9.5 Emoji in Slack Placeholder

**Severity:** Low
**Location:** `chat/router.py:69`

**Description:** The "Thinking..." placeholder uses the Slack emoji `:hourglass_flowing_sand:`. This is Slack-specific and would render as literal text on other platforms if multi-platform support is added.

**Recommendation:** Move platform-specific formatting to the adapter layer.

---

## Strengths Summary

1. **Clean adapter/protocol pattern** in the chat system enables platform extensibility
2. **Centralized configuration** in `config.py` with env var overrides and sensible defaults
3. **Graceful degradation** in heartbeat - each integration failure is non-fatal
4. **File locking** properly implemented for cross-platform (Windows/Unix)
5. **Deduplication logic** in heartbeat prevents notification spam
6. **Security hooks** block dangerous bash commands in Agent SDK sessions
7. **Consistent coding style** - type hints on function signatures, docstrings, clear naming
8. **Session persistence** enables conversation continuity across restarts
9. **Incremental indexing** in memory search avoids redundant work

## Priority Improvement Areas

1. **Add concurrency limits** to the chat router (Critical - could cause runaway costs)
2. **Extract duplicated hook code** into a shared module (High - maintainability)
3. **Add a basic test suite** for pure functions (High - confidence in complex logic)
4. **Fix resource management** - cache API clients, use context managers for SQLite (High)
5. **Remove internal errors from user-facing messages** (Medium - information leakage)
6. **Standardize timezone handling** across the codebase (Medium - correctness)
7. **Address sys.path manipulation** with proper package structure (Medium - long-term)
