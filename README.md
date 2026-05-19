# minecraft server on digitalocean

self-hosted minecraft with a full [pterodactyl](https://pterodactyl.io) panel, encrypted world backups to google drive, discord notifications, and a hibernate/revive system that pauses the server when nobody's playing.

### docs → [shashwtd.github.io/DigitalOcean-Minecraft-Server](https://shashwtd.github.io/DigitalOcean-Minecraft-Server)

## what it does

- pterodactyl panel + wings on one droplet — web ui, console access, docker-isolated server
- [papermc](https://papermc.io) (or vanilla / fabric / forge) behind nginx with cloudflare dns
- encrypted world backups via [restic](https://restic.net) → google drive — daily, on idle, before every hibernate
- **hibernate/revive** — snapshot the droplet and destroy it when not playing, back in ~5 min when you are. drops cost from $24/mo to under $1
- discord notifications for joins, deaths, crashes, backup status
- idle detection — auto-backup after 30 min of zero players

## getting started

**with an ai assistant**

clone the repo, open it in [claude code](https://claude.ai/code), cursor, codex, or any ai coding assistant and say "help me set up my server". it'll ask what you need and handle the rest.

**manually**

follow the [setup guide](https://shashwtd.github.io/DigitalOcean-Minecraft-Server/setup/).

## cost

`s-2vcpu-4gb` droplet is **$0.036/hr** — you only pay for hours it exists.

| how you play | monthly |
|---|---|
| 24/7 | $24.00 |
| 2 weeks on, 2 off | ~$12.50 |
| 1 week on, 3 off | ~$6.50 |
| fully hibernated | ~$0.50 |

**student?** the [github student developer pack](https://education.github.com/pack) includes $200 in free digitalocean credit — enough to run the server for 8+ months.

## what you need

- digitalocean account + api token ([create one](https://cloud.digitalocean.com/account/api/tokens))
- domain on cloudflare + api token
- google account for drive backups
- python 3.10+, ssh key pair (see [.env.example](.env.example) for all required config)
- discord server (optional)

![Hackatime](https://hackatime.hackclub.com/api/v1/badge/U08RPK27GSF/DigitalOcean%20Minecraft%20Server)
