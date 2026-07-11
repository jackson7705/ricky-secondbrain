#!/usr/bin/env bash
# bootstrap.sh — stand up a fresh Ricky on a new Mac.
# Idempotent: safe to re-run. It automates everything that CAN be automated and
# clearly tells you the few manual steps only you can do (BlueBubbles sign-in,
# Google OAuth consent, pasting API keys).
#
#   bash .claude/deploy/bootstrap.sh
#
# Prereqs it will check/help install: Homebrew, uv, poppler, node, Claude Code.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$(cd "$HERE/.." && pwd)"
PROJECT_DIR="$(cd "$CLAUDE_DIR/.." && pwd)"
SCRIPTS_DIR="$CLAUDE_DIR/scripts"

say()  { printf "\n\033[1;36m▶ %s\033[0m\n" "$1"; }
ok()   { printf "  \033[32m✓\033[0m %s\n" "$1"; }
todo() { printf "  \033[33m→ MANUAL:\033[0m %s\n" "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

echo "=============================================="
echo "  Ricky bootstrap"
echo "  repo: $PROJECT_DIR"
echo "=============================================="

# ── 1. Homebrew + system deps ────────────────────────────────────────────────
say "1/7  System dependencies (Homebrew, uv, poppler, node)"
if ! have brew; then
  todo "Homebrew not found. Install it, then re-run this script:"
  echo '     /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  exit 1
fi
ok "Homebrew present"
for pkg in uv poppler node; do
  if have "${pkg%% *}" || brew list "$pkg" >/dev/null 2>&1; then ok "$pkg present"
  else say "installing $pkg…"; brew install "$pkg" && ok "$pkg installed"; fi
done

# ── 2. Claude Code login ─────────────────────────────────────────────────────
say "2/7  Claude Code"
if have claude; then
  ok "claude CLI present"
  if [ -f "$HOME/.claude/.credentials.json" ]; then ok "Claude credentials found"
  else todo "Run 'claude' once and sign in (the SDK reuses that login)."; fi
else
  todo "Install Claude Code (https://claude.com/claude-code), then run 'claude' to sign in."
fi

# ── 3. Python env ────────────────────────────────────────────────────────────
say "3/7  Python environment (uv sync)"
( cd "$SCRIPTS_DIR" && uv sync ) && ok ".venv ready" || todo "uv sync failed — check $SCRIPTS_DIR/pyproject.toml"

# ── 4. compiler subrepo (third-party) ────────────────────────────────────────
say "4/7  Memory compiler (third-party subrepo)"
if [ -d "$CLAUDE_DIR/compiler/.git" ]; then ok "compiler/ already cloned"
else
  git clone https://github.com/coleam00/claude-memory-compiler.git "$CLAUDE_DIR/compiler" \
    && ok "compiler/ cloned" || todo "clone coleam00/claude-memory-compiler into .claude/compiler"
fi

# ── 5. .env ──────────────────────────────────────────────────────────────────
say "5/7  Configuration (.env)"
if [ -f "$SCRIPTS_DIR/.env" ]; then
  ok ".env already exists (leaving it alone)"
else
  cp "$SCRIPTS_DIR/.env.example" "$SCRIPTS_DIR/.env"
  ok "created scripts/.env from template"
  todo "Edit $SCRIPTS_DIR/.env and fill in YOUR values (owner identity, BlueBubbles, Google, ClickUp…)."
fi

# ── 6. MCP config (~/.claude.json) ───────────────────────────────────────────
say "6/7  MCP servers (~/.claude.json)"
if [ -f "$HOME/.claude.json" ] && python3 -c "import json,sys;d=json.load(open('$HOME/.claude.json'));sys.exit(0 if d.get('mcpServers') else 1)" 2>/dev/null; then
  ok "~/.claude.json already has mcpServers"
else
  todo "Add Apify + Redis-Iris MCP servers to ~/.claude.json — see ONBOARDING.md → MCP config (uses APIFY_TOKEN / CONTEXT_RETRIEVER_* from your .env)."
fi

# ── 7. Manual checklist + launchd ────────────────────────────────────────────
say "7/7  Remaining manual steps"
todo "BlueBubbles: install the server app (https://bluebubbles.app) on THIS Mac, sign into iMessage, set a password + enable Private API, then put URL/password in .env."
todo "Google OAuth: drop google_credentials.json into scripts/integrations/, then: cd .claude/scripts && uv run python setup_auth.py --account <profile>"
todo "Vault: create your own private vault repo and clone it to $PROJECT_DIR/Dynamous (see ONBOARDING.md → Vault)."
echo
say "When .env + Google + BlueBubbles are done, install the scheduled jobs:"
echo "     cd $SCRIPTS_DIR && uv run python ../deploy/gen_launchagents.py"
echo
say "Then verify everything:"
echo "     bash $CLAUDE_DIR/deploy/doctor.sh"
echo
echo "Bootstrap finished. Green-light with doctor.sh before relying on the jobs."
