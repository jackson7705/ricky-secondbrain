#!/bin/bash
# bluebubbles_watchdog.sh — restart BlueBubbles if it's been down >5 minutes.
#
# Fires every 60s via com.jasonsecondbrain.bluebubbles-watchdog. Probes the
# BlueBubbles HTTP API at localhost:1234. A response (any HTTP code 200–499)
# means the server is alive. No response → start tracking downtime; if the
# outage exceeds DOWN_THRESHOLD_SECONDS, kickstart the BlueBubbles launchd
# job and reset state.
#
# The 5-minute gate keeps us from hammering the service during transient
# blips (e.g. Mac waking from sleep takes ~30s for BlueBubbles to bind to
# the port). It also acts as cooldown — we won't double-restart within the
# threshold even if the first kickstart didn't take.

set -uo pipefail

STATE_FILE="/tmp/jasonsecondbrain/bluebubbles-down-since.txt"
LOG_FILE="/tmp/jasonsecondbrain/bluebubbles-watchdog.log"
DOWN_THRESHOLD_SECONDS=120  # 2 minutes — fast enough to recover before Ricky is missed mid-shoot
BLUEBUBBLES_LABEL="com.bluebubbles.server"
CHAT_LABEL="com.jasonsecondbrain.chat"
PROBE_URL="http://localhost:1234/"
PROBE_TIMEOUT=3

mkdir -p "$(dirname "$STATE_FILE")"

log() {
  printf '%s %s\n' "$(date -Iseconds)" "$1" >> "$LOG_FILE"
}

# Probe: any HTTP response (even 401/403) means the server is binding
# the port and processing requests. Connection refused / timeout = down.
http_code=$(curl -s -o /dev/null -w '%{http_code}' --max-time "$PROBE_TIMEOUT" "$PROBE_URL" 2>/dev/null || echo "000")

if [[ "$http_code" != "000" && "$http_code" -lt 500 ]]; then
  # Server is responding — clear any pending down-state.
  if [[ -f "$STATE_FILE" ]]; then
    log "RECOVERED (http $http_code) — clearing down-state"
    rm -f "$STATE_FILE"
  fi
  exit 0
fi

# Server is down. Track first-failure timestamp; restart if elapsed > threshold.
now=$(date +%s)

if [[ ! -f "$STATE_FILE" ]]; then
  echo "$now" > "$STATE_FILE"
  log "DOWN detected (http $http_code) — starting countdown"
  exit 0
fi

down_since=$(cat "$STATE_FILE" 2>/dev/null || echo "$now")
elapsed=$((now - down_since))

if (( elapsed >= DOWN_THRESHOLD_SECONDS )); then
  log "DOWN >${elapsed}s — kickstarting $BLUEBUBBLES_LABEL"
  uid=$(id -u)
  if /bin/launchctl kickstart -k "gui/${uid}/${BLUEBUBBLES_LABEL}" >>"$LOG_FILE" 2>&1; then
    log "kickstart issued"
    # BlueBubbles takes a few seconds to bind :1234. Give it a moment, then
    # bounce the chat engine so Ricky reconnects immediately instead of
    # waiting on its own crash-loop respawn timing.
    sleep 8
    if /bin/launchctl kickstart -k "gui/${uid}/${CHAT_LABEL}" >>"$LOG_FILE" 2>&1; then
      log "chat engine kicked — Ricky reconnecting"
    else
      log "chat kick FAILED (exit $?)"
    fi
  else
    log "kickstart FAILED (exit $?)"
  fi
  # Reset state regardless — next poll re-evaluates. If kickstart didn't
  # take, we'll start a new countdown and try again after the threshold.
  rm -f "$STATE_FILE"
else
  log "DOWN ${elapsed}s/${DOWN_THRESHOLD_SECONDS}s — waiting"
fi
