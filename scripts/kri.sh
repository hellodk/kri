#!/usr/bin/env bash
# kri — start/stop/status for the kri fleet management platform
# Usage: kri.sh [start|stop|status|restart|logs]

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO_DIR/.venv/bin/activate"
LOGS_DIR="$REPO_DIR/.kri-logs"
PID_DIR="$REPO_DIR/.kri-pids"
COMPOSE_FILE="$REPO_DIR/deploy/docker-compose.yml"
FRONTEND_DIR="$REPO_DIR/frontend"

mkdir -p "$LOGS_DIR" "$PID_DIR"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*"; }

is_running() {
  local pid_file="$PID_DIR/$1.pid"
  [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

stop_service() {
  local name="$1"
  local pid_file="$PID_DIR/$name.pid"
  if is_running "$name"; then
    kill "$(cat "$pid_file")" 2>/dev/null && ok "Stopped $name" || warn "Could not stop $name"
    rm -f "$pid_file"
  else
    warn "$name was not running"
  fi
}

start_infra() {
  echo "Starting infrastructure (postgres + redis)…"
  docker compose -f "$COMPOSE_FILE" up -d --quiet-pull 2>&1 | tail -2

  # Wait for healthy
  local retries=20
  while [[ $retries -gt 0 ]]; do
    local pg_health
    pg_health=$(docker inspect deploy-postgres-1 --format '{{.State.Health.Status}}' 2>/dev/null || echo "missing")
    local redis_health
    redis_health=$(docker inspect deploy-redis-1 --format '{{.State.Health.Status}}' 2>/dev/null || echo "missing")
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

start_backend() {
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

start_worker() {
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

start_frontend() {
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

cmd_start() {
  echo ""
  echo "  kri fleet management platform"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  start_infra
  start_backend
  start_worker
  start_frontend
  echo ""
  ok "kri is up →  http://localhost:5173"
  echo "   API     →  http://localhost:8000/docs"
  echo ""
}

cmd_stop() {
  echo ""
  echo "  Stopping kri…"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  stop_service "frontend"
  stop_service "worker"
  stop_service "api"
  echo "  Stopping infrastructure…"
  docker compose -f "$COMPOSE_FILE" stop 2>&1 | tail -1
  ok "kri stopped"
  echo ""
}

cmd_status() {
  echo ""
  echo "  kri status"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  for svc in api worker frontend; do
    if is_running "$svc"; then
      ok "$svc  (pid $(cat "$PID_DIR/$svc.pid"))"
    else
      err "$svc  (not running)"
    fi
  done
  echo ""
  docker compose -f "$COMPOSE_FILE" ps 2>/dev/null | tail -n +2 | while read -r line; do
    if echo "$line" | grep -q "healthy"; then
      ok "$line"
    else
      warn "$line"
    fi
  done
  echo ""
}

cmd_logs() {
  local svc="${2:-api}"
  local log_file="$LOGS_DIR/$svc.log"
  if [[ -f "$log_file" ]]; then
    tail -f "$log_file"
  else
    err "No log file for '$svc'. Available: api, worker, frontend"
    exit 1
  fi
}

cmd_restart() {
  cmd_stop
  sleep 1
  cmd_start
}

cmd_test() {
  echo ""
  echo "  kri E2E test suite"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  Requires kri to be running (./scripts/kri.sh start)"
  echo ""
  local filter="${2:-}"
  cd "$REPO_DIR"
  if [[ -n "$filter" ]]; then
    npx playwright test --grep "$filter" --reporter=line 2>&1
  else
    npx playwright test --reporter=line 2>&1
  fi
}

case "${1:-help}" in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  status)  cmd_status ;;
  restart) cmd_restart ;;
  logs)    cmd_logs "$@" ;;
  test)    cmd_test "$@" ;;
  *)
    echo "Usage: $(basename "$0") {start|stop|restart|status|logs [api|worker|frontend]|test [grep-pattern]}"
    exit 1
    ;;
esac
