# Setting it up

Full setup from scratch. Takes 1–2 hours depending on how familiar you are with the pieces.

---

## What you need

**Accounts**

- **DigitalOcean** — personal access token with read + write scope
- **Cloudflare** — domain managed in Cloudflare; API token with Zone:DNS:Edit scoped to your zone
- **Google account** — Drive backup storage; free 15 GB tier is enough for most worlds
- **Discord server** (optional) — webhook URL for event notifications

**Local tools**

- Python 3.10 or later (no third-party packages; stdlib only)
- SSH key pair: one passphrase-free key for automation, one passphrase-protected for interactive use

**Droplet**

Tested on Ubuntu 22.04 LTS. A 4 GB / 2 vCPU / 80 GB SSD droplet runs Panel, Wings, and PaperMC comfortably for up to ~10 players. Smaller sizes are untested.

---

## 1. Provision the droplet

Create a 4 GB Ubuntu 22.04 droplet on DigitalOcean. Upload your automation SSH key during creation. Note the IP address.

---

## 2. Configure DNS

In Cloudflare, create two A records pointing to the droplet IP:

| Name | Proxy status | Purpose |
|---|---|---|
| `panel.yourdomain.com` | Proxied (orange) | Pterodactyl Panel |
| `play.yourdomain.com` | DNS only (grey) | Minecraft connections and Wings API |

The panel subdomain is proxied so Cloudflare handles TLS. The play subdomain must be DNS-only because Minecraft clients connect directly, and Wings needs a Let's Encrypt cert issued to the real IP.

---

## 3. Install Pterodactyl Panel

Follow the [official panel installation guide](https://pterodactyl.io/panel/1.0/getting_started.html). Use MariaDB and Redis as documented. Configure nginx with your panel domain.

For TLS on the panel, use a Cloudflare Origin Certificate (15-year validity, no renewal needed):

1. Cloudflare → your domain → SSL/TLS → Origin Server → Create Certificate
2. Save the certificate and key to the droplet
3. Set Cloudflare SSL/TLS mode to **Full** (not Full Strict)

---

## 4. Install Wings

Follow the [Wings installation guide](https://pterodactyl.io/wings/1.0/installing.html). Set the node FQDN to your play subdomain (e.g., `play.yourdomain.com`).

For Wings TLS, use Let's Encrypt (required since the play subdomain isn't Cloudflare-proxied):

```bash
apt install -y certbot
certbot certonly --standalone -d play.yourdomain.com
```

Add a certbot deploy hook so Wings restarts on renewal:

```bash
cat > /etc/letsencrypt/renewal-hooks/deploy/restart-wings.sh <<'EOF'
#!/bin/bash
systemctl restart wings
EOF
chmod +x /etc/letsencrypt/renewal-hooks/deploy/restart-wings.sh
```

---

## 5. Create the Minecraft server

Install a PaperMC egg from [Pterodactyl's eggs repository](https://github.com/pterodactyl/eggs) or create a server manually. Enable RCON in startup variables (required by the backup script).

To use a specific PaperMC build that the egg's installer doesn't include:

```bash
SERVER_DIR=/var/lib/pterodactyl/volumes/<your-server-uuid>
curl -L -o "$SERVER_DIR/server.jar" \
  "https://fill.papermc.io/v3/projects/paper/versions/<version>/builds/latest/download/type/application"
chown 988:988 "$SERVER_DIR/server.jar"
```

!!! warning
    Do not use the panel's "Reinstall" button after this — it re-runs the egg's install script and overwrites the jar.

---

## 6. Configure restic and rclone

Install the tools:

```bash
apt install -y restic
curl https://rclone.org/install.sh | bash
```

Create a Google Cloud OAuth 2.0 client for rclone:

1. [Google Cloud Console](https://console.cloud.google.com) → APIs & Services → Credentials → Create OAuth 2.0 Client ID, type Desktop
2. Enable the Google Drive API
3. Note the client ID and secret

Configure rclone with `drive.file` scope (rclone can only see files it created):

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

Write the credentials file the backup script reads:

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

---

## 7. Deploy the droplet scripts

```bash
scp droplet/scripts/* root@<IP>:/opt/mc-tools/
chmod +x /opt/mc-tools/*.sh /opt/mc-tools/*.py
```

Optionally configure Discord notifications:

```bash
echo 'WEBHOOK_URL=https://discord.com/api/webhooks/...' > /etc/mc-backup/webhook.env
chmod 600 /etc/mc-backup/webhook.env
```

If this file is absent, all webhook calls silently no-op.

---

## 8. Enable systemd services

```bash
cp droplet/services/idle-monitor.service droplet/services/log-tailer.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now idle-monitor log-tailer
```

Add a daily backup cron:

```bash
echo '0 6 * * * root /opt/mc-tools/backup.sh >> /var/log/mc-backup-cron.log 2>&1' \
  > /etc/cron.d/mc-backup
```

Add scheduled restart crons (optional — broadcasts a countdown in-game before restarting):

```bash
echo '55 4,10,16,22 * * * root /opt/mc-tools/restart-with-warning.sh >> /var/log/mc-restart-cron.log 2>&1' \
  >> /etc/cron.d/mc-backup
```

---

## 9. Configure the local .env

```bash
cp .env.example .env
# fill in your values
```

### Getting the tokens

**DigitalOcean API token**
Account → API → Tokens → Generate New Token. Read + Write scope. This token can create and destroy droplets on your entire account.

**Cloudflare API token**
Profile → API Tokens → Create Token → Edit zone DNS template. Scope it to your specific zone only.

**Pterodactyl client API key**
Panel → Account (top right) → API Credentials → Create API Key.

`SERVER_ADDR` and `PANEL_URL` drive the Cloudflare DNS update logic in `revive.py` — the script derives the domain and subdomains from these values, so no separate domain variable is needed.

---

## Verify it works

Run a manual backup to confirm the whole chain works:

```bash
ssh root@<droplet-ip> /opt/mc-tools/backup.sh
```

Then check snapshots:

```bash
ssh root@<droplet-ip> "source /etc/mc-backup/backup.env && \
  export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE && restic snapshots"
```

You should see at least one snapshot. If not, check `/var/log/mc-backup.log`.
