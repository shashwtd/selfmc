#!/usr/bin/env python3
"""
Creates a new droplet from the hibernation snapshot and points DNS at it.
Run after `hibernate.py` when you want to play again. ~5 min total.

Requires DO_API_TOKEN, CF_API_TOKEN in .env, plus hibernation-state.json
written by hibernate.py.
"""
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from _common import ROOT, load_env, require, http, ssh, log


def main():
    load_env()
    require("DO_API_TOKEN", "CF_API_TOKEN", "SSH_KEY_AUTOMATION", "PANEL_URL", "SERVER_ADDR")

    # Derive domain and subdomains from existing env vars so nothing is hardcoded.
    # SERVER_ADDR=play.yourdomain.com  → mc_sub=play, cf_domain=yourdomain.com
    # PANEL_URL=https://panel.yourdomain.com → panel_sub=panel
    server_addr = os.environ["SERVER_ADDR"]          # e.g. play.yourdomain.com
    mc_sub, cf_domain = server_addr.split(".", 1)    # play, yourdomain.com
    panel_host = urlparse(os.environ["PANEL_URL"]).hostname  # panel.yourdomain.com
    panel_sub = panel_host.split(".")[0]             # panel
    state_file = ROOT / "hibernation-state.json"
    if not state_file.exists():
        sys.exit("No hibernation-state.json - droplet isn't hibernated")

    state = json.loads(state_file.read_text(encoding="utf-8"))
    log(f"Reviving from snapshot {state['snapshot_name']} (created {state['hibernated_at']})")

    do = {"Authorization": f"Bearer {os.environ['DO_API_TOKEN']}"}
    cf = {"Authorization": f"Bearer {os.environ['CF_API_TOKEN']}"}

    # 1. Get all SSH keys on the DO account so the new droplet is reachable
    keys = http("GET", "https://api.digitalocean.com/v2/account/keys", headers=do)["ssh_keys"]
    key_ids = [k["id"] for k in keys]

    # 2. Create droplet from snapshot
    droplet_name = f"mc-revived-{int(time.time())}"
    body = {
        "name":       droplet_name,
        "region":     state["region"],
        "size":       state["size"],
        "image":      state["snapshot_id"],
        "ssh_keys":   key_ids,
        "backups":    False,
        "ipv6":       False,
        "monitoring": True,
        "tags":       ["minecraft", "revived"],
    }
    log(f"Creating new droplet (region {state['region']}, size {state['size']})...")
    create = http("POST", "https://api.digitalocean.com/v2/droplets", headers=do, body=body)
    droplet_id = create["droplet"]["id"]

    # 3. Poll until active + has IP
    log("Waiting for droplet to become active...")
    ip = None
    while not ip:
        time.sleep(6)
        d = http("GET", f"https://api.digitalocean.com/v2/droplets/{droplet_id}", headers=do)["droplet"]
        log(f"  status={d['status']}")
        if d["status"] == "active":
            ip = next(n["ip_address"] for n in d["networks"]["v4"] if n["type"] == "public")
    log(f"  new IP: {ip}")

    # 4. Update Cloudflare DNS records
    zones = http("GET", f"https://api.cloudflare.com/client/v4/zones?name={cf_domain}", headers=cf)["result"]
    if not zones:
        sys.exit(f"Cannot find {cf_domain} zone in Cloudflare")
    zone_id = zones[0]["id"]

    def update_cf(sub, proxied):
        fqdn = f"{sub}.{cf_domain}"
        recs = http(
            "GET",
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records?name={fqdn}&type=A",
            headers=cf,
        )["result"]
        if not recs:
            sys.exit(f"Cannot find {fqdn} DNS record")
        rec = recs[0]
        http(
            "PUT",
            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/{rec['id']}",
            headers=cf,
            body={"type": "A", "name": fqdn, "content": ip, "ttl": 300, "proxied": proxied},
        )
        log(f"  {fqdn} -> {ip} (proxied={proxied})")

    log("Updating Cloudflare DNS...")
    update_cf(panel_sub, True)
    update_cf(mc_sub, False)

    # 5. Wait for SSH (lenient: don't crash if it never connects in the window)
    log("Waiting for SSH (up to ~3 min)...")
    ssh_ok = False
    for i in range(36):
        out = ssh(f"root@{ip}", "echo up", check=False, capture=True, timeout=8)
        if "up" in out:
            log(f"  SSH ready after {(i+1)*5}s")
            ssh_ok = True
            break
        time.sleep(5)
    if not ssh_ok:
        log("  SSH didn't respond yet - droplet might still be booting. Continuing with the rest of revive.")

    # 5b. Fix DNS cache, allocation IPs, then restart services in the right order.
    #
    # Order matters:
    #   1. Pin /etc/hosts so PHP-FPM resolves the Wings FQDN to the new IP immediately
    #      (system DNS cache may still hold the old IP for up to 5 min TTL).
    #   2. Restart PHP-FPM + pteroq so the panel is healthy with the new IP.
    #   3. Fix allocation IPs in the DB so the panel serves the new IP to Wings.
    #   4. Restart Wings LAST — it fetches fresh server config (with new IP) from the
    #      now-healthy panel. If Wings restarts before PHP-FPM is ready it gets stale
    #      config and Docker tries to bind to the old IP → server crashes on start.
    if ssh_ok:
        log(f"Pinning {server_addr} -> {ip} in /etc/hosts...")
        ssh(f"root@{ip}",
            f"sed -i '/{re.escape(server_addr)}/d' /etc/hosts && echo '{ip} {server_addr}' >> /etc/hosts",
            check=False, timeout=10)

        log("Restarting PHP-FPM and pteroq...")
        ssh(f"root@{ip}", "systemctl restart php8.3-fpm pteroq", check=False, timeout=30)
        time.sleep(8)

        log("Updating Pterodactyl allocations to new IP...")
        fix_php = (
            f"php -r 'require \"/var/www/pterodactyl/vendor/autoload.php\"; "
            f"$app = require \"/var/www/pterodactyl/bootstrap/app.php\"; "
            f"$app->make(\"Illuminate\\Contracts\\Console\\Kernel\")->bootstrap(); "
            f"foreach (\\Pterodactyl\\Models\\Allocation::all() as $a) {{ "
            f"  $a->ip = \"{ip}\"; $a->save(); "
            f"  echo \"alloc #\".$a->id.\" -> \".$a->ip.\"\\n\"; }}'"
        )
        out = ssh(f"root@{ip}", fix_php, check=False, capture=True, timeout=30)
        for line in out.splitlines():
            log(f"  {line}")

        log("Restarting Wings so it fetches fresh server config with new IP...")
        ssh(f"root@{ip}", "systemctl restart wings", check=False, timeout=30)
        time.sleep(5)

    # 5c. Wait for Wings to be active, then start the Minecraft server via API
    if ssh_ok:
        log("Waiting for Wings daemon to be active...")
        wings_up = False
        for _ in range(30):
            out = ssh(f"root@{ip}", "systemctl is-active wings", check=False, capture=True, timeout=10)
            if "active" in out and "inactive" not in out:
                wings_up = True
                log("  Wings is up")
                break
            time.sleep(4)
        if wings_up:
            log("Starting Minecraft server via Pterodactyl API...")
            # Run the curl on the droplet so we use the local backup.env credentials cleanly
            start_cmd = (
                'source /etc/mc-backup/backup.env && '
                'curl -s -X POST -H "Authorization: Bearer $PTERO_KEY" '
                '-H "Content-Type: application/json" -H "Accept: application/json" '
                '-d \'{"signal":"start"}\' '
                '"$PTERO_URL/api/client/servers/$SERVER_ID/power" '
                '&& echo SENT'
            )
            out = ssh(f"root@{ip}", start_cmd, check=False, capture=True, timeout=30)
            if "SENT" in out:
                log("  Start signal sent. Server will be online in ~30s.")
            else:
                log("  Start signal may have failed - check panel manually.")
        else:
            log("  Wings didn't come up in time - start the server manually from the panel.")

    # 6. Update .env DROPLET_IP
    env_path = ROOT / ".env"
    new_env = re.sub(r'^DROPLET_IP=.*$', f'DROPLET_IP="{ip}"', env_path.read_text(encoding="utf-8"), flags=re.M)
    env_path.write_text(new_env, encoding="utf-8")

    # 7. Clean up hibernation state and snapshot
    state_file.unlink()
    log("Deleting hibernation snapshot...")
    http("DELETE", f"https://api.digitalocean.com/v2/snapshots/{state['snapshot_id']}", headers=do)

    log("")
    log(f"Revived. Droplet {droplet_id} at {ip} is back online.")
    log("Cloudflare records updated (TTL 5 min for fast cutover).")
    log(f"Panel: {os.environ['PANEL_URL']}")
    log(f"MC:    {server_addr}")


if __name__ == "__main__":
    main()
