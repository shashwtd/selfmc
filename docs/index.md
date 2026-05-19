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

The recommended droplet (`s-2vcpu-4gb`) is **$0.036/hour** — you only pay for hours the droplet exists. Snapshots (while hibernated) cost $0.06/GB/month, typically $0.30–$0.60/month total.

| How you play | Monthly cost |
|---|---|
| Running 24/7 | $24.00 |
| 2 weeks on, 2 weeks off | ~$12.50 |
| 1 week on, 3 weeks off | ~$6.50 |
| Fully hibernated | ~$0.50 |

The 5-minute revive time is the only cost of hibernating.

### vs. managed Minecraft hosting

Managed hosting looks cheaper at first glance — but they charge the same whether you play or not. With hibernate, you only pay for hours the server is actually running.

All prices for a 4 GB RAM plan, May 2026.

| Provider | 4 GB/month | Auto backups | Player slots | Full mod/plugin control |
|---|---|---|---|---|
| PebbleHost | $4.00 | Extra cost | Unlimited | Yes |
| ScalaCube | $4.99 | Manual only | Unlimited | Yes |
| Bisect Hosting | $8.00 | 7 days (4 slots) | Unlimited | Yes |
| Shockbyte | ~$10.50 | Included | 80 slots | Yes |
| Apex Hosting | $14.99 | Daily | Unlimited | Yes |
| **This repo (DO)** | **$0.50–$24** | **Encrypted, to your Drive** | **Unlimited** | **Full root access** |

The managed hosts win if you want zero maintenance and play every day. Self-hosting wins when you play occasionally — hibernating to $0.50/month while you're away, and keeping your world data encrypted under your own Google account with no player slot caps and no shared infrastructure.

---

## Are you a student?

!!! tip "GitHub Education gives you $200 in free DigitalOcean credit"
    If you have a `.edu` email or a school-verified GitHub account, you qualify for the [GitHub Student Developer Pack](https://education.github.com/pack). It includes **$200 in DigitalOcean credit** — enough to run the recommended 4 GB droplet for over 8 months, or play freely without worrying about the bill.

    1. Apply at [education.github.com/pack](https://education.github.com/pack) (takes 1–3 days to approve)
    2. Redeem the DigitalOcean offer from your pack dashboard
    3. Come back here and follow the setup guide

    The 4 GB droplet is the right choice for a student server — comfortable headroom for 1–10 players without needing to think about memory pressure.

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
