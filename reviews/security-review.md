# Security Review: Dynamous Engine (.claude/ Directory)

**Date:** 2026-02-08
**Reviewer:** security-reviewer (automated)
**Scope:** All Python files in `.claude/chat/`, `.claude/hooks/`, `.claude/scripts/`, `.claude/scripts/integrations/`, `.claude/skills/direct-integrations/`

---

## Executive Summary

The dynamous-engine Second Brain codebase is a **personal-use automation system** (single user) rather than a multi-tenant application. This context significantly reduces the attack surface. Overall, the codebase demonstrates **good security posture** for a personal tool:

- Credentials are loaded from `.env` files, never hardcoded, and `.gitignore` properly excludes secrets
- The Slack chat bot enforces a user allowlist (the owner's user ID only)
- Agent SDK sessions use a `PreToolUse` hook to block dangerous bash commands
- SQLite queries use parameterized statements throughout (no SQL injection)
- OAuth tokens auto-refresh and are stored locally

However, several findings merit attention, particularly around **error message data exposure**, **incomplete command blocking**, and **file permission practices**.

**Risk profile:** Low overall. No critical vulnerabilities found. Most findings are defense-in-depth improvements.

---

## Findings

### HIGH Severity

#### H-1: Error Messages Expose Internal Details to Slack Users

**Severity:** HIGH
**Location:** `chat/engine.py:141-148`, `chat/router.py:83-84`

**Description:**
When the Agent SDK throws an exception, the raw Python exception message (including tracebacks, file paths, and potentially sensitive internal state) is sent directly to the Slack channel:

```python
# engine.py:146
yield OutgoingMessage(
    text=f"Sorry, I hit an error: {e}",
    ...
)

# router.py:84
final_text = f"Sorry, something went wrong: {e}"
```

Python exception messages can contain file paths, environment variable names, API endpoint URLs, token prefixes, or stack traces. While the Slack bot only responds to the owner, this is still a data hygiene concern — Slack message history is searchable and persisted.

**Recommendation:**
Return a generic error message to Slack and log the full exception to the console/daily log only:

```python
print(f"[{datetime.now()}] Agent SDK error: {e}", file=sys.stderr)
yield OutgoingMessage(text="Sorry, I ran into an error processing that. Check the logs for details.", ...)
```

---

#### H-2: Token Prefix Logged at Startup

**Severity:** HIGH
**Location:** `chat/main.py:64-65`

**Description:**
The chat bot logs the first 12 characters of both the Slack bot token and app token at startup:

```python
print(f"  Bot token:     {SLACK_BOT_TOKEN[:12]}...")
print(f"  App token:     {SLACK_APP_TOKEN[:12]}...")
```

Slack bot tokens follow the format `xoxb-WORKSPACE_ID-...` and app tokens follow `xapp-1-...`. The first 12 characters reveal the workspace ID and token type, which is useful information for an attacker. If these logs are captured (e.g., Task Scheduler logs, systemd journal, CI output), they expose partial credentials.

**Recommendation:**
Log only the token type prefix (4-5 chars) or a masked version:

```python
print(f"  Bot token:     {SLACK_BOT_TOKEN[:4]}...{SLACK_BOT_TOKEN[-4:]}")
```

---

#### H-3: Slack Allowlist Bypass When Empty

**Severity:** HIGH (mitigated by config default)
**Location:** `chat/adapters/slack.py:149-153`

**Description:**
The `_is_allowed()` method returns `True` when the allowlist is empty:

```python
def _is_allowed(self, user_id: str) -> bool:
    if not self.allowed_users:
        return True  # No allowlist = allow all
    return user_id in self.allowed_users
```

While `config.py:71` defaults `CHAT_ALLOWED_USERS` to the owner's user ID, if someone accidentally sets `CHAT_ALLOWED_USERS=` (empty string) in `.env`, the split produces `['']`, the strip+filter removes it, and the allowlist becomes empty — opening the bot to any Slack user in the workspace.

**Recommendation:**
Fail closed — if the allowlist is empty after processing, refuse all messages rather than allowing all:

```python
def _is_allowed(self, user_id: str) -> bool:
    if not self.allowed_users:
        return False  # Fail closed - no allowlist means deny all
    return user_id in self.allowed_users
```

---

### MEDIUM Severity

#### M-1: Dangerous Bash Command Blocklist is Incomplete and Bypassable

**Severity:** MEDIUM
**Location:** `scripts/shared.py:32-64`, `scripts/shared.py:67-97`

**Description:**
The bash command validation uses a substring-match blocklist approach which has inherent weaknesses:

1. **String encoding bypass:** `rm -rf /` can be bypassed with `rm -rf $(echo /)`, variable expansion (`$HOME`), hex encoding, or Base64-piped execution (`echo cm0gLXJmIC8= | base64 -d | sh`)
2. **Missing patterns:** The list doesn't block `mv / /dev/null`, `kill -9 -1`, `iptables --flush`, `crontab -r`, `userdel`, or package manager destructive commands (`pip install --force-reinstall`, `npm cache clean --force`)
3. **Pattern ordering:** `chown -R` blocks all recursive chown commands, even safe ones like `chown -R user:user ./my-project`
4. **Subshell extraction is limited:** Only handles `$(...)` and backticks, but not `<(process substitution)`, heredocs, or `eval`

This is defense-in-depth (the Agent SDK also has its own safeguards), so the practical risk is low, but the blocklist gives a false sense of complete protection.

**Recommendation:**
- Document that this is a best-effort safeguard, not a security boundary
- Consider an allowlist approach for the heartbeat (which only needs `uv run python memory_search.py` and similar commands)
- Add the additional patterns for `eval`, `exec`, `source` of untrusted content

---

#### M-2: Google OAuth Token File Stored Without Restricted Permissions

**Severity:** MEDIUM
**Location:** `scripts/integrations/auth.py:92-93`

**Description:**
The Google OAuth token file (containing refresh token + access token) is written with default file permissions:

```python
GOOGLE_TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
```

On multi-user systems, the default umask might allow other users to read this file. The token grants read access to the owner's Gmail and Calendar.

**Recommendation:**
Set restrictive permissions on token files:

```python
import os
GOOGLE_TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
os.chmod(GOOGLE_TOKEN_FILE, 0o600)  # Owner read/write only
```

This also applies to `google_credentials.json` (the OAuth client secret).

---

#### M-3: Chat Session Database Stores User Data Without Encryption

**Severity:** MEDIUM
**Location:** `chat/session.py:38-56`

**Description:**
The SQLite session database (`chat.db`) stores session metadata including `user_id`, `channel_id`, `thread_id`, and `agent_session_id` in plaintext. The `agent_session_id` is particularly sensitive as it can be used to resume conversations via the Agent SDK.

While the database is stored locally and git-ignored, if the machine is compromised or the file is included in backups, it provides a map of all conversations and their resume tokens.

**Recommendation:**
- Ensure the database file has restrictive permissions (0o600)
- Consider adding a `session_expires_at` field and auto-pruning old sessions
- Document the sensitivity of this file in deployment guides

---

#### M-4: macOS Notification AppleScript Injection (Incomplete Escaping)

**Severity:** MEDIUM
**Location:** `scripts/notifications.py:60-64`

**Description:**
The macOS notification function escapes backslashes and double quotes, but AppleScript injection has other vectors. Content containing unescaped single quotes, or certain Unicode characters, could potentially break out of the string context. More critically, `osascript` is invoked via `subprocess.run` with a constructed command string.

```python
safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
safe_message = message.replace("\\", "\\\\").replace('"', '\\"')
script = f'display notification "{safe_message}" with title "{safe_title}"'
subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
```

Since the message content comes from Claude's heartbeat response, which could theoretically contain crafted content, this is a medium concern.

**Recommendation:**
Pass message content via stdin or environment variables rather than embedding in the AppleScript string:

```python
import shlex
# Or use osascript with -s s flag and pipe via stdin
```

---

#### M-5: Context Files Written to State Directory Without Cleanup Guarantee

**Severity:** MEDIUM
**Location:** `hooks/pre-compact-flush.py:148-149`, `hooks/session-end-flush.py:160-161`

**Description:**
The hooks write conversation context (which may contain sensitive data like email content, task details, or personal information) to temporary files in the state directory:

```python
context_path = STATE_DIR / context_filename
context_path.write_text(context, encoding="utf-8")
```

While `memory_flush.py:177-181` attempts to clean up these files, if the background flush process crashes or fails to start, the context files persist indefinitely. These files contain recent conversation content.

**Recommendation:**
- Add a cleanup mechanism (e.g., heartbeat deletes context files older than 1 hour)
- Write context files with restrictive permissions
- Consider using `tempfile.NamedTemporaryFile` with a `.claude`-prefixed temp directory

---

#### M-6: Heartbeat Logs Sensitive Integration Data to Console

**Severity:** MEDIUM
**Location:** `scripts/heartbeat.py:86-89, 115-117, 143-146, 170-171`

**Description:**
Integration errors are logged with full exception messages to stdout:

```python
print(f"[{datetime.now()}] Gmail error (non-fatal): {e}")
```

HTTP client exceptions from Google APIs and Slack often include the request URL, partial headers, and sometimes token fragments. If the heartbeat runs under Task Scheduler, these logs may be captured in system logs.

**Recommendation:**
Log error types without full messages, or sanitize messages before logging:

```python
print(f"[{datetime.now()}] Gmail error (non-fatal): {type(e).__name__}")
```

---

### LOW Severity

#### L-1: SQLite `check_same_thread=False` Without Connection Pooling

**Severity:** LOW
**Location:** `chat/session.py:38, 77, 89, 112, 130`

**Description:**
SQLiteSessionStore creates a new connection for each operation with `check_same_thread=False`. While this avoids threading issues, it means multiple async tasks could write simultaneously without proper serialization. SQLite handles this via file-level locking, but concurrent writes may produce `database is locked` errors under high load.

**Recommendation:**
Consider using a single connection with a mutex, or `aiosqlite` for async-safe access.

---

#### L-2: Hook Execution Log May Contain Sensitive Timing Information

**Severity:** LOW
**Location:** `scripts/shared.py:192-220`

**Description:**
The hook execution log (`hook-execution.log`) records timestamps, hook names, triggers, and detail strings. While it rotates at 1000 lines, the detail field can contain context lengths and error messages that reveal usage patterns.

**Recommendation:**
Ensure the log file has restrictive permissions. The current rotation is adequate.

---

#### L-3: `sys.path.insert(0, ...)` Used Extensively

**Severity:** LOW
**Location:** Multiple files (engine.py:16, main.py:19-20, hooks/*.py, integrations/*.py)

**Description:**
Many files prepend to `sys.path` to enable cross-directory imports. While functional, this means any file placed in those directories would be importable and could shadow standard library modules. In a single-user environment this is low risk.

**Recommendation:**
Consider restructuring as a proper Python package with `pyproject.toml` to eliminate path manipulation. This is a code quality issue more than a security one.

---

#### L-4: File Lock Does Not Clean Up Stale Lock Files

**Severity:** LOW
**Location:** `scripts/shared.py:228-273`

**Description:**
The `file_lock()` context manager creates `.lock` files that persist after the process exits (the file handle is closed, releasing the lock, but the file remains). Over time, empty lock files accumulate in the state directory. This is cosmetic, not a security issue.

**Recommendation:**
Add a `try: lock_file.unlink()` in the finally block, or accept the cosmetic clutter.

---

#### L-5: Agent SDK Chat Engine Uses `acceptEdits` Permission Mode

**Severity:** LOW
**Location:** `chat/engine.py:83`

**Description:**
The chat engine's Agent SDK session uses `permission_mode="acceptEdits"`, which auto-approves file write operations. Combined with tools like `Write`, `Edit`, and `Bash`, a sufficiently crafted Slack message could instruct the agent to modify files on disk. However, since only the owner can send messages (enforced by the allowlist), this is intentional behavior.

**Recommendation:**
Document this trust model. If others ever gain access to the Slack bot, this should be reconsidered.

---

### INFO (Observations)

#### I-1: Credentials Properly Excluded from Git

**Severity:** INFO
**Location:** `.gitignore`

**Description:**
The `.gitignore` file correctly excludes:
- `.claude/scripts/.env` (API tokens)
- `.claude/scripts/integrations/google_credentials.json` (OAuth client secret)
- `.claude/scripts/integrations/google_token.json` (OAuth refresh/access token)
- `master.env` (multi-repo master credentials file)

This is good practice and prevents accidental credential commits.

---

#### I-2: OAuth Scopes Are Read-Only

**Severity:** INFO
**Location:** `scripts/config.py:50-53`

**Description:**
Google OAuth scopes are limited to `gmail.readonly` and `calendar.readonly`. This is the principle of least privilege — even if the token is compromised, it cannot send emails or modify calendar events.

---

#### I-3: Agent SDK Budget Limits Are Enforced

**Severity:** INFO
**Location:** `chat/engine.py:36`, `scripts/config.py:70`

**Description:**
Chat sessions have a `max_budget_usd` (default $2.00) and `max_turns` (default 25) limit, preventing runaway API costs from a single conversation.

---

#### I-4: SQL Injection Not Present — Parameterized Queries Used Throughout

**Severity:** INFO
**Location:** `chat/session.py`, `scripts/memory_index.py`, `scripts/memory_search.py`

**Description:**
All SQLite queries use parameterized statements (`?` placeholders). The FTS5 search in `memory_search.py` properly quotes user-provided terms and has fallback error handling for malformed queries. No SQL injection vectors were found.

---

#### I-5: Heartbeat Active Hours Check Prevents Off-Hours Execution

**Severity:** INFO
**Location:** `scripts/config.py:108-119`, `scripts/heartbeat.py:262`

**Description:**
The heartbeat checks if the current time is within configured active hours (8am-10pm CST) before running, preventing unnecessary API calls and notifications during off-hours.

---

#### I-6: Memory Flush Uses File Locking for Concurrency Safety

**Severity:** INFO
**Location:** `scripts/memory_flush.py:52-63`, `scripts/memory_reflect.py:88-98`

**Description:**
Both memory flush and reflection use `file_lock()` to prevent simultaneous runs. Additionally, memory flush has dedup logic to skip duplicate flushes for the same session within 60 seconds.

---

#### I-7: FTS5 Query Quoting Handles Special Characters

**Severity:** INFO
**Location:** `scripts/memory_search.py:56-63`

**Description:**
The `_quote_fts_query()` function wraps each search term in double quotes, which prevents FTS5 syntax injection (e.g., `OR`, `NOT`, `NEAR` operators). The fallback to raw query on operational error is also handled.

---

## Summary Statistics

| Severity | Count |
|----------|-------|
| Critical | 0     |
| High     | 3     |
| Medium   | 6     |
| Low      | 5     |
| Info     | 7     |
| **Total**| **21**|

## Key Recommendations (Priority Order)

1. **Sanitize error messages before sending to Slack** (H-1) — Quick fix, high value
2. **Reduce token logging verbosity** (H-2) — Quick fix
3. **Fail closed on empty allowlist** (H-3) — One-line fix, prevents misconfiguration
4. **Set restrictive file permissions on OAuth tokens** (M-2) — Quick fix
5. **Document the bash command blocklist as best-effort, not a security boundary** (M-1)
6. **Add cleanup for orphaned context files** (M-5)
7. **Sanitize integration error logs** (M-6)

## Assessment

For a single-user personal automation system, this codebase demonstrates thoughtful security practices:
- Proper secret management via `.env` and `.gitignore`
- User allowlisting on the chat bot
- Parameterized SQL queries
- Read-only OAuth scopes
- Budget and turn limits on Agent SDK sessions
- Bash command safety hooks

The findings above are primarily defense-in-depth improvements that would harden the system against edge cases, log exposure, and potential future multi-user scenarios. No critical vulnerabilities were found that would allow unauthorized access under the current single-user deployment model.
