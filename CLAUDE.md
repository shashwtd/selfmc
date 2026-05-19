# Agent Setup Guide

This repo sets up a self-hosted Minecraft server on DigitalOcean with automated backups, Discord notifications, and a hibernate/revive system. When someone opens this repo and asks you to set up their server, **do not start running commands yet**. Ask all the questions below first, then proceed based on their answers.

---

## Step 1 — Ask these questions before doing anything

Ask them all up front in one message so the user can answer everything at once.

### Server
1. **Minecraft version?** (e.g. 1.21.4, latest stable, specific version)
2. **Server type?** Paper (recommended — best performance, supports plugins), Vanilla (pure Mojang, no plugins), Fabric (lightweight mods), or Forge (heavy modpacks — needs more RAM)
3. **Approximate player count?** (determines droplet size — 1–5 players, 5–10, or 10+)

### Infrastructure
4. **Do you have a domain name?** If yes, is it on Cloudflare? (Required for automatic DNS updates on hibernate/revive. If no domain, the server will work fine but you'll connect by IP and hibernate/revive won't auto-update DNS.)
5. **DigitalOcean account ready?** Do they have an API token with read+write scope? (Remind them: GitHub Student Developer Pack includes $200 free DO credit at education.github.com/pack if they have a .edu email)

### Features — ask each one
6. **Backups?** Restic backups to Google Drive — encrypted, deduplicated, runs daily + on idle + before hibernate. Requires a Google account and a one-time OAuth setup. Do they want this? (Strongly recommended — it's the only copy of the world if the droplet is lost)
7. **Hibernate/revive?** Destroys the droplet when not playing, revives it in ~5 min when needed. Cuts monthly cost from $24 to under $1 when hibernated. Do they want this? (Requires a domain on Cloudflare for automatic DNS updates)
8. **Discord notifications?** Player join/leave, server start/stop, death messages, backup status. Do they have a Discord server they want notifications in?
9. **Scheduled restarts?** Automatic server restarts every 6 hours with an in-game countdown warning. Do they want this?

---

## Step 2 — Confirm the plan before proceeding

Summarize what you're going to set up based on their answers. For example:

> "Here's what I'll set up: PaperMC 1.21.4, 4 GB droplet, domain play.yourdomain.com on Cloudflare, backups to Google Drive, hibernate/revive enabled, Discord notifications to your #mc-server channel, no scheduled restarts. Sound right?"

Wait for confirmation before running any commands.

---

## Step 3 — Follow the setup guide

The full step-by-step setup is in `docs/setup.md`. Follow it in order, skipping steps for features the user opted out of:

- No backups → skip step 6 (restic/rclone), skip `backup.sh` deploy and cron, skip idle-monitor
- No hibernate/revive → skip the `.env` variables `DO_API_TOKEN`, `CF_API_TOKEN`, `SERVER_ADDR`, `PANEL_URL`; `hibernate.py` and `revive.py` won't work without them
- No Discord → skip `webhook.env` creation; all webhook calls no-op safely without it
- No scheduled restarts → skip the restart cron line in step 8

For anything not covered in the docs, the scripts themselves are well-commented — read them.

---

## Key files to know

| File | What it does |
|---|---|
| `hibernate.py` | Snapshots and destroys the droplet |
| `revive.py` | Recreates droplet from snapshot, fixes DNS and service state |
| `_common.py` | Shared SSH/HTTP helpers used by both scripts |
| `droplet/scripts/backup.sh` | Restic backup orchestrator |
| `droplet/scripts/idle-monitor.py` | Triggers backup after 30 min of zero players |
| `droplet/scripts/log-tailer.py` | Forwards server log events to Discord |
| `.env.example` | Template for all required secrets and config |

---

## Things that will trip you up

- **Post-revive service restart order matters.** After `revive.py` creates a new droplet, services must restart in a specific order or the panel dashboard hangs and the game server fails to bind. `revive.py` handles this automatically — do not restart services manually unless following the recovery steps in `docs/HIBERNATE.md`.
- **rclone OAuth must be done interactively.** `rclone config` requires a browser. Run it once on the droplet via SSH. Everything after that is headless.
- **The passphrase-free SSH key** (`SSH_KEY_AUTOMATION` in `.env`) is required for `hibernate.py` and `revive.py` to work without prompting. Create a separate key for automation; keep your personal key passphrase-protected.
- **Cloudflare SSL mode must be Full, not Full Strict.** The panel uses a Cloudflare Origin Certificate. Full Strict breaks it.
