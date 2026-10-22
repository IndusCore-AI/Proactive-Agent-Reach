#!/usr/bin/env bash
# Publish the aggregation skill to teamctx's shared skills, so both founders'
# `ctx update` installs it into ~/.claude/skills/aggregate-silicon-valley/.
# Source of truth stays in this repo; run this after changing the skill:
#   SV_VM=<vm ssh target> SV_VM_KEY=<path to the team key> bash sv/ops/publish-skill.sh
# Follows teamctx's convention (k:970): copy into client/skills/<name>/ with a
# skill.json and commit on the VM's main. A client-only change needs no restart.
set -euo pipefail
SKILL="$(cd "$(dirname "$0")/../skill/aggregate-silicon-valley" && pwd)"
VM="${SV_VM:?set SV_VM to the VM ssh target}"
SSH=(ssh -o BatchMode=yes)
[ -n "${SV_VM_KEY:-}" ] && SSH+=(-i "$SV_VM_KEY")
REV="$(git -C "$SKILL" rev-parse --short HEAD 2>/dev/null || echo unknown)"
tar -C "$SKILL" --exclude '__pycache__' --exclude '*.pyc' -czf - . | "${SSH[@]}" "$VM" REV="$REV" bash -c '
  set -euo pipefail
  DEST=~/teamctx/client/skills/aggregate-silicon-valley
  rm -rf "$DEST.new" && mkdir -p "$DEST.new" && tar -xzf - -C "$DEST.new"
  rm -rf "$DEST" && mv "$DEST.new" "$DEST"
  cd ~/teamctx
  git add client/skills/aggregate-silicon-valley
  if git diff --cached --quiet; then echo "teamctx: skill unchanged"; else
    git -c user.name="keeping-up-sv publish" -c user.email="noreply@induscore.site" commit -qm "Shared skill aggregate-silicon-valley (Proactive-Agent-Reach $REV)"
    echo "teamctx: published at $(git rev-parse --short HEAD)"
  fi
'
