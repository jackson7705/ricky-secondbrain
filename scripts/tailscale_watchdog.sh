#!/bin/bash
# tailscale_watchdog.sh — keep the Tailscale tunnel up so Ricky stays reachable.
#
# Companion to bluebubbles_watchdog.sh. Fires every 60s via
# com.jasonsecondbrain.tailscale-watchdog. Tailscale on this Mac is the macsys
# (GUI) build: the tunnel lives inside the logged-in session, so a restart that
# lands anywhere other than Jason's desktop leaves the Mac off the tailnet and
# unreachable from outside the office.
#
# Two failure shapes, two repairs:
#   1. Tailscale.app isn't running at all  -> relaunch it (backgrounded, hidden)
#   2. App is running but BackendState != Running -> `tailscale up` to reconnect
#
# Same 2-minute gate as the BlueBubbles watchdog: long enough to ride out a
# wake-from-sleep reconnect (~30s), short enough to self-heal before anyone
# notices. The gate doubles as a cooldown so we don't relaunch in a tight loop.

set -uo pipefail

STATE_FILE="/tmp/jasonsecondbrain/tailscale-down-since.txt"
LOG_FILE="/tmp/jasonsecondbrain/tailscale-watchdog.log"
DOWN_THRESHOLD_SECONDS=120
TAILSCALE_BIN="/Applications/Tailscale.app/Contents/MacOS/tailscale"

mkdir -p "$(dirname "$STATE_FILE")"

log() {
  printf '%s %s\n' "$(date -Iseconds)" "$1" >> "$LOG_FILE"
}

# Probe. BackendState comes straight from the daemon; "Running" is the only
# value that means traffic actually flows. "Stopped"/"NeedsLogin"/"NoState" are
# all down as far as reaching this Mac goes. If the binary can't be reached at
# all (app not launched), status exits non-zero and we get an empty string.
state=$("$TAILSCALE_BIN" status --json 2>/dev/null \
  | /usr/bin/python3 -c 'import sys,json; print(json.load(sys.stdin).get("BackendState",""))' 2>/dev/null)
state="${state:-Unreachable}"

if [[ "$state" == "Running" ]]; then
  if [[ -f "$STATE_FILE" ]]; then
    log "RECOVERED (state $state) — clearing down-state"
    rm -f "$STATE_FILE"
  fi
  exit 0
fi

now=$(date +%s)

if [[ ! -f "$STATE_FILE" ]]; then
  echo "$now" > "$STATE_FILE"
  log "DOWN detected (state $state) — starting countdown"
  exit 0
fi

down_since=$(cat "$STATE_FILE" 2>/dev/null || echo "$now")
elapsed=$((now - down_since))

if (( elapsed < DOWN_THRESHOLD_SECONDS )); then
  log "DOWN ${elapsed}s/${DOWN_THRESHOLD_SECONDS}s (state $state) — waiting"
  exit 0
fi

log "DOWN >${elapsed}s (state $state) — repairing"

# Repair 1: no daemon answering means the app isn't up. Launch it hidden and
# backgrounded so it never steals focus from whatever is on screen.
if [[ "$state" == "Unreachable" ]] || ! /usr/bin/pgrep -qf "Tailscale.app/Contents/MacOS/Tailscale"; then
  if /usr/bin/open -gj -a Tailscale >>"$LOG_FILE" 2>&1; then
    log "relaunched Tailscale.app"
  else
    log "relaunch FAILED (exit $?)"
  fi
  sleep 10
fi

# Repair 2: app is up but the tunnel is down. WantRunning is already true in
# prefs and the node is logged in, so a bare `up` reconnects without prompting
# for auth. --timeout keeps us from wedging the 60s watchdog slot.
state=$("$TAILSCALE_BIN" status --json 2>/dev/null \
  | /usr/bin/python3 -c 'import sys,json; print(json.load(sys.stdin).get("BackendState",""))' 2>/dev/null)
if [[ "${state:-}" != "Running" ]]; then
  if "$TAILSCALE_BIN" up --timeout 30s >>"$LOG_FILE" 2>&1; then
    log "tailscale up succeeded"
  else
    log "tailscale up FAILED (exit $?) — may need interactive re-auth"
  fi
else
  log "RECOVERED after relaunch"
fi

# Reset regardless — next poll re-evaluates and restarts the countdown if the
# repair didn't take.
rm -f "$STATE_FILE"
