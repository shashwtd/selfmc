"""Shared helpers for hibernate.py and revive.py."""
import json
import os
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_env():
    """Read .env and merge into os.environ. Expands $env:VAR references."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        sys.exit(".env not found")
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r'^([A-Z_]+)\s*=\s*"?([^"]*)"?\s*$', line)
        if not m:
            continue
        k, v = m.group(1), m.group(2)
        # Expand $env:VAR (Windows/PowerShell) and $VAR / ${VAR} (Unix)
        v = re.sub(r"\$env:([A-Za-z_][A-Za-z0-9_]*)",
                   lambda mm: os.environ.get(mm.group(1), ""), v)
        v = re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}",
                   lambda mm: os.environ.get(mm.group(1), ""), v)
        v = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)",
                   lambda mm: os.environ.get(mm.group(1), ""), v)
        v = os.path.expanduser(v)   # expand ~ to home dir on all platforms
        os.environ[k] = v


def require(*keys):
    missing = [k for k in keys if not os.environ.get(k)]
    if missing:
        sys.exit(f"Missing in .env: {', '.join(missing)}")


def http(method, url, headers=None, body=None, timeout=60):
    """Tiny HTTP client wrapping urllib. Returns parsed JSON."""
    data = None
    h = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read()
            if not raw:
                return {}
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} from {url}: {body_txt}") from None


def ssh(host_user_ip, command, key=None, capture=True, timeout=600, check=True):
    """Run a command over SSH. Returns stdout as str.
    If check=False, timeouts and non-zero exits return empty string instead of raising.
    """
    key = key or os.environ["SSH_KEY_AUTOMATION"]
    args = [
        "ssh",
        "-i", key,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        host_user_ip,
        command,
    ]
    try:
        res = subprocess.run(args, capture_output=capture, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        if not check:
            return ""
        raise
    if check and res.returncode != 0:
        raise RuntimeError(
            f"SSH command failed (rc={res.returncode}):\n  cmd: {command}\n  stderr: {res.stderr.strip()}"
        )
    return res.stdout


def ssh_stream(host_user_ip, command, key=None, timeout=3600, prefix="  "):
    """Run a command over SSH, streaming output to stdout in real-time.
    Returns (full_stdout, return_code).
    """
    key = key or os.environ["SSH_KEY_AUTOMATION"]
    args = [
        "ssh",
        "-i", key,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        host_user_ip,
        command,
    ]
    proc = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    captured = []
    try:
        for line in proc.stdout:
            line = line.rstrip()
            captured.append(line)
            print(f"{prefix}{line}", flush=True)
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise
    return "\n".join(captured), proc.returncode


def log(msg=""):
    print(msg, flush=True)
