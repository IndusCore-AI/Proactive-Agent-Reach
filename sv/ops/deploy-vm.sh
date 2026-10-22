#!/usr/bin/env bash
# Deploy the API to the prod VM from either founder's laptop:
#   SV_VM=<vm ssh target> SV_VM_KEY=<path to the team key> bash sv/ops/deploy-vm.sh [branch]
# (host and key: see teamctx, never this public repo)
# (SV_VM may also be an ssh config alias such as `spd`.) Pulls the branch into
# ~/keeping-up-sv, applies migrations and restarts the API window. The tunnel
# keeps its URL because only the API process restarts.
set -euo pipefail
BRANCH="${1:-main}"
VM="${SV_VM:?set SV_VM to the VM ssh target (user@host or an ssh config alias)}"
SSH=(ssh -o BatchMode=yes)
[ -n "${SV_VM_KEY:-}" ] && SSH+=(-i "$SV_VM_KEY")
"${SSH[@]}" "$VM" BRANCH="$BRANCH" bash -s <<'REMOTE'
set -euo pipefail
REPO=https://github.com/gaurpulkit/Proactive-Agent-Reach.git
DIR="$HOME/keeping-up-sv"
[ -d "$DIR/.git" ] || git clone -q "$REPO" "$DIR"
cd "$DIR"
git fetch -q origin "$BRANCH"
git checkout -q -B "$BRANCH" "origin/$BRANCH"
bash sv/ops/vm-setup.sh
tmux kill-window -t keeping-up-sv:api 2>/dev/null || true
pkill -f "uvicorn app:app --host 127.0.0.1 --port $(grep ^SV_PORT= ~/.config/keeping-up-sv/env | cut -d= -f2) " 2>/dev/null || true
sleep 2
bash sv/ops/start.sh
sleep 5
curl -fsS "http://127.0.0.1:$(grep ^SV_PORT= ~/.config/keeping-up-sv/env | cut -d= -f2)/v1/health" && echo
echo "deployed $(git rev-parse --short HEAD) on $BRANCH; tunnel: $(cat ~/.local/state/keeping-up-sv/tunnel_url 2>/dev/null || echo 'starting')"
REMOTE
