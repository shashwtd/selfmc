# Discord Webhook Integration (Spec for future implementation)

This document tells a future agent exactly how to wire up Discord notifications. It's not implemented yet.

## How Discord webhooks work

A Discord webhook is just a URL. You `POST` JSON to it and a message appears in the target channel.

```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"content":"Hello"}' \
  https://discord.com/api/webhooks/<id>/<token>
```

The webhook URL **only allows posting** to the channel — it can't read messages, manage the server, or do anything else. Treat it as low-sensitivity but don't commit to public git.

## Where to store the URL

Create on the droplet:

```bash
echo 'WEBHOOK_URL="https://discord.com/api/webhooks/..."' > /etc/mc-backup/webhook.env
chmod 600 /etc/mc-backup/webhook.env
```

Any script that sends webhooks should source this file.

## Payload structure

Two formats:

**Plain text (simplest):**
```json
{"content": "Player Steve joined the game"}
```

**Rich embed (preferred, looks nicer):**
```json
{
  "embeds": [{
    "title": "Player joined",
    "description": "**Steve** is now online",
    "color": 5763719,
    "footer": {"text": "play.yourdomain.com"},
    "timestamp": "2026-05-19T03:45:00Z"
  }]
}
```

Color is a decimal integer of an RGB hex. Useful values:
- Green (success): `5763719`
- Red (error): `15548997`
- Yellow (warning): `16776960`
- Blue (info): `3447003`
- Purple (event): `10181046`

## Events to wire up

| Event | Source | Where to hook |
|---|---|---|
| Player joined | server log `joined the game` | new log-tailing daemon (see below) |
| Player left | server log `left the game` | same log-tailer |
| Player died | server log `was slain`, `fell from`, `drowned`, etc. | same log-tailer |
| Server started | server log `Done (Xs)! For help` | same log-tailer |
| Server stopped | server log `Stopping server` | same log-tailer |
| Backup started | `backup.sh` line: `log "=== Backup started ==="` | edit `backup.sh` |
| Backup completed | `backup.sh` line: `log "=== Backup done ==="` | edit `backup.sh`, include duration + size |
| Backup failed | `backup.sh` error branch | edit `backup.sh` |
| Idle backup triggered | `idle-monitor.py` decision point | edit Python script |
| Scheduled restart warning | `restart-with-warning.sh` start | edit script |
| Restart triggered | end of `restart-with-warning.sh` | edit script |
| Unexpected crash | server log `Server thread`+`Exception` patterns | log-tailer |

## Implementation outline

### Step 1: Webhook helper function

Put this in `/opt/mc-tools/webhook.sh`:

```bash
#!/bin/bash
# Usage: webhook.sh "Title" "Description" <color-int>
source /etc/mc-backup/webhook.env
TITLE="$1"
DESC="$2"
COLOR="${3:-3447003}"
curl -s -X POST -H "Content-Type: application/json" \
  -d "$(jq -n --arg t "$TITLE" --arg d "$DESC" --argjson c "$COLOR" \
        '{embeds:[{title:$t, description:$d, color:$c, timestamp:(now | todate)}]}')" \
  "$WEBHOOK_URL" > /dev/null
```

Then any script can do:
```bash
/opt/mc-tools/webhook.sh "Backup complete" "Snapshot $SID — 12 MiB added in 24s" 5763719
```

### Step 2: Hook into existing scripts

Add `webhook.sh` calls to:
- `/opt/mc-tools/backup.sh` — on start, success, failure
- `/opt/mc-tools/restart-with-warning.sh` — at warning + restart
- `/opt/mc-tools/idle-monitor.py` — when triggering backup (use `requests` library to call Discord directly)

### Step 3: Log-tailer daemon (for player events)

Create `/opt/mc-tools/log-tailer.py` (systemd service):

- `tail -f` the server log: `/var/lib/pterodactyl/volumes/<your-server-uuid>/logs/latest.log`
- Match patterns:
  - `r" joined the game$"` → green webhook
  - `r" left the game$"` → grey/info webhook
  - `r"\[Server thread/(WARN|ERROR)\]"` for crashes → red webhook
  - Common death messages (Paper uses standard MC death message format)
- Handle log rotation: when file is replaced/truncated, reopen
- Throttle: don't spam if 10 join/leaves happen in 10s (rare but possible during server start)

Wrap in a systemd unit similar to `idle-monitor.service`.

## Rate limits

Discord webhooks: 30 messages / minute per webhook URL. For our scale this is never an issue, but the log-tailer should still throttle bursts.

## Testing

```bash
source /etc/mc-backup/webhook.env
curl -X POST -H "Content-Type: application/json" \
  -d '{"content":"Test from droplet"}' \
  "$WEBHOOK_URL"
```

Should appear in the configured Discord channel instantly.

## Optional: dashboard UI

If you want a web page to configure webhook URL + which events fire (instead of editing config files):

- Small Flask/FastAPI app
- One form: webhook URL field + checkboxes for each event category
- Saves to `/etc/mc-backup/webhook.json`
- Scripts read the JSON to decide whether to fire each event
- Auth: HTTP basic auth or behind Cloudflare Access
- Host at `webhooks.yourdomain.com` (new DNS record + Nginx vhost)

This is several hours of work and overkill for a single-user setup, but listed here in case future-you wants it.
