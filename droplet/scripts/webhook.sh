#!/bin/bash
# Reusable Discord webhook helper.
# Usage: webhook.sh "Title" "Description" <color-int>
#
# IMPORTANT: This script ALWAYS exits 0 — never causes a caller to fail.
# If webhook is unconfigured or Discord is down, it silently no-ops.
#
# Colors:
#   3447003   blue   (info)
#   5763719   green  (success / join)
#   9807270   grey   (leave)
#   15105570  orange (restart triggered)
#   15548997  red    (error / crash)
#   16776960  yellow (warning)
#   10181046  purple (event)

WEBHOOK_ENV="/etc/mc-backup/webhook.env"

# Bail early (success) if not configured — must NEVER return non-zero.
[ -f "$WEBHOOK_ENV" ] || exit 0

# shellcheck disable=SC1090
source "$WEBHOOK_ENV" 2>/dev/null || exit 0

# Empty / unset URL? no-op.
[ -n "${WEBHOOK_URL:-}" ] || exit 0

# Required tools missing? no-op (don't crash).
command -v curl >/dev/null 2>&1 || exit 0
command -v jq   >/dev/null 2>&1 || exit 0

# Two modes:
#   webhook.sh "plain message"               → plain content line
#   webhook.sh "Title" "Description" <color> → embed (titled, colored, timestamped)
if [ $# -le 1 ]; then
  PAYLOAD=$(jq -n --arg c "${1:-}" '{content:$c}' 2>/dev/null) || exit 0
else
  TITLE="$1"
  DESC="${2:-}"
  COLOR="${3:-3447003}"
  PAYLOAD=$(jq -n \
    --arg t "$TITLE" \
    --arg d "$DESC" \
    --argjson c "$COLOR" \
    '{embeds:[{title:$t, description:$d, color:$c, timestamp:(now | todate)}]}' \
    2>/dev/null) || exit 0
fi

# Fire the webhook. Suppress all errors. Short timeout so we don't hang the caller.
# --max-time 5s caps the whole operation; if Discord is down we move on fast.
curl -sS --max-time 5 -X POST \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" \
  "$WEBHOOK_URL" >/dev/null 2>&1

# Always succeed.
exit 0
