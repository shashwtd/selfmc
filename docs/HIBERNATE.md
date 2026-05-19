# Hibernate / Revive

Cost-saving workflow for when no one's playing.

## What it does

**`hibernate.py`**
1. Runs a final restic backup (so even if the snapshot ever fails, world is safe on Drive)
2. Powers off the droplet via DigitalOcean API
3. Creates a full disk snapshot
4. Deletes the droplet
5. Saves snapshot ID locally to `hibernation-state.json`

**`revive.py`**
1. Reads `hibernation-state.json` for snapshot ID
2. Creates a new droplet from the snapshot (same region, same size)
3. Polls until it's active and gets the new IP
4. Updates Cloudflare DNS records (`panel.yourdomain.com` + `play.yourdomain.com`) to the new IP
5. Waits for SSH
6. Updates `.env` `DROPLET_IP` to the new IP
7. Deletes the snapshot (no point paying for it once revived)
8. Removes `hibernation-state.json`

Total revive time: ~5 minutes.

## When to use

- Friends not playing for several days / weeks
- Going on vacation
- Just exploring whether to keep the server long-term

You do NOT need to hibernate for one-off quiet evenings — the idle monitor already handles "nobody's online right now" via auto-backups, and the droplet itself idles at near-zero CPU.

## Usage

```powershell
python hibernate.py     # ~3-5 min to snapshot + destroy
# ... time passes, friends ping you ...
python revive.py        # ~5 min to recreate + DNS update
```

## What's preserved across hibernation

Everything on the droplet disk:
- Pterodactyl panel + DB + user accounts
- Wings + server config
- The Minecraft world
- All plugins
- All scripts in `/opt/mc-tools/`
- All scheduled crons
- SSL certs (Cloudflare origin + Let's Encrypt)
- restic state, rclone OAuth tokens, etc.

When you revive, the new droplet boots and everything runs exactly as before — just with a new IP.

## What changes

- **IP address** is new every revive. `.env` auto-updates with the new IP. DNS auto-updates (Cloudflare records pointed to new IP).
- **Let's Encrypt cert**: still valid (cert is for `play.yourdomain.com` which now points to the new IP). Will auto-renew normally.
- **SSH known_hosts**: the new droplet has a fresh host key. If you SSH by hostname, you'll get a warning until you clear the old cached entry.

## Connecting via SSH after revive

The new droplet has a different SSH host key than the old one. Two cases:

**If you SSH to the new IP** (e.g. `ssh root@168.x.x.x`):
- No warning — new IP isn't in your `known_hosts` yet
- Just connect normally:
  ```bash
  ssh -i ~/.ssh/do_minecraft_claude root@<new-ip>
  ```

**If you SSH by hostname** (e.g. `ssh root@play.yourdomain.com`):
- You'll get `WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!`
- Clear the stale entry once:
  ```powershell
  ssh-keygen -R play.yourdomain.com
  ```
- Then SSH works normally.

The new IP is printed at the end of `revive.py`, and is also saved to `.env` as `DROPLET_IP`.

## Billing math

DigitalOcean bills **hourly**, capped at the monthly rate. A $24/mo droplet is $0.0357/hr.

### Your specific question: created droplet yesterday, hibernate after 3 more days

So 4 total days of droplet runtime:
- 4 days × 24h × $0.0357 = **~$3.43** for droplet usage
- Plus snapshot storage from day 4 onward: ~10 GB × $0.06/GB/month = **~$0.60/month**
- If you stay hibernated for the remaining ~26 days of the billing month: **~$0.52** snapshot cost

**Total for the month: ~$3.95** instead of $24. **You save ~$20.**

The longer you stay hibernated, the more you save. Snapshot is ~$0.60/month forever; running droplet is $24/mo.

### Break-even

If you'd play 2-3 days per month, hibernate the rest:
- Active days × $0.86/day + snapshot $0.60 = a few bucks total
- vs $24 always-on

### Reserved IP (optional, if you hate updating DNS)

DigitalOcean lets you reserve an IP for $4/mo. Attach it to whatever droplet is currently running. Revives no longer need DNS updates. Skip this unless DNS friction bugs you.

## Troubleshooting

**Hibernate failed mid-way (snapshot exists but droplet still there)**
- Check DO control panel
- If snapshot is good, manually destroy droplet, then manually write `hibernation-state.json` with the snapshot ID
- Run revive normally

**Revive failed (new droplet up but DNS update broke)**
- Check Cloudflare manually — update DNS records to the IP shown in the script output
- Edit `.env` DROPLET_IP yourself

**Friends say game is laggy after revive**
- DNS TTL is 5 min after revive; first few minutes some clients may still cache old IP
- Have them flush DNS or restart their MC client

## Security note

Both API tokens have meaningful power:
- `DO_API_TOKEN` can destroy any droplet on your DO account
- `CF_API_TOKEN` can edit DNS for yourdomain.com (scoped to just that zone)

Both are in `.env`. Don't sync this folder. If a token leaks, revoke it from DO/Cloudflare and generate a new one.
