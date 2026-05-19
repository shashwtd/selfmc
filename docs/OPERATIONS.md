# Operations Guide

Common tasks for running the server.

## Connecting

```powershell
ssh -i ~/.ssh/do_minecraft_claude root@<droplet-ip>
```

`do_minecraft_claude` is the passphrase-free key. `id_ed25519` is the passphrase-protected one.

---

## Backups

### Manual backup
```bash
/opt/mc-tools/backup.sh
```

### List snapshots
```bash
source /etc/mc-backup/backup.env
export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE
restic snapshots
```

### Restore a snapshot
```bash
source /etc/mc-backup/backup.env
export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE

# 1. Stop the server first via panel (or API)

# 2. Restore to a staging directory
restic restore <snapshot-id> --target /tmp/restored

# 3. Replace world folders
SERVER_DIR=/var/lib/pterodactyl/volumes/<your-server-uuid>
rm -rf $SERVER_DIR/world $SERVER_DIR/world_nether $SERVER_DIR/world_the_end
cp -r /tmp/restored/var/lib/pterodactyl/volumes/.../world $SERVER_DIR/
chown -R 988:988 $SERVER_DIR/world*

# 4. Start the server
```

### Check backup logs
- `/var/log/mc-backup.log` — backup script output
- `/var/log/mc-backup-cron.log` — cron wrapper output
- `/var/log/mc-idle-monitor.log` — idle monitor decisions

---

## Server control

### Restart manually
Via panel button, or:
```bash
curl -X POST \
  -H "Authorization: Bearer $PTERO_KEY" \
  -H "Content-Type: application/json" \
  -d '{"signal":"restart"}' \
  https://panel.yourdomain.com/api/client/servers/<server-id>/power
```

### Send a command via API
```bash
curl -X POST \
  -H "Authorization: Bearer $PTERO_KEY" \
  -H "Content-Type: application/json" \
  -d '{"command":"say Hello"}' \
  https://panel.yourdomain.com/api/client/servers/<server-id>/command
```

### Whitelist
In server console:
```
/whitelist add <name>
/whitelist on
```

---

## Plugins

### Add a plugin
1. Find a Paper-compatible jar (modrinth.com, hangar.papermc.io)
2. SCP or download into `/var/lib/pterodactyl/volumes/<your-server-uuid>/plugins/`
3. `chown 988:988 <file>.jar` so Docker can read it
4. Restart the server

### Remove
Delete the jar from `plugins/` and restart.

---

## Updating Minecraft version

The egg uses an old Paper API and won't auto-find 26.x. Workflow:

1. Stop the server in panel
2. Find new jar URL from https://fill.papermc.io/v3/projects/paper/versions/<version>/builds/latest
3. SSH in:
   ```bash
   cd /var/lib/pterodactyl/volumes/<your-server-uuid>
   curl -L -o server.jar <new-jar-url>
   chown 988:988 server.jar
   ```
4. **Do NOT click "Reinstall"** — that re-runs the egg's install script and re-downloads the old API's version
5. Start the server
6. If new MC version needs newer Java: add the matching `ghcr.io/pterodactyl/yolks:java_NN` Docker image in admin → egg → Docker Images, then select it in server's Startup tab

---

## Backup retention / cleanup

Restic auto-prunes per its policy. To force a manual clean:
```bash
source /etc/mc-backup/backup.env
export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE
restic forget --keep-last 1 --keep-daily 30 --keep-weekly 12 --prune
```

To check repo integrity:
```bash
restic check
```

---

## SSL / certificate renewal

- **Panel SSL**: Cloudflare Origin Cert (15-year validity, no renewal needed) at `/etc/ssl/cloudflare/yourdomain.{crt,key}`
- **Wings SSL**: Let's Encrypt at `/etc/letsencrypt/live/play.yourdomain.com/`. Auto-renews via certbot's systemd timer. A deploy hook (`/etc/letsencrypt/renewal-hooks/deploy/restart-wings.sh`) restarts Wings after renewal.

To force-renew Let's Encrypt:
```bash
certbot renew --force-renewal
```

---

## Logs to check when things break

| Issue | Logs |
|---|---|
| Server won't start | Pterodactyl console, `/var/lib/pterodactyl/volumes/<uuid>/logs/latest.log` |
| Panel UI broken | `/var/log/nginx/pterodactyl.app-error.log`, `journalctl -u pteroq` |
| Console won't load | `journalctl -u wings -n 50` |
| Backup failed | `/var/log/mc-backup.log` |
| Idle monitor not firing | `/var/log/mc-idle-monitor.log`, `journalctl -u idle-monitor` |
| Restart script | `/var/log/mc-restart.log`, `/var/log/mc-restart-cron.log` |

---

## Common in-game admin commands

```
/op <player>            # grant admin
/deop <player>          # revoke admin
/whitelist add <name>
/whitelist on / off
/gamemode survival|creative|spectator <player>
/difficulty peaceful|easy|normal|hard
/worldborder set <radius>     # caps explorable area
/save-all                     # force flush to disk
/spark profiler --timeout 60  # 60s perf profile (Spark is disabled — re-enable in paper-global.yml first)
```

## Adding a Cloudflare Origin Cert (if regenerating)

1. Cloudflare → yourdomain.com → SSL/TLS → Origin Server → Create Certificate
2. Save cert + key to `/etc/ssl/cloudflare/yourdomain.crt` and `/etc/ssl/cloudflare/yourdomain.key`
3. **Strip BOM and convert CRLF** if pasted from Windows: `dos2unix /etc/ssl/cloudflare/*`
4. `chmod 600` on the key
5. `systemctl restart nginx`
