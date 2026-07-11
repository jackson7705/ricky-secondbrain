#!/usr/bin/env bash
# Vault sync runner for systemd timer (Linux VPS)
# Runs git-sync to synchronize Obsidian vault with GitHub

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Resolve vault path (two levels up from .claude/scripts/, then into the vault folder)
# Change "Vault" below to match your actual vault folder name
VAULT_DIR="$(cd "$SCRIPT_DIR/../../Vault" && pwd)"

cd "$VAULT_DIR" && bash "$SCRIPT_DIR/git-sync"
SYNC_RESULT=$?

if [ $SYNC_RESULT -eq 0 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Vault sync OK" >> "$SCRIPT_DIR/vault_sync_runs.log"
elif [ $SYNC_RESULT -eq 1 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Vault sync CONFLICT - manual resolution needed" >> "$SCRIPT_DIR/vault_sync_runs.log"
else
    echo "$(date '+%Y-%m-%d %H:%M:%S') - Vault sync FAILED exit=$SYNC_RESULT" >> "$SCRIPT_DIR/vault_sync_runs.log"
fi

exit $SYNC_RESULT
