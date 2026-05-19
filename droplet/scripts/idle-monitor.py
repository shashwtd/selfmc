#!/usr/bin/env python3
"""
Minecraft idle backup monitor.
Polls the Paper server log to count online players.
After IDLE_THRESHOLD seconds of zero players, triggers /opt/mc-tools/backup.sh.
"""
import os
import re
import time
import subprocess
import logging
from datetime import datetime, timedelta

WEBHOOK_SCRIPT = "/opt/mc-tools/webhook.sh"

def notify_plain(message):
    if os.path.exists(WEBHOOK_SCRIPT):
        try:
            subprocess.run([WEBHOOK_SCRIPT, message], timeout=10)
        except Exception:
            pass

LOG_FILE = "/var/lib/pterodactyl/volumes/<your-server-uuid>/logs/latest.log"
BACKUP_SCRIPT = "/opt/mc-tools/backup.sh"
MONITOR_LOG = "/var/log/mc-idle-monitor.log"

POLL_INTERVAL = 300       # 5 min between checks
IDLE_THRESHOLD = 1800     # 30 min of zero players → backup
COOLDOWN = 2 * 60 * 60    # 2h cooldown between idle backups

JOIN_RE = re.compile(r"joined the game")
LEAVE_RE = re.compile(r"left the game")
STARTUP_RE = re.compile(r"Done \(\d+(\.\d+)?s\)!")
STOP_RE = re.compile(r"Stopping (the )?server")

logging.basicConfig(
    filename=MONITOR_LOG,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("idle-monitor")


def player_count():
    """Replay log file, count net player joins/leaves since last server start."""
    if not os.path.exists(LOG_FILE):
        return None  # server not running / no log yet
    count = 0
    try:
        with open(LOG_FILE, "r", errors="ignore") as f:
            for line in f:
                if STARTUP_RE.search(line) or STOP_RE.search(line):
                    count = 0
                elif JOIN_RE.search(line):
                    count += 1
                elif LEAVE_RE.search(line):
                    count -= 1
    except Exception as e:
        log.warning("Failed to read log: %s", e)
        return None
    return max(0, count)


def run_backup():
    log.info("Triggering backup script")
    try:
        result = subprocess.run([BACKUP_SCRIPT], capture_output=True, text=True, timeout=3600)
        if result.returncode == 0:
            log.info("Backup completed successfully")
        else:
            log.error("Backup exited with code %d: %s", result.returncode, result.stderr[-500:])
    except subprocess.TimeoutExpired:
        log.error("Backup script timed out after 1 hour")
    except Exception as e:
        log.error("Backup script crashed: %s", e)


def main():
    log.info("Idle monitor started (threshold=%ds, cooldown=%ds, poll=%ds)",
             IDLE_THRESHOLD, COOLDOWN, POLL_INTERVAL)
    idle_seconds = 0
    last_backup = None

    while True:
        count = player_count()
        if count is None:
            log.debug("Server log unavailable, treating as not-idle")
            idle_seconds = 0
        elif count == 0:
            idle_seconds += POLL_INTERVAL
        else:
            if idle_seconds > 0:
                log.info("Players online (%d), resetting idle timer", count)
            idle_seconds = 0

        if idle_seconds >= IDLE_THRESHOLD:
            now = datetime.now()
            if last_backup and (now - last_backup) < timedelta(seconds=COOLDOWN):
                remaining = COOLDOWN - (now - last_backup).total_seconds()
                log.debug("Idle threshold met but in cooldown (%ds remaining)", int(remaining))
            else:
                log.info("Idle threshold reached (%ds with 0 players), backing up", idle_seconds)
                notify_plain(f"🌙 Idle for {idle_seconds // 60} min — running backup")
                run_backup()
                last_backup = datetime.now()
                idle_seconds = 0

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
