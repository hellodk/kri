#!/usr/bin/env bash
# kri API container entrypoint (#1050).
#
# Replaces the previous inline `sh -c` command in deploy/docker-compose.yml:
# the chown lines are no-ops when the volume is already owned correctly and
# never fail the boot (the container runs as non-root appuser), migrate.sh
# acquires a PostgreSQL advisory lock before alembic upgrade head, and
# exec makes uvicorn PID 1 so it receives SIGTERM directly (compose pairs
# this with init: true for zombie reaping).
set -euo pipefail

chown "$(id -u):$(id -g)" /home/appuser/.kri 2>/dev/null || true
chown -R "$(id -u):$(id -g)" /home/appuser/.kri/git-repos 2>/dev/null || true

bash /app/deploy/migrate.sh

exec uv run uvicorn fleet_platform.api.main:app --host 0.0.0.0 --port 8000 --log-level info
