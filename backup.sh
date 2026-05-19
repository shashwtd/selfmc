#!/bin/bash
# Minecraft backup via restic → Google Drive
# Triggered by: cron (daily) or idle-monitor.py (idle)

set -u

CONFIG="/etc/mc-backup/backup.env"
[ -f "$CONFIG" ] || { echo "Missing $CONFIG"; exit 1; }
# shellcheck disable=SC1090
source "$CONFIG"

WEBHOOK="/opt/mc-tools/webhook.sh"
LOG="/var/log/mc-backup.log"
LOCKFILE="/tmp/mc-backup.lock"

export RESTIC_REPOSITORY
export RESTIC_PASSWORD_FILE
export RESTIC_PACK_SIZE=128
RESTIC_RCLONE_ARGS=(-o "rclone.args=serve restic --stdio --b2-hard-delete")

log() { echo "$(date -Iseconds) $*" | tee -a "$LOG"; }
notify() {
  # Never let webhook failures break the backup.
  [ -x "$WEBHOOK" ] || return 0
  "$WEBHOOK" "$1" "$2" "$3" 2>/dev/null
  return 0
}

exec 9>"$LOCKFILE"
flock -n 9 || { log "Backup already running, skipping"; exit 0; }

send_cmd() {
  curl -s -X POST \
    -H "Authorization: Bearer $PTERO_KEY" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json" \
    -d "{\"command\":\"$1\"}" \
    "$PTERO_URL/api/client/servers/$SERVER_ID/command" > /dev/null
}

get_state() {
  curl -s \
    -H "Authorization: Bearer $PTERO_KEY" \
    -H "Accept: application/json" \
    "$PTERO_URL/api/client/servers/$SERVER_ID/resources" \
    | jq -r '.attributes.current_state'
}

START_TS=$(date +%s)
log "=== Backup started ==="

restic "${RESTIC_RCLONE_ARGS[@]}" unlock 2>/dev/null || true

STATE=$(get_state)
log "Server state: $STATE"

if [ "$STATE" = "running" ]; then
  log "Pausing world saves via API"
  send_cmd "save-off"
  send_cmd "save-all flush"
  sleep 5
fi

log "Running restic backup of world folders"
BACKUP_OUTPUT=$(restic "${RESTIC_RCLONE_ARGS[@]}" backup \
  "$WORLD_DIR/world" "$WORLD_DIR/world_nether" "$WORLD_DIR/world_the_end" \
  --tag auto 2>&1)
BACKUP_RC=$?
echo "$BACKUP_OUTPUT" >> "$LOG"

if [ "$STATE" = "running" ]; then
  log "Resuming world saves"
  send_cmd "save-on"
fi

if [ $BACKUP_RC -ne 0 ]; then
  log "Restic backup FAILED (rc=$BACKUP_RC)"
  notify "Backup FAILED" "Restic exited with code $BACKUP_RC. Check /var/log/mc-backup.log on the droplet." 15548997
  exit 1
fi

# Extract size added & duration from restic output for the notification
ADDED=$(echo "$BACKUP_OUTPUT" | grep -oE 'Added to the repo: [^ ]+ [KMGT]?iB' | sed 's/Added to the repo: //')
[ -z "$ADDED" ] && ADDED="(small)"
DURATION=$(( $(date +%s) - START_TS ))

log "Restic backup OK ($ADDED in ${DURATION}s)"

log "Pruning old snapshots"
restic "${RESTIC_RCLONE_ARGS[@]}" forget --keep-last 1 --keep-daily 30 --keep-weekly 12 --prune >> "$LOG" 2>&1 \
  || log "Prune had issues (non-fatal)"

log "=== Backup done ==="
notify "Backup complete ✓" "**Added:** $ADDED\n**Duration:** ${DURATION}s\n**Server was:** $STATE" 5763719
