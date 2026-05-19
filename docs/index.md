# Minecraft Server on DigitalOcean

Self-hosted Minecraft on a DigitalOcean droplet. Automated world backups to Google Drive, idle detection, Discord notifications, and a hibernate/revive system that destroys the droplet when nobody's playing — dropping the monthly cost from $24 to under $1.

---

## How it's built

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

Panel and Wings run on the same droplet. No separate database host, no load balancer — the complexity budget for a personal server is low.

---

## What it actually costs

DigitalOcean bills hourly, capped at the monthly rate. A `s-2vcpu-4gb` droplet is $24/month ($0.036/hour). Snapshots are $0.06/GB/month.

| State | Monthly cost |
|---|---|
| Running continuously | $24.00 |
| Playing 2 weeks, hibernated 2 weeks | ~$12.50 |
| Playing 1 week, hibernated 3 weeks | ~$6.50 |
| Fully hibernated | ~$0.50 |

The 5-minute revive time is the main cost of hibernation.

---

## What's in this repo

| File | Purpose |
|---|---|
| `hibernate.py` | Snapshot and destroy the droplet |
| `revive.py` | Recreate from snapshot, update DNS, fix post-revive state |
| `_common.py` | Shared helpers: env loading, HTTP, SSH |
| `.env` | All secrets and runtime config (gitignored) |
| `.env.example` | Template for `.env` |
| `droplet/scripts/` | Scripts deployed to `/opt/mc-tools/` on the droplet |
| `droplet/services/` | Systemd units for idle monitor and log tailer |
| `droplet/config/` | Reference config files for nginx, Wings, backup env |

---

## Where to start

**Easiest path:** Clone this repo and open it in [Claude Code](https://claude.ai/code), Cursor, or any AI coding assistant. Ask it to set up the server for you — it can read the scripts, run commands, and guide you through every step interactively. No manual reading required.

**Manual path:** Follow [Setting it up](setup.md) step by step.

Already running and just need something specific? Use the nav on the left.
