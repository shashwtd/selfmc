#!/usr/bin/env python3
"""
Snapshots the droplet, then destroys it.
Cost goes from $24/mo to ~$1/mo (just snapshot storage).
Run `revive.py` to bring it back in ~5 min.

Requires DO_API_TOKEN, DROPLET_IP, SSH_KEY_AUTOMATION in .env.
"""
import datetime
import json
import os
import re
import sys
import time
from pathlib import Path

from _common import ROOT, load_env, require, http, ssh, ssh_stream, log


def wait_action(token, action_id, label):
    h = {"Authorization": f"Bearer {token}"}
    while True:
        r = http("GET", f"https://api.digitalocean.com/v2/actions/{action_id}", headers=h)
        status = r["action"]["status"]
        log(f"  [{label}] {status}...")
        if status == "completed":
            return
        if status == "errored":
            sys.exit(f"DO action {action_id} errored")
        time.sleep(8)


def main():
    load_env()
    require("DO_API_TOKEN", "DROPLET_IP", "SSH_KEY_AUTOMATION")
    token = os.environ["DO_API_TOKEN"]
    ip = os.environ["DROPLET_IP"]
    host = f"root@{ip}"
    do_headers = {"Authorization": f"Bearer {token}"}

    # 1. Find droplet
    log(f"Finding droplet at {ip}...")
    droplets = http("GET", "https://api.digitalocean.com/v2/droplets?per_page=200", headers=do_headers)["droplets"]
    droplet = next(
        (d for d in droplets if any(n["ip_address"] == ip for n in d["networks"]["v4"])),
        None,
    )
    if not droplet:
        sys.exit(f"No droplet found at {ip}")
    droplet_id = droplet["id"]
    region = droplet["region"]["slug"]
    size = droplet["size_slug"]
    log(f"  droplet {droplet_id}  region={region}  size={size}")

    # 1b. Warn players if anyone is online
    log("Checking for online players...")
    list_out = ssh(host,
        "source /etc/mc-backup/backup.env && "
        "mcrcon -H localhost -P 25575 -p \"$RCON_PASSWORD\" list",
        check=False, capture=True, timeout=15)
    m = re.search(r"There are (\d+) of a max", list_out)
    online = int(m.group(1)) if m else 0
    if online > 0:
        log(f"  {online} player(s) online — notifying and kicking...")
        def rcon(cmd):
            ssh(host,
                f"source /etc/mc-backup/backup.env && "
                f"mcrcon -H localhost -P 25575 -p \"$RCON_PASSWORD\" \"{cmd}\"",
                check=False, timeout=10)
        rcon("say [SERVER] Hibernate started. World is being saved — you will be disconnected shortly.")
        time.sleep(5)
        rcon("kick @a Server is hibernating.")
        log("  Players kicked.")
    else:
        log("  No players online.")

    # 2. Pause idle-monitor + wait for any backup in flight
    log("Pausing idle-monitor service...")
    ssh(host, "systemctl stop idle-monitor.service")

    log("Waiting for any in-flight backup to finish...")
    for _ in range(180):
        out = ssh(host, "flock -n /tmp/mc-backup.lock -c 'echo FREE' 2>/dev/null || echo BUSY", check=False)
        if "FREE" in out:
            log("  lock is free")
            break
        log("  backup in progress, waiting 10s...")
        time.sleep(10)
    else:
        sys.exit("Existing backup never finished. Investigate /var/log/mc-backup.log on droplet.")

    # 3. Run final backup with live progress streaming
    log("")
    log("Running final backup (streaming progress)...")
    backup_start = datetime.datetime.now(datetime.timezone.utc)
    # Pipe backup.sh + tail -f the log so we see restic's per-file progress
    # `stdbuf -oL` keeps output line-buffered through the SSH pipe.
    cmd = (
        "(stdbuf -oL /opt/mc-tools/backup.sh & "
        "BPID=$!; "
        "tail -n0 -F /var/log/mc-backup.log --pid=$BPID 2>/dev/null & "
        "TPID=$!; "
        "wait $BPID; RC=$?; "
        "kill $TPID 2>/dev/null; "
        "echo EXIT_CODE=$RC)"
    )
    backup_out, rc = ssh_stream(host, cmd, timeout=3600)
    if "EXIT_CODE=0" not in backup_out:
        sys.exit("Backup script returned non-zero. Aborting. Check /var/log/mc-backup.log on droplet.")
    if "Backup already running, skipping" in backup_out:
        sys.exit("Backup was skipped (lock held). Aborting hibernate, no fresh snapshot guaranteed.")

    # 4. Verify fresh snapshot landed on Drive
    log("")
    log("Verifying snapshot on Drive...")
    # `--latest 1` is per-host, which is wrong after revive (new droplets have new hostnames).
    # Just fetch all snapshots and pick the most recent by time.
    snap_out = ssh(
        host,
        "source /etc/mc-backup/backup.env && export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE && restic snapshots --json",
    )
    snaps = json.loads(snap_out)
    if not snaps:
        sys.exit("Could not read restic snapshots. Aborting.")
    # Most recent by time across all hosts
    snaps.sort(key=lambda s: s["time"], reverse=True)
    latest = snaps[0]
    snap_time = datetime.datetime.fromisoformat(latest["time"].replace("Z", "+00:00")).astimezone(datetime.timezone.utc)
    if snap_time < backup_start:
        sys.exit(
            f"Latest restic snapshot is from {snap_time}, BEFORE this backup started ({backup_start}). "
            f"Backup did not produce a new snapshot — aborting."
        )
    log(f"  OK: restic snapshot {latest['short_id']} at {snap_time} on host {latest.get('hostname','?')}")

    # 5. Power off droplet
    log("")
    log("Powering off droplet...")
    r = http(
        "POST", f"https://api.digitalocean.com/v2/droplets/{droplet_id}/actions",
        headers=do_headers, body={"type": "shutdown"},
    )
    wait_action(token, r["action"]["id"], "shutdown")

    # 6. Create snapshot
    snap_name = f"mc-hibernate-{datetime.datetime.now().strftime('%Y%m%d-%H%M')}"
    log("")
    log(f"Creating snapshot '{snap_name}'...")
    r = http(
        "POST", f"https://api.digitalocean.com/v2/droplets/{droplet_id}/actions",
        headers=do_headers, body={"type": "snapshot", "name": snap_name},
    )
    wait_action(token, r["action"]["id"], "snapshot")

    snaps = http("GET", f"https://api.digitalocean.com/v2/droplets/{droplet_id}/snapshots", headers=do_headers)["snapshots"]
    snap = next((s for s in snaps if s["name"] == snap_name), None)
    if not snap:
        sys.exit("Snapshot created but cannot find by name. Check DO dashboard.")
    gb = round(snap["size_gigabytes"], 1)
    log(f"  snapshot id {snap['id']}  size {gb} GB")

    # 7. Destroy droplet
    log("")
    log("Destroying droplet...")
    http("DELETE", f"https://api.digitalocean.com/v2/droplets/{droplet_id}", headers=do_headers)

    # 8. Save state
    state = {
        "snapshot_id":   snap["id"],
        "snapshot_name": snap_name,
        "region":        region,
        "size":          size,
        "hibernated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "last_ip":       ip,
    }
    (ROOT / "hibernation-state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")

    cost = round(gb * 0.06, 2)
    log("")
    log(f"Hibernated. Snapshot stored ({gb} GB, about ${cost}/month).")
    log("Run revive.py to bring it back.")


if __name__ == "__main__":
    main()
