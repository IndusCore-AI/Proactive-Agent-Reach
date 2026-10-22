#!/usr/bin/env bash
# Idempotent: make sure tmux session `keeping-up-sv` has the api and tunnel windows.
SV="$(cd "$(dirname "$0")/.." && pwd)"
if ! tmux has-session -t keeping-up-sv 2>/dev/null; then
  tmux new-session -d -s keeping-up-sv -n api -c "$SV" "bash ops/run-api.sh"
fi
tmux list-windows -t keeping-up-sv -F '#W' | grep -qx api || tmux new-window -d -t keeping-up-sv -n api -c "$SV" "bash ops/run-api.sh"
tmux list-windows -t keeping-up-sv -F '#W' | grep -qx tunnel || tmux new-window -d -t keeping-up-sv -n tunnel -c "$SV" "bash ops/run-tunnel.sh"
