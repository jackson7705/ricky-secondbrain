#!/usr/bin/env bash
# Start the Second Brain chat interface
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/../scripts"
uv run python "$SCRIPT_DIR/main.py" "$@"
