#!/usr/bin/env bash
# The API on 127.0.0.1 only, restarted if it dies. Lives in tmux keeping-up-sv:api.
# Killing this window (deploy-vm.sh does) also stops uvicorn: the trap below
# takes the server down with the loop, so a restart never finds the port held.
SV="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$HOME/.local/state/keeping-up-sv/logs/api.log"
set -a; . "$HOME/.config/keeping-up-sv/env"; set +a
PORT="${SV_PORT:-8793}"
PATTERN="uvicorn app:app --host 127.0.0.1 --port $PORT"
cd "$SV/api"
CHILD=""
trap '[ -n "$CHILD" ] && kill "$CHILD" 2>/dev/null; exit 0' HUP INT TERM EXIT
# A server left behind by an older loop would hold the port forever.
pkill -f "$PATTERN" 2>/dev/null && sleep 2
while true; do
  .venv/bin/uvicorn app:app --host 127.0.0.1 --port "$PORT" --workers 2 \
    --proxy-headers --no-server-header >> "$LOG" 2>&1 &
  CHILD=$!
  wait "$CHILD"
  echo "$(date -u +%FT%TZ) api exited; restarting in 3s" >> "$LOG"
  sleep 3
done
