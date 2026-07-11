#!/usr/bin/env bash
# doctor.sh — preflight / health check for a Ricky install.
# Verifies prerequisites, secrets, auth, and connectivity. Read-only: changes
# nothing. Run any time to see what's green and what still needs setup.
#
#   bash .claude/deploy/doctor.sh
set -uo pipefail

# Resolve repo paths from this script's location (.../SecondBrain/.claude/deploy)
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$(cd "$HERE/.." && pwd)"
SCRIPTS_DIR="$CLAUDE_DIR/scripts"
ENV_FILE="$SCRIPTS_DIR/.env"

pass=0; warn=0; fail=0
ok()   { printf "  \033[32m✓\033[0m %s\n" "$1"; pass=$((pass+1)); }
wrn()  { printf "  \033[33m!\033[0m %s\n" "$1"; warn=$((warn+1)); }
bad()  { printf "  \033[31m✗\033[0m %s\n" "$1"; fail=$((fail+1)); }
have() { command -v "$1" >/dev/null 2>&1; }

# Read a key's value from .env (no export, tolerant of comments/spaces)
envval() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"' | xargs 2>/dev/null; }
req()  { if [ -n "$(envval "$1")" ]; then ok ".env $1 set"; else bad ".env $1 MISSING"; fi; }
opt()  { if [ -n "$(envval "$1")" ]; then ok ".env $1 set"; else wrn ".env $1 not set (optional)"; fi; }

echo "== Ricky doctor =="
echo "repo: $CLAUDE_DIR"
echo

echo "[1] System tools"
for t in uv python3 git node npx; do
  have "$t" && ok "$t ($(command -v $t))" || bad "$t not found"
done
have pdftoppm && ok "poppler/pdftoppm (PDF QA)" || wrn "poppler not found — 'brew install poppler' (needed for branded-PDF visual QA)"
have claude && ok "claude CLI" || bad "claude CLI not found — install Claude Code + run 'claude' to log in"
echo

echo "[2] Python env"
if [ -x "$SCRIPTS_DIR/.venv/bin/python3" ]; then
  ok ".venv present ($("$SCRIPTS_DIR/.venv/bin/python3" --version 2>&1))"
else
  bad ".venv missing — run: cd .claude/scripts && uv sync"
fi
echo

echo "[3] Config (.env)"
if [ -f "$ENV_FILE" ]; then ok ".env exists"; else bad ".env missing — copy scripts/.env.example → scripts/.env"; fi
req OWNER_NAME; req OWNER_EMAILS
req CLICKUP_API_TOKEN; req CLICKUP_OWNER_UID; req CLICKUP_INBOX_LIST_ID
req DRIVE_BRIEFINGS_FOLDER_ID
opt FATHOM_API_KEY; opt REDIS_URL; opt CONTEXT_RETRIEVER_AGENT_KEY; opt APIFY_TOKEN
echo

echo "[3b] Chat surface (need at least one)"
declare -a SURF=()
[ -n "$(envval BLUEBUBBLES_URL)" ] && [ -n "$(envval BLUEBUBBLES_PASSWORD)" ] && [ -n "$(envval IMESSAGE_ALLOWED_ADDRESSES)" ] && SURF+=("iMessage/BlueBubbles")
[ -n "$(envval TELEGRAM_BOT_TOKEN)" ] && [ -n "$(envval TELEGRAM_ALLOWED_USER_IDS)" ] && SURF+=("Telegram")
[ -n "$(envval DISCORD_BOT_TOKEN)" ] && [ -n "$(envval DISCORD_ALLOWED_USER_IDS)" ] && SURF+=("Discord")
[ -n "$(envval SLACK_BOT_TOKEN)" ] && [ -n "$(envval SLACK_APP_TOKEN)" ] && SURF+=("Slack")
if [ "${#SURF[@]}" -gt 0 ]; then ok "configured: ${SURF[*]}"; else bad "no chat surface configured — set BlueBubbles, Telegram, Discord, or Slack"; fi
notify="$(envval OWNER_NOTIFY_CHANNEL)"; [ -n "$notify" ] && ok "OWNER_NOTIFY_CHANNEL=$notify" || wrn "OWNER_NOTIFY_CHANNEL unset (auto-picks first configured surface)"
# Discord extra installed?
if [ -n "$(envval DISCORD_BOT_TOKEN)" ]; then
  "$SCRIPTS_DIR/.venv/bin/python3" -c "import discord" 2>/dev/null && ok "discord.py installed" || bad "Discord configured but discord.py missing — run: cd .claude/scripts && uv sync --extra discord"
fi
echo

echo "[4] Google OAuth"
[ -f "$SCRIPTS_DIR/integrations/google_credentials.json" ] && ok "google_credentials.json present" \
  || bad "google_credentials.json missing — see ONBOARDING.md (Google OAuth)"
if ls "$SCRIPTS_DIR"/integrations/google_token*.json >/dev/null 2>&1; then
  ok "google token(s): $(ls "$SCRIPTS_DIR"/integrations/google_token*.json 2>/dev/null | xargs -n1 basename | tr '\n' ' ')"
else
  bad "no google_token*.json — run: cd .claude/scripts && uv run python setup_auth.py --account <profile>"
fi
echo

echo "[5] MCP config (~/.claude.json)"
if [ -f "$HOME/.claude.json" ]; then
  python3 -c "import json;d=json.load(open('$HOME/.claude.json'));m=d.get('mcpServers',{});print('  servers:',', '.join(m) or '(none)')" 2>/dev/null \
    && ok "~/.claude.json parses" || wrn "~/.claude.json present but unreadable"
else
  wrn "~/.claude.json missing — Apify/Redis MCP tools unavailable (see ONBOARDING.md)"
fi
echo

echo "[6] BlueBubbles reachable"
BB_URL="$(envval BLUEBUBBLES_URL)"; BB_PW="$(envval BLUEBUBBLES_PASSWORD)"
if [ -n "$BB_URL" ] && [ -n "$BB_PW" ]; then
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 6 \
         --get "$BB_URL/api/v1/ping" --data-urlencode "password=$BB_PW" 2>/dev/null)
  case "$code" in
    200)     ok "BlueBubbles up + auth OK (200)" ;;
    401|403) wrn "BlueBubbles up but ping auth failed ($code) — verify BLUEBUBBLES_PASSWORD" ;;
    000|"")  bad "BlueBubbles NOT reachable at $BB_URL — is the server app running?" ;;
    *)       ok "BlueBubbles reachable ($BB_URL, HTTP $code)" ;;
  esac
else
  wrn "BlueBubbles URL/password not set — skipping reachability"
fi
echo

echo "[7] launchd jobs"
PREFIX="$(envval OWNER_LAUNCHD_SLUG)"; [ -n "$PREFIX" ] || PREFIX="$(id -un | tr '[:upper:]' '[:lower:]')secondbrain"
n=$(launchctl list 2>/dev/null | grep -c "com\.$PREFIX\.")
if [ "$n" -gt 0 ]; then ok "$n launchd job(s) loaded (com.$PREFIX.*)"; else wrn "no com.$PREFIX.* jobs loaded — run deploy/gen_launchagents.py"; fi
echo

echo "== summary: $pass ok, $warn warn, $fail fail =="
[ "$fail" -eq 0 ] && echo "Ricky looks healthy. ✅" || echo "Fix the ✗ items above, then re-run doctor.sh."
exit 0
