#!/usr/bin/env bash
# kri — start/stop/status for the kri fleet management platform
# Usage: kri.sh [start|stop|status|restart|logs [service]|dev|test [grep]]

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO_DIR/.venv/bin/activate"
LOGS_DIR="$REPO_DIR/.kri-logs"
PID_DIR="$REPO_DIR/.kri-pids"
COMPOSE_FILE="$REPO_DIR/deploy/docker-compose.yml"
COMPOSE_DEV_OVERRIDE="$REPO_DIR/deploy/docker-compose.override.yml"
FRONTEND_DIR="$REPO_DIR/frontend"

mkdir -p "$LOGS_DIR" "$PID_DIR"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*"; }

# ── Docker Compose commands ───────────────────────────────────────────────────

cmd_start() {
  echo ""
  echo "  kri fleet management platform"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  Starting all services via Docker Compose…"
  docker compose -f "$COMPOSE_FILE" up -d --build
  echo ""
  ok "kri is up →  http://localhost"
  echo "   API docs →  http://localhost/api/docs"
  echo ""
}

cmd_stop() {
  echo ""
  echo "  Stopping kri…"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  docker compose -f "$COMPOSE_FILE" down
  ok "kri stopped"
  echo ""
}

cmd_status() {
  echo ""
  echo "  kri status"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  docker compose -f "$COMPOSE_FILE" ps
  echo ""
}

cmd_logs() {
  local svc="${2:-}"
  if [[ -n "$svc" ]]; then
    docker compose -f "$COMPOSE_FILE" logs -f "$svc"
  else
    docker compose -f "$COMPOSE_FILE" logs -f
  fi
}

cmd_restart() {
  cmd_stop
  cmd_start
}

# ── Local dev (old behaviour) ─────────────────────────────────────────────────

is_running() {
  local pid_file="$PID_DIR/$1.pid"
  [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

stop_local_service() {
  local name="$1"
  local pid_file="$PID_DIR/$name.pid"
  if is_running "$name"; then
    kill "$(cat "$pid_file")" 2>/dev/null && ok "Stopped $name" || warn "Could not stop $name"
    rm -f "$pid_file"
  else
    warn "$name was not running"
  fi
}

start_infra_local() {
  echo "Starting infrastructure (postgres + redis)…"
  # Use override so db:5432 and redis:6379 are exposed to local processes
  docker compose -f "$COMPOSE_FILE" -f "$COMPOSE_DEV_OVERRIDE" up -d db redis --quiet-pull 2>&1 | tail -2

  local retries=20
  while [[ $retries -gt 0 ]]; do
    local pg_health redis_health
    pg_health=$(docker compose -f "$COMPOSE_FILE" -f "$COMPOSE_DEV_OVERRIDE" ps --format json db 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0].get('Health','') if isinstance(d,list) else d.get('Health',''))" 2>/dev/null || echo "unknown")
    redis_health=$(docker compose -f "$COMPOSE_FILE" -f "$COMPOSE_DEV_OVERRIDE" ps --format json redis 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0].get('Health','') if isinstance(d,list) else d.get('Health',''))" 2>/dev/null || echo "unknown")
    if [[ "$pg_health" == "healthy" && "$redis_health" == "healthy" ]]; then
      ok "Infrastructure ready"
      return 0
    fi
    sleep 1
    ((retries--))
  done
  err "Infrastructure did not become healthy in time"
  exit 1
}

start_backend_local() {
  if is_running "api"; then
    warn "API already running (pid $(cat "$PID_DIR/api.pid"))"
    return
  fi
  echo "Starting API server…"
  # shellcheck disable=SC1090
  source "$VENV"
  cd "$REPO_DIR"
  uvicorn fleet_platform.api.main:app \
    --host 0.0.0.0 --port 8000 \
    --log-level info \
    > "$LOGS_DIR/api.log" 2>&1 &
  echo $! > "$PID_DIR/api.pid"
  sleep 2
  if is_running "api"; then
    ok "API running on :8000 (log: .kri-logs/api.log)"
  else
    err "API failed to start — check .kri-logs/api.log"
    exit 1
  fi
}

