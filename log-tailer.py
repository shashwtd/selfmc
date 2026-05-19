#!/usr/bin/env python3
"""
Tails the Paper server log and forwards interesting events to Discord
via /opt/mc-tools/webhook.sh.

Handles:
- player join / leave
- server startup (Done (Xs)!) / stop
- crash patterns (FATAL, server thread Exception)
- player death messages
"""
import os
import re
import time
import subprocess
import logging
from collections import deque
from datetime import datetime, timedelta

LOG_FILE = "/var/lib/pterodactyl/volumes/<your-server-uuid>/logs/latest.log"
WEBHOOK_SCRIPT = "/opt/mc-tools/webhook.sh"
SELF_LOG = "/var/log/mc-log-tailer.log"

POLL_INTERVAL = 0.5      # seconds between read attempts when at EOF
RATE_LIMIT_WINDOW = 10   # seconds
RATE_LIMIT_MAX = 5       # max webhooks in window (silently drop excess)

logging.basicConfig(
    filename=SELF_LOG,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("log-tailer")

# ─── patterns ──────────────────────────────────────────────────────
TIMESTAMP = r"\[\d+:\d+:\d+\] \[[^\]]+/INFO\]:"

P_JOIN   = re.compile(rf"^{TIMESTAMP} (\S+) joined the game$")
P_LEAVE  = re.compile(rf"^{TIMESTAMP} (\S+) left the game$")
P_START  = re.compile(rf"^{TIMESTAMP} Done \(([\d.]+)s\)! For help")
P_STOP   = re.compile(rf"^{TIMESTAMP} Stopping (the )?server")
P_CRASH  = re.compile(r"\[Server thread/(FATAL|ERROR)\]|Caused by:|java\.lang\.\w+Exception")

# Death messages: line starting with a non-bracket word (player name) followed by a death verb.
DEATH_VERBS = [
    "was slain", "was shot", "was killed", "was blown up", "was pricked",
    "was squashed", "was poked", "was impaled", "was stung", "was struck by lightning",
    "was frozen", "was skewered", "was doomed", "was fireballed",
    "fell out of the world", "fell from", "fell off", "fell into",
    "drowned", "blew up", "starved to death", "suffocated",
    "burned to death", "went up in flames", "tried to swim in lava",
    "withered away", "froze to death",
    "didn't want to live", "discovered the floor was lava",
    "hit the ground too hard", "experienced kinetic energy",
    "died", "was roasted",
]
P_DEATH = re.compile(
    rf"^{TIMESTAMP} (\S+) ({'|'.join(map(re.escape, DEATH_VERBS))})\b(.*)$"
)

# ─── webhook helper ────────────────────────────────────────────────
_recent_sends = deque()

def _send(args):
    if not os.path.exists(WEBHOOK_SCRIPT):
        return
    now = time.time()
    while _recent_sends and now - _recent_sends[0] > RATE_LIMIT_WINDOW:
        _recent_sends.popleft()
    if len(_recent_sends) >= RATE_LIMIT_MAX:
        log.warning("Webhook rate-limited (dropping)")
        return
    _recent_sends.append(now)
    try:
        subprocess.run([WEBHOOK_SCRIPT] + args, timeout=10)
    except Exception as e:
        log.warning("Webhook call failed: %s", e)

def plain(message: str) -> None:
    """Send a one-line content message (no embed)."""
    _send([message])

def embed(title: str, desc: str, color: int = 3447003) -> None:
    """Send a rich embed (use sparingly for important events)."""
    _send([title, desc, str(color)])

# ─── log tailing ───────────────────────────────────────────────────
def tail_file(path):
    """Yield new lines forever, reopening when log rotates."""
    inode = None
    f = None
    while True:
        try:
            st = os.stat(path)
        except FileNotFoundError:
            time.sleep(POLL_INTERVAL)
            continue
        if inode != st.st_ino:
            if f:
                f.close()
            f = open(path, "r", errors="ignore")
            f.seek(0, os.SEEK_END)  # start at end on (re)open
            inode = st.st_ino
            log.info("Opened log file (inode=%d)", inode)
        line = f.readline()
        if line:
            yield line.rstrip("\n")
        else:
            time.sleep(POLL_INTERVAL)


def handle(line: str) -> None:
    m = P_JOIN.match(line)
    if m:
        plain(f"🟢 **{m.group(1)}** joined")
        return

    m = P_LEAVE.match(line)
    if m:
        plain(f"⚪ **{m.group(1)}** left")
        return

    m = P_START.match(line)
    if m:
        plain(f"🟢 Server online ({m.group(1)}s startup)")
        return

    if P_STOP.search(line):
        plain("🛑 Server stopping")
        return

    m = P_DEATH.match(line)
    if m:
        player = m.group(1)
        cause = m.group(2) + (m.group(3) or "")
        plain(f"💀 **{player}** {cause}")
        return

    if P_CRASH.search(line):
        # Multi-line / data-rich → embed.
        snippet = line.strip()[:300]
        embed("Server error", f"```\n{snippet}\n```", 15548997)
        return


def main():
    log.info("Log tailer started, watching %s", LOG_FILE)
    for line in tail_file(LOG_FILE):
        try:
            handle(line)
        except Exception as e:
            log.warning("Handler failed on line: %s — %s", line[:120], e)


if __name__ == "__main__":
    main()
