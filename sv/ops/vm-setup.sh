#!/usr/bin/env bash
# One-time, idempotent setup of Keeping Up with Silicon Valley on the prod VM.
# Run on the VM from the clone:  bash sv/ops/vm-setup.sh
#
# Creates (only if missing): the sv_app role, the induscore_sv and
# induscore_sv_test databases (both owned by sv_app, CONNECT revoked from
# PUBLIC), ~/.config/keeping-up-sv/env (mode 600) with the DB password, the
# announce HMAC secret and the ntfy topic (token hashes are filled in by hand),
# the API venv, and the cron entries
# that keep the API and its tunnel up. Applies migrations. Never touches the
# IndusCore databases.
set -euo pipefail
SV="$(cd "$(dirname "$0")/.." && pwd)"
CONF="$HOME/.config/keeping-up-sv"
ENV="$CONF/env"
STATE="$HOME/.local/state/keeping-up-sv"
mkdir -p "$CONF" "$STATE/logs"
chmod 700 "$CONF"

rand() { python3 -c "import secrets; print(secrets.token_urlsafe($1))"; }
if [ ! -s "$ENV" ]; then
  umask 077
  PW="$(rand 24)"
  cat > "$ENV" <<EOF
SV_DATABASE_URL=postgresql://sv_app:$PW@127.0.0.1:5432/induscore_sv
SV_TEST_DATABASE_URL=postgresql://sv_app:$PW@127.0.0.1:5432/induscore_sv_test
SV_PORT=8793
SV_READ_TOKEN_SHA256=
SV_FOUNDERS_TOKEN_SHA256=
SV_ANNOUNCE_SECRET=$(rand 32)
SV_NTFY_TOPIC=ksv-$(python3 -c 'import secrets; print(secrets.token_hex(12))')
EOF
  echo "wrote $ENV"
fi
chmod 600 "$ENV"
# Keys added after the first setup: present but empty until filled in by hand.
# An empty SV_FOUNDERS_TOKEN_SHA256 keeps /v1/private/* (the founders' desk) closed (403).
if ! grep -q '^SV_FOUNDERS_TOKEN_SHA256=' "$ENV"; then
  [ -n "$(tail -c1 "$ENV")" ] && echo >> "$ENV"
  echo 'SV_FOUNDERS_TOKEN_SHA256=' >> "$ENV"
fi
set -a; . "$ENV"; set +a
PW="$(python3 -c 'import os, urllib.parse as u; print(u.urlsplit(os.environ["SV_DATABASE_URL"]).password)')"

# Password goes over stdin, never on a command line.
sudo -u postgres psql -v ON_ERROR_STOP=1 -q <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'sv_app') THEN
    CREATE ROLE sv_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '$PW';
  ELSE
    ALTER ROLE sv_app LOGIN PASSWORD '$PW';
  END IF;
END \$\$;
SQL
for db in induscore_sv induscore_sv_test; do
  if ! sudo -u postgres psql -Atc "select 1 from pg_database where datname = '$db'" | grep -q 1; then
    sudo -u postgres createdb -O sv_app "$db"
    echo "created database $db"
  fi
  sudo -u postgres psql -q -d "$db" -c "revoke connect on database $db from public; grant connect on database $db to sv_app;"
done

if [ ! -x "$SV/api/.venv/bin/python" ]; then
  python3 -m venv "$SV/api/.venv"
fi
"$SV/api/.venv/bin/pip" install -q --upgrade pip
"$SV/api/.venv/bin/pip" install -q -r "$SV/api/requirements.txt"
(cd "$SV/api" && .venv/bin/python manage.py migrate)

# Keep the API + tunnel alive (same shape as teamctx's entries). These are
# process watchdogs and a URL re-announcement; nothing here aggregates content.
CRON="$(crontab -l 2>/dev/null || true)"
add_cron() { grep -q "# job:$1\$" <<<"$CRON" || CRON="$CRON"$'\n'"$2 # job:$1"; }
add_cron keeping-up-sv-start "@reboot sleep 30 && /bin/bash $SV/ops/start.sh"
add_cron keeping-up-sv-watchdog "*/10 * * * * /bin/bash $SV/ops/start.sh"
add_cron keeping-up-sv-announce "5 */6 * * * $SV/api/.venv/bin/python $SV/ops/announce.py"
printf '%s\n' "$CRON" | sed '/^$/d' | crontab -
echo "setup ok"