start_worker_local() {
  if is_running "worker"; then
    warn "Celery worker already running (pid $(cat "$PID_DIR/worker.pid"))"
    return
  fi
  echo "Starting Celery worker…"
  # shellcheck disable=SC1090
  source "$VENV"
  cd "$REPO_DIR"
  celery -A fleet_platform.workers.celery_app worker \
    --queues default,maintenance \
    --concurrency 2 \
    --loglevel info \
    > "$LOGS_DIR/worker.log" 2>&1 &
  echo $! > "$PID_DIR/worker.pid"
  sleep 2
  if is_running "worker"; then
    ok "Celery worker running (log: .kri-logs/worker.log)"
  else
    err "Celery worker failed to start — check .kri-logs/worker.log"
    exit 1
  fi
}

start_frontend_local() {
  if is_running "frontend"; then
    warn "Frontend already running (pid $(cat "$PID_DIR/frontend.pid"))"
    return
  fi
  echo "Starting frontend dev server…"
  cd "$FRONTEND_DIR"
  npm run dev -- --host 0.0.0.0 \
    > "$LOGS_DIR/frontend.log" 2>&1 &
  echo $! > "$PID_DIR/frontend.pid"
  sleep 3
  if is_running "frontend"; then
    ok "Frontend running on :5173 (log: .kri-logs/frontend.log)"
  else
    err "Frontend failed to start — check .kri-logs/frontend.log"
    exit 1
  fi
}

cmd_dev() {
  echo ""
  echo "  kri fleet management platform (dev mode)"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  start_infra_local
  start_backend_local
  start_worker_local
  start_frontend_local
  echo ""
  ok "kri dev is up →  http://localhost:5173"
  echo "   API     →  http://localhost:8000/docs"
  echo ""
}

cmd_dev_stop() {
  echo ""
  echo "  Stopping kri dev…"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  stop_local_service "frontend"
  stop_local_service "worker"
  stop_local_service "api"
  echo "  Stopping infrastructure…"
  docker compose -f "$COMPOSE_FILE" -f "$COMPOSE_DEV_OVERRIDE" stop db redis 2>&1 | tail -1
  ok "kri dev stopped"
  echo ""
}

# ── Test ──────────────────────────────────────────────────────────────────────

cmd_test() {
  echo ""
  echo "  kri E2E test suite"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  Requires kri to be running (./scripts/kri.sh start)"
  echo ""
  local filter="${2:-}"
  cd "$REPO_DIR"
  local PW="$REPO_DIR/frontend/node_modules/.bin/playwright"
  export NODE_PATH="$REPO_DIR/frontend/node_modules"
  if [[ -n "$filter" ]]; then
    "$PW" test --grep "$filter" --reporter=line 2>&1
  else
    "$PW" test --reporter=line 2>&1
  fi
}

# ── Dispatch ──────────────────────────────────────────────────────────────────

case "${1:-help}" in
  start)    cmd_start ;;
  stop)     cmd_stop ;;
  status)   cmd_status ;;
  restart)  cmd_restart ;;
  logs)     cmd_logs "$@" ;;
  dev)      cmd_dev ;;
  dev-stop) cmd_dev_stop ;;
  test)     cmd_test "$@" ;;
  *)
    echo "Usage: $(basename "$0") {start|stop|restart|status|logs [service]|dev|dev-stop|test [grep-pattern]}"
    echo ""
    echo "  start      — build and start all services in Docker"
    echo "  stop       — stop all Docker services"
    echo "  restart    — stop then start"
    echo "  status     — show Docker Compose service status"
    echo "  logs [svc] — tail logs for all or a specific service"
    echo "  dev        — local dev: host uvicorn + celery + vite (infra in Docker)"
    echo "  dev-stop   — stop local dev processes + infra"
    echo "  test       — run Playwright E2E suite against running stack"
    exit 1
    ;;
esac
