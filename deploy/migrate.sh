#!/bin/bash
# deploy/migrate.sh — run Alembic migrations with a PostgreSQL advisory lock.
#
# Prevents concurrent migration races when multiple API container replicas start
# at the same time (issue #90).  The advisory lock (id 20260101) is held for the
# duration of the `alembic upgrade head` call and released automatically when the
# connection closes — even if the migration fails.
#
# Requires: DATABASE_URL env var (postgresql+psycopg://... form)
# Requires: psycopg (psycopg3) — already in the project dependencies
set -e

echo "[migrate] Acquiring PostgreSQL advisory lock and running Alembic migrations…"

uv run python - <<'PYEOF'
import os
import subprocess
import sys

import psycopg

db_url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")

try:
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(20260101)")
        print("[migrate] Advisory lock acquired (id=20260101)")
        try:
            result = subprocess.run(
                ["uv", "run", "alembic", "upgrade", "head"],
                check=True,
            )
            print("[migrate] Alembic upgrade head completed successfully")
        finally:
            conn.execute("SELECT pg_advisory_unlock(20260101)")
            print("[migrate] Advisory lock released")
except psycopg.OperationalError as exc:
    print(f"[migrate] ERROR: Cannot connect to database: {exc}", file=sys.stderr)
    sys.exit(1)
except subprocess.CalledProcessError as exc:
    print(f"[migrate] ERROR: Alembic migration failed (exit {exc.returncode})", file=sys.stderr)
    sys.exit(exc.returncode)
PYEOF

echo "[migrate] Done."
