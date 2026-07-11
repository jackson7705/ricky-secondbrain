# Onboarding a new Ricky (duplicate across the team)

This guide stands up a **fully independent Ricky** for a teammate: their own
identity, their own accounts and API keys, their own private memory vault.
Nothing is shared between people — each Ricky texts its own owner, files tasks
in its own ClickUp, and remembers its own things.

> **Time:** ~45–60 min, most of it waiting on account/API signups.
> **You need:** a Mac the teammate controls, their Apple ID (for iMessage), and
> the ability to create the accounts in the checklist below.

---

## How Ricky is put together (30-second tour)

| Layer | What it is |
|---|---|
| **Chat engine** (`.claude/chat/`) | Long-running process bridging a **chat surface** (Telegram / Discord / iMessage / Slack — any or several) ↔ Claude Agent SDK. This is "talking to Ricky." |
| **Autonomous jobs** (`.claude/scripts/`) | Scheduled scripts: `loose_ends` (inbox→tasks), `fathom_sweep` (meetings→tasks), `eod_email` (draft replies), `heartbeat`, daily briefs, invoice router, memory tools. |
| **Skills** (`.claude/skills/`) | Reusable capabilities: email-triage, invoice-router, locafy-documents (branded PDFs), direct-integrations, design-system, etc. |
| **Memory vault** (`Dynamous/`) | An Obsidian vault, git-synced. Ricky's long-term memory. **Per-person.** |
| **Scheduler** | macOS **launchd** jobs (`com.<slug>.<job>`) keep everything running. |

Everything that differs per person lives in **`.claude/scripts/.env`** (secrets +
identity) and a few OAuth token files — none of which are in git.

---

## Prerequisites (accounts the teammate needs)

Create/collect these first — the config step needs them:

- [ ] **Claude Code** subscription + login (`claude` CLI)
- [ ] **A chat surface** — a Telegram or Discord bot (any OS), or an Apple ID +
      Mac for iMessage/BlueBubbles. Pick whatever fits their machine.
- [ ] **Google account** (Gmail + Calendar + Drive) they'll let Ricky act as
- [ ] **ClickUp** account + a personal API token + an "Inbox" list
- [ ] *(optional)* **Fathom** API key — meeting action items
- [ ] *(optional)* **Redis Iris** URL + Context Retriever agent key
- [ ] *(optional)* **Apify** token — web scraping

---

## Quick start

```bash
# 1. Clone the code repo into the SecondBrain folder
git clone https://github.com/jackson7705/ricky-secondbrain.git ~/SecondBrain/.claude
#    (or copy the whole SecondBrain/ tree; the repo IS the .claude/ dir)

# 2. Run the bootstrapper — installs deps, venv, compiler, seeds .env
bash ~/SecondBrain/.claude/deploy/bootstrap.sh

# 3. Fill in YOUR values
$EDITOR ~/SecondBrain/.claude/scripts/.env      # see "Config" below

# 4. Do the manual account steps (BlueBubbles, Google OAuth, MCP, Vault) — below

# 5. Verify everything is green
bash ~/SecondBrain/.claude/deploy/doctor.sh

# 6. Install the scheduled jobs (only once doctor is happy)
cd ~/SecondBrain/.claude/scripts && uv run python ../deploy/gen_launchagents.py
```

`doctor.sh` is your source of truth — re-run it any time; it changes nothing and
tells you exactly what's still red.

---

## Config: `.claude/scripts/.env`

`bootstrap.sh` copies `.env.example` → `.env`. Fill in the **required** blocks.
The file itself documents every key; the essentials:

| Key | What / where to get it |
|---|---|
| `OWNER_NAME` | Teammate's name |
| `OWNER_PHONE` | Their mobile, digits only w/ country code (e.g. `14155550123`) |
| `OWNER_EMAILS` | Their work emails, comma-separated |
| `OWNER_LAUNCHD_SLUG` | Job namespace, e.g. `taylorsecondbrain` (defaults to `<macuser>secondbrain`) |
| *chat surface* | Pick ≥1: Telegram / Discord / BlueBubbles / Slack keys — see step 1 below |
| `OWNER_NOTIFY_CHANNEL` | Where job pings go: `telegram`/`discord`/`bluebubbles`/`slack` (blank = auto) |
| `DEFAULT_GOOGLE_ACCOUNT` | The OAuth profile name they'll authorize |
| `GOOGLE_CALENDAR_ID` | `primary` or a specific calendar |
| `DRIVE_BRIEFINGS_FOLDER_ID` | Drive folder id (from its URL) where Ricky uploads docs |
| `CLICKUP_API_TOKEN` | ClickUp → Settings → Apps → Generate (`pk_…`) |
| `CLICKUP_WORKSPACE_ID` / `CLICKUP_OWNER_UID` / `CLICKUP_INBOX_LIST_ID` | Workspace + their user id + Inbox list id |

---

## Manual steps (the parts only a human can do)

### 1. Chat surface — pick at least one (talk to Ricky)
Ricky listens on any combination of these at once. **BlueBubbles is Mac-only**;
Telegram and Discord work on any OS, so use those on Windows/Linux (or by
preference). Set the matching keys in `.env`, then `doctor.sh` step [3b] lists
what's configured.

**Telegram (easiest, any OS)**
1. Message **@BotFather** → `/newbot` → copy the token → `TELEGRAM_BOT_TOKEN`.
2. Get your numeric id from **@userinfobot** → `TELEGRAM_ALLOWED_USER_IDS`.
3. (For job pings) set `OWNER_TELEGRAM_CHAT_ID` to that same id.

