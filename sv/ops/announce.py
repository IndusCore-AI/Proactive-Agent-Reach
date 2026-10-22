"""Publish the API's current tunnel URL on the ntfy topic, signed with
SV_ANNOUNCE_SECRET, so the Vercel server can find it after a tunnel restart.
ntfy keeps messages about 12 hours, so cron re-announces every 6 hours.

Message body: {"url": ..., "ts": unix seconds, "sig": hex hmac-sha256(secret, f"{url}|{ts}")}
"""
import hashlib
import hmac
import json
import os
import time
import urllib.request
from pathlib import Path


def load_env() -> None:
    for line in (Path.home() / ".config/keeping-up-sv/env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k, v)


def main() -> None:
    load_env()
    url_file = Path.home() / ".local/state/keeping-up-sv/tunnel_url"
    if not url_file.exists():
        raise SystemExit("no tunnel_url yet")
    url = url_file.read_text().strip()
    ts = int(time.time())
    sig = hmac.new(os.environ["SV_ANNOUNCE_SECRET"].encode(), f"{url}|{ts}".encode(), hashlib.sha256).hexdigest()
    body = json.dumps({"url": url, "ts": ts, "sig": sig}).encode()
    req = urllib.request.Request(f"https://ntfy.sh/{os.environ['SV_NTFY_TOPIC']}", data=body, method="POST",
                                 headers={"Title": "keeping-up-sv api url"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        print(f"announced {url} ({resp.status})")


if __name__ == "__main__":
    main()
