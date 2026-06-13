#!/bin/bash
# kri Fleet Platform — launchd wrapper.
#
# Single launcher used by all four com.kri.*.plist files. Sources the env
# file, locates `uv` regardless of where it was installed, and execs the
# right Celery / uvicorn command for the given role.
#
# Override defaults via the env file or the calling plist:
#   KRI_HOME       — repo root (default /opt/kri)
#   KRI_ENV_FILE   — path to env file (default /etc/kri/kri.env)
#   UV             — explicit path to the uv binary (optional)

set -euo pipefail

KRI_HOME="${KRI_HOME:-/opt/kri}"
KRI_ENV_FILE="${KRI_ENV_FILE:-/etc/kri/kri.env}"

if [ -r "$KRI_ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$KRI_ENV_FILE"
    set +a
fi

# Auto-detect uv unless the caller pre-set UV. macOS install paths differ:
#   Apple Silicon Homebrew → /opt/homebrew/bin/uv
#   Intel Homebrew         → /usr/local/bin/uv
#   astral.sh installer    → ~/.local/bin/uv
#   Linux package manager  → /usr/bin/uv
if [ -z "${UV:-}" ]; then
    for candidate in \
        "${HOME:-/var/empty}/.local/bin/uv" \
        "/opt/homebrew/bin/uv" \
        "/usr/local/bin/uv" \
        "/usr/bin/uv"
    do
        if [ -x "$candidate" ]; then
            UV="$candidate"
            break
        fi
    done
fi

if [ -z "${UV:-}" ]; then
    echo "kri-launch: uv not found in any of the expected locations" >&2
    echo "kri-launch: install with 'curl -LsSf https://astral.sh/uv/install.sh | sh'" >&2
    exit 127
fi

cd "$KRI_HOME"

ROLE="${1:-}"
case "$ROLE" in
    api)
        # Alembic advisory-lock-protected; safe with multi-replica restart.
        bash "$KRI_HOME/deploy/migrate.sh"
        exec "$UV" run uvicorn fleet_platform.api.main:app \
            --host 0.0.0.0 --port 8000 --log-level info
        ;;
    worker)
        exec "$UV" run celery -A fleet_platform.workers.celery_app worker \
            --queues default,maintenance,drift,sbom --concurrency 4 --loglevel info
        ;;
    worker-ansible)
        exec "$UV" run celery -A fleet_platform.workers.celery_app worker \
            --queues ansible --concurrency 2 --loglevel info
        ;;
    beat)
        exec "$UV" run celery -A fleet_platform.workers.celery_app beat \
            --scheduler=redbeat.RedBeatScheduler --loglevel info
        ;;
    *)
        echo "Usage: $0 {api|worker|worker-ansible|beat}" >&2
        exit 2
        ;;
esac
