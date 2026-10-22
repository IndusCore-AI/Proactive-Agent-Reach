#!/usr/bin/env bash
# Free Cloudflare quick tunnel to the API, forever (the teamctx pattern, k:249).
# A restart gets a new *.trycloudflare.com hostname: it is written to
# tunnel_url and announced, HMAC-signed, on the ntfy topic, where the Vercel
# server picks it up. Lives in tmux keeping-up-sv:tunnel.
SV="$(cd "$(dirname "$0")/.." && pwd)"
STATE="$HOME/.local/state/keeping-up-sv"
set -a; . "$HOME/.config/keeping-up-sv/env"; set +a
mkdir -p "$STATE/logs"
while true; do
  : > "$STATE/logs/tunnel.log"
  cloudflared tunnel --url "http://127.0.0.1:${SV_PORT:-8793}" --no-autoupdate >> "$STATE/logs/tunnel.log" 2>&1 &
  PID=$!
  URL=""
  for _ in $(seq 1 90); do
    URL="$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$STATE/logs/tunnel.log" | head -1 || true)"
    [ -n "$URL" ] && break
    sleep 1
  done
  if [ -n "$URL" ]; then
    echo "$URL" > "$STATE/tunnel_url"
    "$SV/api/.venv/bin/python" "$SV/ops/announce.py" || true
    echo "$(date -u +%FT%TZ) tunnel up: $URL"
  else
    echo "$(date -u +%FT%TZ) no tunnel URL after 90s"
  fi
  wait "$PID"
  echo "$(date -u +%FT%TZ) cloudflared exited; restarting in 5s"
  sleep 5
done