**Discord (any OS)**
1. https://discord.com/developers → New Application → **Bot** → copy token → `DISCORD_BOT_TOKEN`.
2. Enable **Message Content Intent** (Bot settings).
3. Enable Developer Mode → right-click yourself → Copy User ID → `DISCORD_ALLOWED_USER_IDS`.
4. Install the extra: `cd .claude/scripts && uv sync --extra discord`.
5. (For job pings) create a channel Webhook → `OWNER_DISCORD_WEBHOOK_URL`.

**iMessage via BlueBubbles (Mac only)**
1. Install the **BlueBubbles Server** on this Mac → https://bluebubbles.app
2. Sign it into the teammate's iMessage account.
3. Set a **server password**, enable the **Private API**.
4. `BLUEBUBBLES_URL` (default `http://localhost:1234`) + `BLUEBUBBLES_PASSWORD` +
   `IMESSAGE_ALLOWED_ADDRESSES`. `doctor.sh` [6] → **"BlueBubbles up + auth OK (200)"**.

**Slack** — see `.env.example` §11 (`SLACK_BOT_TOKEN` + `SLACK_APP_TOKEN`).

> **Job notifications** (loose_ends / fathom / eod) go to the surface named in
> `OWNER_NOTIFY_CHANNEL` (`bluebubbles|telegram|discord|slack`); if blank, the
> first configured one is used. Test it: `uv run python notify_owner.py "hi"`.

### 2. Google OAuth
1. https://console.cloud.google.com → new project.
2. Enable **Gmail, Calendar, Drive, Sheets** APIs.
3. **OAuth consent screen** → External → fill in → **Publish** (skips the
   7-day token expiry).
4. **Credentials** → OAuth client ID → **Desktop app** → download JSON →
   save as `.claude/scripts/integrations/google_credentials.json`.
5. Authorize:
   ```bash
   cd ~/SecondBrain/.claude/scripts && uv run python setup_auth.py --account <profile>
   ```
   A browser opens; approve. Token lands at `integrations/google_token_<profile>.json`.
   Set `DEFAULT_GOOGLE_ACCOUNT=<profile>` in `.env`.

### 3. MCP servers (`~/.claude.json`)
Ricky's Apify + Redis-Iris tools are configured **outside** the repo, in
`~/.claude.json`. Add (using the teammate's own keys):
```jsonc
{
  "mcpServers": {
    "apify": {
      "type": "stdio", "command": "npx",
      "args": ["-y", "@apify/actors-mcp-server"],
      "env": { "APIFY_TOKEN": "apify_api_…" }
    },
    "redis-iris": {                              // optional
      "type": "http",
      "url": "https://<your-context-surfaces-host>/mcp",
      "headers": { "X-API-Key": "cs_agent_…" }
    }
  }
}
```
Skip `redis-iris` if they're not using structured memory.

### 4. Memory vault (per-person, private)
Each Ricky needs its own vault repo at `~/SecondBrain/Dynamous`:
1. Create a **new private GitHub repo** (e.g. `taylor-second-brain-vault`).
2. Seed it from the starter structure (`Dynamous/Memory/` with `SOUL.md`,
   `USER.md`, `MEMORY.md`, `HEARTBEAT.md`, `daily/`). Copy the templates from an
   existing vault and **strip the owner-specific content** — keep the structure,
   replace the facts.
3. Clone it to `~/SecondBrain/Dynamous` and set the git-sync config per
   `CLAUDE.md` → *Vault Sync*.
4. Fill in `SOUL.md` (personality/voice) and `USER.md` (their accounts/prefs).

---

## Verifying & managing the jobs

```bash
# What's loaded (uses OWNER_LAUNCHD_SLUG; default com.<macuser>secondbrain.*)
launchctl list | grep secondbrain

# (Re)install / update all jobs — idempotent, safe to re-run after code changes
cd ~/SecondBrain/.claude/scripts && uv run python ../deploy/gen_launchagents.py

# Preview without touching the system
uv run python ../deploy/gen_launchagents.py --print --only chat

# Just one or two jobs
uv run python ../deploy/gen_launchagents.py --only chat,heartbeat

# Tail a job's log (LOG dir = /tmp/<slug>)
tail -f /tmp/<slug>/chat.log
```

The 14 jobs and their schedules are the templates in
`deploy/launchd/templates/` — the generator substitutes this machine's paths and
the owner's slug into each.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `doctor.sh` BlueBubbles ✗ | Server app not running, or wrong password. Open BlueBubbles, confirm it's connected to iMessage. |
| Ricky doesn't reply to texts | `IMESSAGE_ALLOWED_ADDRESSES` must include the sender; check `launchctl list \| grep chat` and `tail /tmp/<slug>/chat.log`. |
| Google calls fail | Token missing/expired — re-run `setup_auth.py --account <profile>`; make sure the consent screen is **Published**. |
| Tasks not filing | `CLICKUP_*` values — verify token, `CLICKUP_OWNER_UID`, `CLICKUP_INBOX_LIST_ID`. |
| Jobs not running | Re-run `gen_launchagents.py`; check `/tmp/<slug>/<job>-stderr.log`. |
| MCP tools absent | `~/.claude.json` missing/!parsing — see MCP step. |

---

## Security model (do not weaken)

- **Secrets never enter git.** `.env`, `google_*token*.json`, `google_credentials.json`,
  and `data/` are all git-ignored. Verify with `git -C ~/SecondBrain/.claude status`.
- **Email is approval-gated.** `eod_email` only ever **drafts**; nothing is sent
  without the owner's explicit per-draft "send it." Never wire an autonomous send.
  (See `.claude/skills/email-triage/SKILL.md`.)
- **Each Ricky is isolated.** Own accounts, own vault, own keys → one person's
  blast radius never touches another's.
