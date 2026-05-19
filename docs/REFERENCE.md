# Reference

Paths, ports, and config locations on the droplet.

## Server UUID / identifiers

| | Value |
|---|---|
| Full server UUID | `<your-server-uuid>` |
| Short identifier (used by API) | `<server-id>` |
| Node ID | `node1` |

## Network / ports

| Port | Service | Notes |
|---|---|---|
| 22 | SSH | Key-only, no password auth |
| 80 | Nginx HTTP | Redirects to 443 |
| 443 | Nginx HTTPS | Panel UI (uses CF Origin Cert) |
| 2022 | Pterodactyl SFTP | For file access to server volume |
| 8080 | Wings daemon | HTTPS with Let's Encrypt cert |
| 25565 | Minecraft | Player connections |

Firewall (ufw): only the above are open.

## Key file locations

### Panel
- App root: `/var/www/pterodactyl/`
- Env / DB creds: `/var/www/pterodactyl/.env`
- Nginx config: `/etc/nginx/sites-available/pterodactyl.conf`
- Cloudflare cert: `/etc/ssl/cloudflare/yourdomain.crt` + `yourdomain.key`

### Wings
- Binary: `/usr/local/bin/wings`
- Config: `/etc/pterodactyl/config.yml`
- Server volumes: `/var/lib/pterodactyl/volumes/<server-uuid>/`
- Let's Encrypt cert: `/etc/letsencrypt/live/play.yourdomain.com/`
- Renew hook: `/etc/letsencrypt/renewal-hooks/deploy/restart-wings.sh`

### Backups / automation
- Scripts: `/opt/mc-tools/`
  - `backup.sh` — restic backup orchestrator
  - `idle-monitor.py` — idle player detection
  - `restart-with-warning.sh` — scheduled restart with countdown
- Config: `/etc/mc-backup/backup.env` (PTERO_KEY, server ID, paths)
- Restic password: `/root/.restic-password`
- Rclone config: `/root/.config/rclone/rclone.conf`
- Logs:
  - `/var/log/mc-backup.log`
  - `/var/log/mc-backup-cron.log`
  - `/var/log/mc-idle-monitor.log`
  - `/var/log/mc-restart.log`

### systemd services
- `wings.service` — Pterodactyl daemon
- `pteroq.service` — Panel queue worker
- `idle-monitor.service` — Idle backup trigger
- `nginx.service` — Web server
- `mariadb.service` — Database
- `redis-server.service` — Cache/session/queue store
- `docker.service` — Container runtime

## Pterodactyl egg / Java images

- Egg: Paper (under Minecraft nest)
- Active Docker image: `ghcr.io/pterodactyl/yolks:java_25`
- Other useful images you can switch to (admin → egg → Docker Images):
  - `ghcr.io/pterodactyl/yolks:java_21` — for older MC versions

## Restic repo

| | Value |
|---|---|
| Backend | `rclone:gdrive:minecraft-backups` |
| Password file | `/root/.restic-password` |
| Pack size | 128 MB (env: `RESTIC_PACK_SIZE`) |
| Retention | keep-last 1, keep-daily 30, keep-weekly 12 |

## rclone config

| | Value |
|---|---|
| Remote name | `gdrive` |
| Backend | `drive` |
| Scope | `drive.file` (only files rclone creates) |
| OAuth client | Personal Google Cloud project (not shared default) |

## Pterodactyl URLs

- User dashboard: https://panel.yourdomain.com
- Admin panel: https://panel.yourdomain.com/admin
- API base (Client): https://panel.yourdomain.com/api/client
- API base (Application, requires app key): https://panel.yourdomain.com/api/application

## Container internals

Pterodactyl runs MC in a Docker container as **UID/GID 988**. When you SCP files into the server volume from the host, `chown 988:988 <file>` so the container can read/write them.

## Player connection

```
Server address: play.yourdomain.com
Port: 25565 (default, no need to specify)
Version: 26.1.2
Online-mode: disabled
```
