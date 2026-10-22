"""Admin commands for the induscore_sv database. Run on the VM from sv/api:

  .venv/bin/python manage.py migrate              apply migrations/NNN_*.sql not yet applied
  .venv/bin/python manage.py issue-token NAME     create or rotate NAME's ingest token; prints it once
  .venv/bin/python manage.py revoke-token NAME
  .venv/bin/python manage.py tokens               list token names (never the tokens)
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sys
from pathlib import Path

import psycopg

DATABASE_URL = os.environ.get("SV_DATABASE_URL", "postgresql:///induscore_sv")
MIGRATIONS = Path(__file__).with_name("migrations")


def migrate(conn: psycopg.Connection) -> list[str]:
    conn.execute("create table if not exists schema_migrations (version text primary key, applied_at timestamptz not null default now())")
    done = {r[0] for r in conn.execute("select version from schema_migrations")}
    applied = []
    for path in sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql")):
        if path.stem in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text())
            conn.execute("insert into schema_migrations (version) values (%s)", (path.stem,))
        applied.append(path.stem)
    return applied


def issue_token(conn: psycopg.Connection, name: str) -> str:
    if not name.isidentifier() or len(name) > 32:
        raise SystemExit("name must be a short identifier, e.g. pulkit")
    token = "svi_" + secrets.token_urlsafe(32)
    conn.execute(
        "insert into ingest_tokens (name, token_hash) values (%s, %s) "
        "on conflict (name) do update set token_hash = excluded.token_hash, created_at = now(), revoked_at = null",
        (name, hashlib.sha256(token.encode()).hexdigest()),
    )
    return token


def main(argv: list[str]) -> None:
    if not argv:
        raise SystemExit(__doc__)
    cmd, *rest = argv
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        if cmd == "migrate":
            applied = migrate(conn)
            print("applied: " + (", ".join(applied) if applied else "nothing, already at head"))
        elif cmd == "issue-token" and len(rest) == 1:
            print(issue_token(conn, rest[0]))
        elif cmd == "revoke-token" and len(rest) == 1:
            n = conn.execute("update ingest_tokens set revoked_at = now() where name = %s and revoked_at is null", (rest[0],)).rowcount
            print(f"revoked {n}")
        elif cmd == "tokens":
            for name, created, revoked in conn.execute("select name, created_at, revoked_at from ingest_tokens order by name"):
                print(f"{name}\tcreated {created:%Y-%m-%d}\t{'revoked ' + f'{revoked:%Y-%m-%d}' if revoked else 'active'}")
        else:
            raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
