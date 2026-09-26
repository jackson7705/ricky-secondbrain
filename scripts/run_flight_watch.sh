#!/usr/bin/env bash
# Flight fare watcher runner for launchd (macOS). Hourly.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# launchd hands us a minimal PATH
export PATH="$PATH:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin"

uv run python flight_watch.py >> flight_watch_runs.log 2>&1 \
  && echo "$(date '+%Y-%m-%d %H:%M:%S') - flight watch ok" >> flight_watch_runs.log \
  || echo "$(date '+%Y-%m-%d %H:%M:%S') - flight watch FAILED" >> flight_watch_runs.log
