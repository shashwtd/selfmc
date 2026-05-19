# Disaster Recovery

If you destroy / cancel the droplet, you can restore the world to a new server using only:

1. The **restic repo password** (1 string)
2. The **Google OAuth client_id + secret** (2 strings)
3. Access to the Google account where backups live

These are tiny, fit in a password manager, and are the only critical secrets.

---

## Step 0: Back these up to a password manager NOW

| Item | Where it lives on droplet | Why you need it |
|---|---|---|
| Restic password | `/root/.restic-password` | Decrypts the snapshot repo on Drive |
| Google OAuth client ID | `/root/.config/rclone/rclone.conf` (`client_id` line) | rclone's identity for Drive API |
| Google OAuth client secret | `/root/.config/rclone/rclone.conf` (`client_secret` line) | Same |

Grab them once:
```bash
ssh -i $env:USERPROFILE\.ssh\do_minecraft_claude root@<droplet-ip> \
  "cat /root/.restic-password; echo; grep -E 'client_id|client_secret' /root/.config/rclone/rclone.conf"
```
→ paste into Bitwarden / 1Password / iCloud Keychain / your password manager of choice. **DO NOT** commit them to git or any sync'd folder.

You do *not* need to back up the rclone OAuth token — it's short-lived and re-auth gives you a new one.

---

## Step 1: Restore on a new machine (any Linux box with internet)

Install restic + rclone:
```bash
apt install -y restic
curl https://rclone.org/install.sh | bash
```

Configure rclone with your OAuth client:
```bash
rclone config
# n (new), name = gdrive, type = drive,
# paste client_id, paste client_secret, scope = 3 (drive.file),
# advanced = no, autoconfig = no
# copy the rclone authorize line, run it on a machine with a browser
# (https://rclone.org/drive/#headless), paste the token back
```

Set environment for restic:
```bash
export RESTIC_REPOSITORY=rclone:gdrive:minecraft-backups
echo '<your-restic-password>' > /tmp/pw && chmod 600 /tmp/pw
export RESTIC_PASSWORD_FILE=/tmp/pw
```

Confirm you can see snapshots:
```bash
restic snapshots
```

Restore the latest snapshot:
```bash
restic restore latest --target /tmp/restored
```

You now have the world folders under `/tmp/restored/var/lib/pterodactyl/volumes/.../world/`.

---

## Step 2: Bring it back online

You have the world. Now you need a server to run it. Two options:

**Option A — Rebuild the same setup on a new droplet**
Follow `README.md` + `OPERATIONS.md` to provision a new droplet and reinstall Pterodactyl. After creating an empty server, drop the restored `world/`, `world_nether/`, `world_the_end/` folders into the server volume (replace any defaults). `chown -R 988:988` so Docker can read them.

**Option B — Run vanilla / Paper directly without Pterodactyl**
Download Paper 26.1.2 jar, unzip the restored world into the same directory as the jar, accept the EULA, run:
```bash
java -Xms2G -Xmx2G -jar paper-26.1.2-64.jar nogui
```
Skips the entire panel — useful if you just want to play locally / on a temporary VM.

---

## What this means for "what if I cancel the droplet"

- **World data: safe** as long as Drive has at least one snapshot
- **Pterodactyl panel state** (users, scheduled tasks, the egg config): not backed up, but easy to rebuild
- **The scripts in this repo** are your blueprint for redeploying — they're saved here, not on Drive
- **DNS / domain / Cloudflare**: untouched (those are at the registrar level)

So canceling the droplet costs you about an hour of setup work, but no data.

---

## Sanity check: when did backups last run?

```bash
ssh -i $env:USERPROFILE\.ssh\do_minecraft_claude root@<droplet-ip> \
  "source /etc/mc-backup/backup.env && export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE && restic snapshots --latest 5"
```

If you haven't seen a snapshot in >24 hours, something's broken — check `/var/log/mc-backup.log` and `/var/log/mc-idle-monitor.log`.
