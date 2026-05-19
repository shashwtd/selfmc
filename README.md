# Minecraft Server — DigitalOcean + Pterodactyl

A self-hosted Minecraft server on DigitalOcean with full lifecycle automation: encrypted world backups to Google Drive, idle-triggered backup on empty server, Discord event notifications, and a hibernate/revive system that snapshots and destroys the droplet when nobody is playing — cutting the monthly cost from $24 to under $1.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Setup](#setup)
- [Configuration](#configuration)
- [Hibernate / Revive](#hibernate--revive)
- [Backup System](#backup-system)
- [Discord Notifications](#discord-notifications)
- [Automation Schedule](#automation-schedule)
- [File Reference](#file-reference)
- [Cost](#cost)
- [Security](#security)
- [Disaster Recovery](#disaster-recovery)

---

## Overview

This is a complete, production-tested reference implementation for running a small Minecraft server (1–10 players) on DigitalOcean at minimal cost. The key design goals:

**Cost efficiency.** The droplet exists only when you are actually playing. `hibernate.py` snaps the full disk to a DigitalOcean snapshot and destroys the droplet. `revive.py` recreates it from the snapshot, updates Cloudflare DNS to the new IP, and starts the server — all in roughly five minutes. You pay for compute by the hour you play, not by the month.

**Data durability.** World data is backed up independently of the droplet via restic to Google Drive. Even if a snapshot is lost or you cancel the droplet entirely, the world survives. Backups run daily, on idle (after 30 minutes of zero players), and before every hibernate.

**Minimal operational overhead.** The server restarts itself on a schedule, notifies Discord on notable events, and monitors its own idle state. Day-to-day it runs without intervention.

---

## Architecture

```
Your machine
┌────────────────────────────────────┐
│  hibernate.py / revive.py          │
│  (Python 3, runs locally)          │
└──────────┬──────────────┬──────────┘
           │ DO API        │ Cloudflare API
           ▼               ▼
┌──────────────────────────────────────────────────────┐
│  DigitalOcean Droplet  (Ubuntu 22.04, 4 GB / 2 vCPU) │
│                                                       │
│  nginx                                                │
│   └── Pterodactyl Panel (Laravel / PHP-FPM)           │
│         └── Pterodactyl Wings                         │
│               └── Docker container                    │
│                     └── PaperMC                       │
│                                                       │
│  idle-monitor.py  ──►  backup.sh  ──►  restic         │
│  log-tailer.py    ──►  webhook.sh ──►  Discord        │
└───────────────────────────────┬──────────────────────┘
                                │ rclone (OAuth)
                                ▼
                         Google Drive
                    (minecraft-backups/)
```

| Component | Role |
|---|---|
| Pterodactyl Panel | Web UI for server management, scheduled tasks, console access |
| Pterodactyl Wings | Host-side daemon that runs the MC server in a Docker container |
| PaperMC | High-performance Minecraft server; vanilla clients connect without modification |
| restic + rclone | Encrypted, deduplicated backup to Google Drive |
| idle-monitor.py | Systemd service; triggers a backup after 30 minutes with zero players |
| log-tailer.py | Systemd service; watches the Paper log and forwards events to Discord |
| webhook.sh | Reusable Discord webhook helper; always exits 0 so callers never fail on it |
| hibernate.py | Snapshots the droplet disk and destroys the droplet |
| revive.py | Recreates the droplet from snapshot and updates DNS |

Panel and Wings run on the same droplet. There is no separate database host, no load balancer, no container orchestration. This is intentional — the complexity budget for a personal server is low.

---

## Prerequisites

### Accounts

- **DigitalOcean** — create a personal access token with read + write scope
- **Cloudflare** — domain managed in Cloudflare; create an API token with Zone:DNS:Edit permission scoped to your zone
- **Google account** — for Drive backup storage; the free 15 GB tier is sufficient for most Minecraft worlds
- **Discord server** (optional) — create a webhook URL in your channel's Integration settings

### Local tools

- Python 3.10 or later (no third-party packages required; stdlib only)
- SSH key pair: one passphrase-free key for automation, one passphrase-protected key for interactive use

### Server

Tested on Ubuntu 22.04 LTS. A 4 GB / 2 vCPU / 80 GB SSD droplet comfortably runs Panel, Wings, and a PaperMC server for up to ~10 concurrent players with about 1 GB reserved for the OS and panel. Smaller sizes are untested.

---

## Setup

### 1. Provision the droplet

Create a 4 GB Ubuntu 22.04 droplet. Upload your automation SSH key during creation. Note the IP address.

### 2. Configure DNS

In Cloudflare, create two A records pointing to the droplet IP:

| Name | Proxy status | Purpose |
|---|---|---|
| `panel.yourdomain.com` | Proxied (orange) | Pterodactyl Panel |
| `play.yourdomain.com` | DNS only (grey) | Minecraft connections and Wings API |

The panel subdomain is proxied so Cloudflare handles TLS. The play subdomain must be DNS-only because Wings' certificate (Let's Encrypt) must be issued to the real IP, and Minecraft clients connect directly.

### 3. Install Pterodactyl Panel

Follow the [official Pterodactyl panel installation guide](https://pterodactyl.io/panel/1.0/getting_started.html). Use MariaDB and Redis as documented. Configure nginx with your panel domain.

For TLS on the panel, use a Cloudflare Origin Certificate (15-year validity, no renewal):
- Cloudflare → your domain → SSL/TLS → Origin Server → Create Certificate
- Save the certificate and key to the droplet
- Set Cloudflare SSL/TLS mode to **Full** (not Full Strict)

### 4. Install Wings

Follow the [Wings installation guide](https://pterodactyl.io/wings/1.0/installing.html). Set the node FQDN to your play subdomain (e.g., `play.yourdomain.com`).

For Wings TLS, use Let's Encrypt (required because the play subdomain is not Cloudflare-proxied):

```bash
apt install -y certbot
certbot certonly --standalone -d play.yourdomain.com
```

Configure Wings to use the Let's Encrypt certificate paths. Add a certbot deploy hook to restart Wings on renewal:

```bash
cat > /etc/letsencrypt/renewal-hooks/deploy/restart-wings.sh <<'EOF'
#!/bin/bash
systemctl restart wings
EOF
chmod +x /etc/letsencrypt/renewal-hooks/deploy/restart-wings.sh
```

### 5. Create the Minecraft server

Install a PaperMC egg from [Pterodactyl's eggs repository](https://github.com/pterodactyl/eggs) or create a server manually. Enable RCON in startup variables (required by the backup script for save-off/save-on).

To use a PaperMC build that the egg's installer does not include, download the jar directly:

```bash
SERVER_DIR=/var/lib/pterodactyl/volumes/<your-server-uuid>
curl -L -o "$SERVER_DIR/server.jar" \
  "https://fill.papermc.io/v3/projects/paper/versions/<version>/builds/latest/download/type/application"
chown 988:988 "$SERVER_DIR/server.jar"
```

Do not use the panel's "Reinstall" button after this — it re-runs the egg's install script and overwrites the jar.

### 6. Configure restic and rclone

Install the tools:

```bash
apt install -y restic
curl https://rclone.org/install.sh | bash
```

Create a Google Cloud OAuth 2.0 client for rclone (recommended over a service account):

1. [Google Cloud Console](https://console.cloud.google.com) → APIs & Services → Credentials → Create OAuth 2.0 Client ID, type Desktop
2. Enable the Google Drive API
3. Note the client ID and secret

Configure rclone with `drive.file` scope (rclone can only see files it created — limits blast radius if credentials leak):

```bash
rclone config
# type: drive
# scope: drive.file (option 3)
# client_id and client_secret: from step above
# follow the auth URL
```

Initialize the restic repository on Drive:

```bash
export RESTIC_REPOSITORY=rclone:gdrive:minecraft-backups
restic init
```

Write the credentials file consumed by the backup script:

```bash
mkdir -p /etc/mc-backup
cat > /etc/mc-backup/backup.env <<EOF
PTERO_URL=https://panel.yourdomain.com
PTERO_KEY=<pterodactyl-client-api-key>
SERVER_ID=<first-8-chars-of-server-uuid>
WORLD_DIR=/var/lib/pterodactyl/volumes/<full-server-uuid>
RESTIC_REPOSITORY=rclone:gdrive:minecraft-backups
RESTIC_PASSWORD_FILE=/root/.restic-password
EOF
chmod 600 /etc/mc-backup/backup.env
echo '<your-restic-password>' > /root/.restic-password
chmod 600 /root/.restic-password
```

### 7. Deploy the droplet scripts

Copy `backup.sh`, `idle-monitor.py`, `log-tailer.py`, `webhook.sh`, and `restart-with-warning.sh` to `/opt/mc-tools/`:

```bash
chmod +x /opt/mc-tools/*.sh /opt/mc-tools/*.py
```

Optionally configure Discord notifications:

```bash
echo 'WEBHOOK_URL=https://discord.com/api/webhooks/...' > /etc/mc-backup/webhook.env
chmod 600 /etc/mc-backup/webhook.env
```

If this file is absent, all webhook calls silently no-op.

### 8. Enable systemd services

```bash
cp idle-monitor.service log-tailer.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now idle-monitor log-tailer
```

Add a daily backup cron:

```bash
echo '0 6 * * * root /opt/mc-tools/backup.sh >> /var/log/mc-backup-cron.log 2>&1' \
  > /etc/cron.d/mc-backup
```

Add restart crons (optional — the restart script broadcasts a countdown in-game before restarting):

```bash
echo '55 4,10,16,22 * * * root /opt/mc-tools/restart-with-warning.sh >> /var/log/mc-restart-cron.log 2>&1' \
  >> /etc/cron.d/mc-backup
```

### 9. Configure the local .env

```bash
cp .env.example .env
# Edit .env with your values
```

See [Configuration](#configuration) for details on each variable.

---

## Configuration

All secrets and runtime configuration live in `.env`. Copy `.env.example` to `.env` and fill in every value.

The variables `SERVER_ADDR` and `PANEL_URL` drive the Cloudflare DNS update logic in `revive.py` — the script parses the domain and subdomains out of these values automatically, so no separate domain variable is needed.

### Generating the required tokens

**DigitalOcean API token**
Account → API → Tokens → Generate New Token. Read + Write scope. This token can create and destroy droplets on your entire account — treat it accordingly.

**Cloudflare API token**
Profile → API Tokens → Create Token → Edit zone DNS (use the template). Scope it to your specific zone only, not all zones.

**Pterodactyl client API key**
Panel → Account (top right) → API Credentials → Create API Key. This key can start/stop/restart servers and send console commands for the servers associated with your account.

---

## Hibernate / Revive

### What it does

**`hibernate.py`** — run when nobody will be playing for a while:

1. Checks for online players and sends an in-game notification, then kicks them
2. Stops the idle-monitor service to prevent lock conflicts during the shutdown sequence
3. Waits for any in-flight backup to release its lock
4. Runs a final restic backup with live-streamed output
5. Verifies the new snapshot landed on Drive (compares snapshot timestamp to backup start time)
6. Powers off the droplet via DO API
7. Creates a full-disk snapshot via DO API (typically 5–10 minutes depending on disk usage)
8. Destroys the droplet
9. Writes `hibernation-state.json` with the snapshot ID, region, and size

**`revive.py`** — run when you want to play again:

1. Reads `hibernation-state.json` for the snapshot ID
2. Creates a new droplet from the snapshot in the same region and with the same size
3. Polls until the droplet is active and has assigned a public IP
4. Updates Cloudflare DNS: panel subdomain (proxied) and game subdomain (DNS-only), both pointing to the new IP
5. Waits for SSH to become available on the new droplet
6. Writes the new IP to `/etc/hosts` on the droplet for the game subdomain — this bypasses the system DNS cache (TTL 5 min) so that PHP-FPM and pteroq resolve the Wings FQDN correctly the moment they restart, preventing the panel dashboard from hanging
7. Restarts PHP-FPM and pteroq
8. Updates Pterodactyl allocation IPs in the database to the new IP (Docker binds to the allocation IP; using the old IP causes the server container to fail at start)
9. Restarts Wings so it fetches an updated server configuration from the panel (which now has the correct allocation IP)
10. Waits for Wings to become active, then sends a server start signal via Pterodactyl API
11. Updates `DROPLET_IP` in the local `.env`
12. Deletes the hibernation snapshot (it is no longer needed once the droplet is running)
13. Removes `hibernation-state.json`

Total time: approximately 5 minutes.

### Usage

```bash
python hibernate.py
# ... hours or days later ...
python revive.py
```

### What is preserved

Everything on the droplet disk: Pterodactyl Panel state and database, Wings configuration, the Minecraft world, all plugins, cron jobs, SSL certificates, restic state, rclone OAuth tokens, and all scripts in `/opt/mc-tools/`. The revived droplet is byte-for-byte identical to the hibernated one, just with a new IP.

### What changes

The IP address is new on every revive. `revive.py` handles all downstream consequences automatically. If you SSH to the server by hostname after a revive, you will get a host key warning — clear the stale entry with `ssh-keygen -R play.yourdomain.com`.

### A note on the post-revive service restart sequence

Three things must happen in a specific order for the revived server to work correctly:

1. `/etc/hosts` must be updated with the new IP before services restart, or PHP-FPM may resolve the Wings hostname to the old IP from the DNS cache and the panel dashboard will hang.
2. PHP-FPM and pteroq must restart before Wings, so the panel is serving correct data.
3. Wings must restart after the allocation IP is updated in the database, so when it fetches the server configuration it gets the new IP and Docker can bind successfully.

If you ever need to manually recover from a broken revive, run these commands in order on the droplet:

```bash
# 1. Pin the correct IP
sed -i '/play.yourdomain.com/d' /etc/hosts && echo '<new-ip> play.yourdomain.com' >> /etc/hosts

# 2. Fix allocations in the database
php -r 'require "/var/www/pterodactyl/vendor/autoload.php";
$app = require "/var/www/pterodactyl/bootstrap/app.php";
$app->make("Illuminate\Contracts\Console\Kernel")->bootstrap();
foreach (\Pterodactyl\Models\Allocation::all() as $a) { $a->ip = "<new-ip>"; $a->save(); }'

# 3. Restart services in order
systemctl restart php8.3-fpm pteroq
sleep 8
systemctl restart wings
```

---

## Backup System

### How it works

`backup.sh` runs as a standalone script that can be triggered by any caller. It:

1. Acquires an exclusive lock (`/tmp/mc-backup.lock`) — concurrent runs are silently skipped
2. Clears any stale restic lock left by a previously interrupted backup
3. If the server is running: sends `save-off` and `save-all flush` via Pterodactyl API, waits 5 seconds for async writes to settle
4. Runs `restic backup` on the world directories
5. Re-enables world saves if they were paused
6. Prunes old snapshots according to the retention policy
7. Sends a Discord notification with the amount added and time taken

### Trigger conditions

| Trigger | When |
|---|---|
| Idle monitor | After 30 consecutive minutes with zero players (2-hour cooldown between idle backups) |
| Daily cron | 06:00 (configure to your preferred time) |
| Pre-hibernate | Every time `hibernate.py` runs, before the snapshot |
| Manual | `ssh root@<ip> /opt/mc-tools/backup.sh` |

### Retention policy

```
--keep-last 1 --keep-daily 30 --keep-weekly 12
```

One most-recent snapshot is always kept regardless of age. Up to 30 daily and 12 weekly snapshots are kept on Google Drive. restic's deduplication means this is far cheaper in storage than it sounds — only changed chunks are uploaded on each run.

### Idle detection

`idle-monitor.py` runs as a systemd service. Every 5 minutes it replays the current `latest.log` from the beginning, counting net join/leave events since the last server start line. If the resulting count has been zero for 30 consecutive minutes, it runs `backup.sh`. A 2-hour cooldown prevents multiple idle backups in a session where players repeatedly join and leave.

The log-replay approach is intentional: it requires no RCON, no plugins, and no Pterodactyl API calls. It works as long as the log file is readable on the host, which is always the case since Wings mounts the server volume directly.

---

## Discord Notifications

`log-tailer.py` tails `latest.log` inside the server volume and sends webhook messages for notable events.

| Event | Message type |
|---|---|
| Player join / leave | Plain text |
| Server start (with startup time) | Plain text |
| Server stop | Plain text |
| Player death | Plain text |
| Server error / crash | Embed with log excerpt |

`backup.sh` sends a success embed on completion (with bytes added and duration) and an error embed on failure.

All webhook calls go through `webhook.sh`, which exits 0 unconditionally. A missing `webhook.env`, an unreachable Discord endpoint, or a malformed payload will not interrupt any calling script.

To configure, write the webhook URL to `/etc/mc-backup/webhook.env` on the droplet:

```
WEBHOOK_URL=https://discord.com/api/webhooks/<id>/<token>
```

---

## Automation Schedule

| Time | Action |
|---|---|
| 06:00 daily | Restic backup via cron |
| 04:55, 10:55, 16:55, 22:55 | Restart-with-warning: in-game countdown, then API restart |
| Continuous | Idle monitor polls every 5 minutes |
| On hibernate | Final backup before snapshot |

Adjust times to your timezone in `/etc/cron.d/mc-backup`.

---

## File Reference

### Local (your machine)

| File | Purpose |
|---|---|
| `hibernate.py` | Snapshot and destroy the droplet |
| `revive.py` | Recreate from snapshot, update DNS, fix post-revive state |
| `_common.py` | Shared helpers: env loading, HTTP, SSH |
| `.env` | All secrets and runtime config (gitignored) |
| `.env.example` | Template for `.env` |
| `hibernation-state.json` | Written by hibernate.py, consumed by revive.py (gitignored) |

### Droplet (`/opt/mc-tools/`)

| File | Purpose |
|---|---|
| `backup.sh` | Main backup script |
| `idle-monitor.py` | Idle detection and backup trigger |
| `log-tailer.py` | Server log to Discord forwarder |
| `webhook.sh` | Discord webhook helper |
| `restart-with-warning.sh` | Broadcasts countdown, then restarts server via API |
| `idle-monitor.service` | Systemd unit for idle-monitor.py |
| `log-tailer.service` | Systemd unit for log-tailer.py |

### Droplet config (reference copies)

| File | Deployed to |
|---|---|
| `pterodactyl.conf` | `/etc/nginx/sites-available/pterodactyl.conf` |
| `wings-config.yml` | `/etc/pterodactyl/config.yml` |
| `backup.env` | `/etc/mc-backup/backup.env` (populate from template; do not commit) |

---

## Cost

DigitalOcean bills hourly, capped at the monthly rate. A `s-2vcpu-4gb` droplet is $24/month ($0.036/hour). Snapshots are $0.06/GB/month. A typical snapshot of this setup is 5–10 GB.

| State | Monthly cost |
|---|---|
| Running continuously | $24.00 |
| Playing 2 weeks, hibernated 2 weeks | ~$12.50 |
| Playing 1 week, hibernated 3 weeks | ~$6.50 |
| Fully hibernated | ~$0.50 |

The crossover point is roughly one day of activity per month. Below that, hibernating is cheaper. Above that, it may not be worth the friction. The 5-minute revive time is the main cost of hibernation.

---

## Security

**What to protect:**

- `.env` — contains API tokens that can destroy droplets and modify DNS. It is gitignored. Do not sync this directory to cloud storage.
- `SSH_KEY_AUTOMATION` — passphrase-free by design (used by scripts). Keep it off shared machines.
- Restic password — the only thing protecting your world data on Drive from someone who gains access to your Google account. Store it in a password manager.

**Token scopes:**

- DO API token: ideally scoped to droplet read/write only. The default "full access" token also includes database clusters, Spaces, etc. — consider creating a scoped token if your DigitalOcean account holds other resources.
- Cloudflare API token: use the "Edit zone DNS" template scoped to your specific zone. This limits the damage if the token is leaked to DNS changes for one domain only.
- Pterodactyl client API key: can start/stop/restart servers and run console commands for your account's servers. Re-issuable from the panel at any time.
- Google OAuth credentials: `drive.file` scope means rclone can only see files it created. Even full Drive access to the OAuth token would only expose the `minecraft-backups/` folder contents, which are restic-encrypted.

**`hibernation-state.json`:** contains a snapshot ID. If leaked, someone with your DO token could use it to create a droplet from your snapshot. It is gitignored and deleted by `revive.py` after use.

---

## Disaster Recovery

If the droplet is destroyed and no DigitalOcean snapshot exists, the world can be recovered from Google Drive using:

1. The restic repository password
2. The Google OAuth client ID and secret
3. Access to the Google account

These three items are sufficient to restore all world data to any machine. Keep them in a password manager.

```bash
# On any Linux machine with internet access
apt install -y restic && curl https://rclone.org/install.sh | bash

rclone config  # configure gdrive remote with your client_id and client_secret

export RESTIC_REPOSITORY=rclone:gdrive:minecraft-backups
export RESTIC_PASSWORD=<your-restic-password>

restic snapshots          # verify access
restic restore latest --target /tmp/restored
```

The world directories will be at `/tmp/restored/var/lib/pterodactyl/volumes/<uuid>/world*`. From there you can drop them into any Minecraft server setup, with or without Pterodactyl.

See `RECOVERY.md` for the full procedure including how to rebuild the Pterodactyl stack.
