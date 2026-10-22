#!/usr/bin/env bash
# The API on 127.0.0.1 only, restarted if it dies. Lives in tmux keeping-up-sv:api.
SV="$(cd "$(dirname "$0")/.." && pwd)"
LOG="$HOME/.local/state/keeping-up-sv/logs/api.log"
set -a; . "$HOME/.config/keeping-up-sv/env"; set +a
cd "$SV/api"
while true; do
  .venv/bin/uvicorn app:app --host 127.0.0.1 --port "${SV_PORT:-8793}" --workers 2 \
    --proxy-headers --no-server-header >> "$LOG" 2>&1
  echo "$(date -u +%FT%TZ) api exited; restarting in 3s" >> "$LOG"
  sleep 3
done
