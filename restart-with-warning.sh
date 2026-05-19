#!/bin/bash
# Scheduled Minecraft restart with chat warnings + colored countdown.
# Sends commands via Pterodactyl API; triggers Pterodactyl restart at T=0.

set -u

CONFIG="/etc/mc-backup/backup.env"
[ -f "$CONFIG" ] || { echo "Missing $CONFIG"; exit 1; }
# shellcheck disable=SC1090
source "$CONFIG"

WEBHOOK="/opt/mc-tools/webhook.sh"
LOG="/var/log/mc-restart.log"

log() { echo "$(date -Iseconds) $*" | tee -a "$LOG"; }
notify() {
  # Never let webhook failures break the restart flow.
  [ -x "$WEBHOOK" ] || return 0
  "$WEBHOOK" "$1" "$2" "$3" 2>/dev/null
  return 0
}

say_color() {
  local color="$1"
  local text="$2"
  local payload
  payload=$(printf '{"command":"tellraw @a {\\"text\\":\\"%s\\",\\"color\\":\\"%s\\",\\"bold\\":true}"}' "$text" "$color")
  curl -s -X POST \
    -H "Authorization: Bearer $PTERO_KEY" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -d "$payload" \
    "$PTERO_URL/api/client/servers/$SERVER_ID/command" > /dev/null
}

restart_server() {
  curl -s -X POST \
    -H "Authorization: Bearer $PTERO_KEY" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -d '{"signal":"restart"}' \
    "$PTERO_URL/api/client/servers/$SERVER_ID/power" > /dev/null
}

state=$(curl -s -H "Authorization: Bearer $PTERO_KEY" -H "Accept: application/json" \
  "$PTERO_URL/api/client/servers/$SERVER_ID/resources" | jq -r '.attributes.current_state')
if [ "$state" != "running" ]; then
  log "Server state is $state — skipping scheduled restart"
  exit 0
fi

log "=== Scheduled restart starting ==="
notify "Scheduled restart in 5 min" "The server will restart in 5 minutes. Warning announcements going out now." 16776960

say_color "yellow" "[!] Server restart in 5 minutes"
sleep 270

say_color "gold" "[!] Server restart in 30 seconds"
sleep 25

say_color "red"        "5..."
sleep 1
say_color "gold"       "4..."
sleep 1
say_color "yellow"     "3..."
sleep 1
say_color "green"      "2..."
sleep 1
say_color "aqua"       "1..."
sleep 1

log "Triggering Pterodactyl restart"
restart_server

log "=== Restart command sent ==="
