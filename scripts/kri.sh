#!/usr/bin/env bash
# kri — start/stop/status for the kri fleet management platform
# Usage: kri.sh [start|stop|status|restart|deploy|logs|seed|dev|dev-stop|test|rolling-deploy|rollback]

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO_DIR/.venv/bin/activate"
LOGS_DIR="$REPO_DIR/.kri-logs"
PID_DIR="$REPO_DIR/.kri-pids"
COMPOSE_FILE="$REPO_DIR/deploy/docker-compose.yml"
COMPOSE_DEV_OVERRIDE="$REPO_DIR/deploy/docker-compose.override.yml"
ENV_FILE="$REPO_DIR/.env.docker"
FRONTEND_DIR="$REPO_DIR/frontend"

mkdir -p "$LOGS_DIR" "$PID_DIR"

# Load .env.docker for compose variable interpolation (REDIS_PASSWORD, POSTGRES_PASSWORD, etc.)
# Services also receive it via env_file: but compose substitution needs it at parse time.
require_env_file() {
  if [[ ! -f "$ENV_FILE" ]]; then
    err ".env.docker not found at $ENV_FILE"
    echo "  Copy .env.docker.example to .env.docker and fill in the required values."
    exit 1
  fi
}

# Build the --env-file flag for docker compose commands that need interpolation
compose_env() { echo "--env-file $ENV_FILE"; }

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*"; }

# ── Docker Compose commands ───────────────────────────────────────────────────

cmd_start() {
  require_env_file
  echo ""
  echo "  kri fleet management platform"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  Starting all services via Docker Compose…"
  export APP_VERSION
  APP_VERSION=$(cat "$REPO_DIR/VERSION" 2>/dev/null || echo "0.0.0")
  docker compose -f "$COMPOSE_FILE" $(compose_env) up -d --build
  echo ""
  ok "kri is up →  http://localhost"
  echo "   API docs →  http://localhost/api/docs"
  echo ""
}

cmd_stop() {
  require_env_file
  echo ""
  echo "  Stopping kri…"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  docker compose -f "$COMPOSE_FILE" $(compose_env) down
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

# ── Test (unit / integration / e2e) ──────────────────────────────────────────

cmd_test() {
  local subcommand="${2:-e2e}"
  local filter="${3:-}"

  case "$subcommand" in
    unit)
      echo ""
      echo "  kri test unit"
      echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
      # shellcheck disable=SC1090
      source "$VENV"
      cd "$REPO_DIR"
      if [[ -n "$filter" ]]; then
        uv run pytest tests/unit/ -q -k "$filter"
      else
        uv run pytest tests/unit/ -q
      fi
      ;;
    integration)
      echo ""
      echo "  kri test integration"
      echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
      echo "  Requires running DB + Redis (kri dev or kri start)"
      echo ""
      # shellcheck disable=SC1090
      source "$VENV"
      cd "$REPO_DIR"
      if [[ -n "$filter" ]]; then
        uv run pytest tests/integration/ -q -k "$filter"
      else
        uv run pytest tests/integration/ -q
      fi
      ;;
    all)
      echo ""
      echo "  kri test all"
      echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
      # shellcheck disable=SC1090
      source "$VENV"
      cd "$REPO_DIR"
      uv run pytest tests/unit/ tests/integration/ -q
      ;;
    e2e|*)
      echo ""
      echo "  kri test e2e"
      echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
      echo "  Requires kri to be running (./scripts/kri.sh start)"
      echo ""
      cd "$REPO_DIR"
      local PW="$REPO_DIR/frontend/node_modules/.bin/playwright"
      export NODE_PATH="$REPO_DIR/frontend/node_modules"
      if [[ -n "$filter" ]]; then
        "$PW" test --grep "$filter" --reporter=line 2>&1
      else
        "$PW" test --reporter=line 2>&1
      fi
      ;;
  esac
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
  require_env_file
  echo "Starting infrastructure (postgres + redis)…"
  # Use override so db:5432 and redis:6379 are exposed to local processes
  docker compose -f "$COMPOSE_FILE" -f "$COMPOSE_DEV_OVERRIDE" $(compose_env) up -d db redis --quiet-pull 2>&1 | tail -2

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
    elapsed=$((elapsed + 1))
    retries=$((retries - 1))
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
  docker compose -f "$COMPOSE_FILE" -f "$COMPOSE_DEV_OVERRIDE" $(compose_env) stop db redis 2>&1 | tail -1
  ok "kri dev stopped"
  echo ""
}

# ── Rolling deploy + rollback ─────────────────────────────────────────────────

wait_for_healthy() {
  local svc="$1"
  local timeout="${2:-60}"
  local elapsed=0
  echo "  Waiting for $svc to become healthy…"
  while [[ $elapsed -lt $timeout ]]; do
    local health
    health=$(docker compose -f "$COMPOSE_FILE" ps --format json "$svc" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0].get('Health','') if isinstance(d,list) and d else d.get('Health',''))" 2>/dev/null || echo "unknown")
    if [[ "$health" == "healthy" ]]; then
      ok "$svc is healthy"
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done
  local state
  state=$(docker compose -f "$COMPOSE_FILE" ps --format json "$svc" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0].get('State','') if isinstance(d,list) and d else '')" 2>/dev/null || echo "")
  if [[ "$state" == "exited" || "$state" == "restarting" ]]; then
    err "$svc is in state '$state' — rolling deploy may be broken. Continuing…"
  else
    warn "$svc did not become healthy within ${timeout}s, continuing anyway…"
  fi
  return 0
}

cmd_rolling_deploy() {
  require_env_file
  echo ""
  echo "  kri rolling deploy (stateless services only)"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  local version
  version=$(cat "$REPO_DIR/VERSION" 2>/dev/null || echo "?")
  export APP_VERSION="$version"

  echo "  Tagging current images as :previous…"
  for svc in api worker beat frontend; do
    local img
    img=$(docker compose -f "$COMPOSE_FILE" $(compose_env) images --format json "$svc" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['Image'] if d else '')" 2>/dev/null || echo "")
    if [[ -n "$img" ]]; then
      docker tag "$img" "${img%:*}:previous" 2>/dev/null || true
    fi
  done

  echo "$version" > "$REPO_DIR/.kri-last-version"
  echo "  Building all services → v$version"
  docker compose -f "$COMPOSE_FILE" $(compose_env) build

  local services=("frontend" "beat" "worker" "api")
  for svc in "${services[@]}"; do
    echo ""
    echo "  Restarting $svc…"
    docker compose -f "$COMPOSE_FILE" $(compose_env) up -d --no-deps "$svc"
    wait_for_healthy "$svc" 60
  done

  echo ""
  ok "Rolling deploy complete v$version →  http://localhost"
  echo ""
}

cmd_rollback() {
  require_env_file
  echo ""
  echo "  kri rollback"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  local last_version
  if [[ -f "$REPO_DIR/.kri-last-version" ]]; then
    last_version=$(cat "$REPO_DIR/.kri-last-version" 2>/dev/null || echo "unknown")
    echo "  Rolling back to v$last_version…"
  else
    warn "No previous version found (.kri-last-version does not exist)"
    return 1
  fi

  local services=("frontend" "beat" "worker" "api")
  for svc in "${services[@]}"; do
    local img
    img=$(docker compose -f "$COMPOSE_FILE" $(compose_env) images --format json "$svc" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['Image'] if d else '')" 2>/dev/null || echo "")
    if [[ -z "$img" ]]; then
      warn "Could not find image for $svc, skipping…"
      continue
    fi
    local base_img="${img%:*}"
    local previous_img="${base_img}:previous"
    echo "  Restoring $svc from $previous_img…"
    if docker image inspect "$previous_img" >/dev/null 2>&1; then
      docker tag "$previous_img" "${base_img}:latest" 2>/dev/null || true
      docker compose -f "$COMPOSE_FILE" $(compose_env) up -d --no-deps "$svc"
      wait_for_healthy "$svc" 60
    else
      warn "Previous image $previous_img not found for $svc, skipping…"
    fi
  done

  echo ""
  ok "Rollback complete (back to v$last_version)"
  echo ""
}

# ── Deploy (full rebuild + restart) ──────────────────────────────────────────

cmd_deploy() {
  require_env_file
  local service="${2:-}"
  echo ""
  echo "  kri deploy${service:+ ($service)}"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  local version
  version=$(cat "$REPO_DIR/VERSION" 2>/dev/null || echo "?")
  export APP_VERSION="$version"

  if [[ -n "$service" ]]; then
    echo "  Building $service → v$version"
    docker compose -f "$COMPOSE_FILE" $(compose_env) build "$service"
    docker compose -f "$COMPOSE_FILE" $(compose_env) up -d "$service"
  else
    echo "  Building all services → v$version"
    docker compose -f "$COMPOSE_FILE" $(compose_env) build
    docker compose -f "$COMPOSE_FILE" $(compose_env) up -d
  fi

  echo ""
  ok "Deployed v$version →  http://localhost"
  echo ""
}

# ── Seed ──────────────────────────────────────────────────────────────────────

cmd_seed() {
  echo ""
  echo "  Seeding default users…"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  docker cp "$REPO_DIR/scripts/seed.py" deploy-api-1:/app/seed.py
  docker exec deploy-api-1 uv run python3 /app/seed.py
  echo ""
}

# ── Diagnose offline node ─────────────────────────────────────────────────────

cmd_diagnose() {
  local target="${2:-}"
  if [[ -z "$target" ]]; then
    err "Usage: $(basename "$0") diagnose <node-ip|minion-id>"
    exit 1
  fi

  echo ""
  echo "  kri diagnose — $target"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""

  # 1. Network reachability
  echo "  [1/4] Network reachability…"
  if ping -c 2 -W 2 "$target" >/dev/null 2>&1; then
    ok "  Host $target is reachable (ICMP)"
  else
    warn "  Host $target does not respond to ping — may be offline or ICMP blocked"
    echo "       Next step: verify the node is powered on and connected to the network"
  fi

  # 2. SSH port check
  echo ""
  echo "  [2/4] SSH port (22)…"
  if timeout 5 bash -c "</dev/tcp/$target/22" 2>/dev/null; then
    ok "  Port 22 is open on $target"
  else
    err "  Port 22 is closed or unreachable on $target"
    echo "       Next step: ensure SSH is enabled on the Mac Mini (System Settings → Sharing → Remote Login)"
  fi

  # 3. Salt master key status
  echo ""
  echo "  [3/4] Salt minion key status…"
  local salt_keys
  salt_keys=$(docker exec deploy-saltmaster-1 salt-key -L 2>/dev/null || echo "salt-master-unavailable")
  if [[ "$salt_keys" == "salt-master-unavailable" ]]; then
    warn "  Cannot reach salt-master container (is kri running?)"
  else
    local accepted rejected pending
    accepted=$(echo "$salt_keys" | grep -A999 "Accepted Keys:" | grep -B999 "Denied Keys:" | grep -v "Accepted Keys:\|Denied Keys:" | grep -c "$target" 2>/dev/null || echo 0)
    rejected=$(echo "$salt_keys" | grep -A999 "Rejected Keys:" | grep -c "$target" 2>/dev/null || echo 0)
    pending=$(echo "$salt_keys" | grep -A999 "Unaccepted Keys:" | grep -B999 "Rejected Keys:" | grep -v "Unaccepted Keys:\|Rejected Keys:" | grep -c "$target" 2>/dev/null || echo 0)

    if [[ "$accepted" -gt 0 ]]; then
      ok "  Minion key for $target is ACCEPTED"
    elif [[ "$pending" -gt 0 ]]; then
      warn "  Minion key for $target is PENDING acceptance"
      echo "       Next step: run:  docker exec deploy-saltmaster-1 salt-key -A -y"
    elif [[ "$rejected" -gt 0 ]]; then
      err "  Minion key for $target is REJECTED"
      echo "       Next step: delete rejected key and re-bootstrap:"
      echo "         docker exec deploy-saltmaster-1 salt-key -d $target -y"
    else
      warn "  No salt key found for $target — minion may not have connected yet"
      echo "       Next step: trigger a bootstrap from the kri UI (Fleet → node → Bootstrap)"
    fi
  fi

  # 4. kri API node status
  echo ""
  echo "  [4/4] kri API node record…"
  local api_up
  api_up=$(curl -sf http://localhost:8000/health/ready 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print('ok' if d.get('status')=='ok' else 'err')" 2>/dev/null || echo "unreachable")
  if [[ "$api_up" == "unreachable" ]]; then
    warn "  kri API not reachable at localhost:8000 — is kri running?"
  else
    local nodes_json
    nodes_json=$(curl -sf "http://localhost:8000/api/v1/fleet/nodes?per_page=200" \
      -H "Authorization: Bearer $(cat "$REPO_DIR/.kri-token" 2>/dev/null || echo '')" 2>/dev/null || echo "")
    if [[ -z "$nodes_json" ]]; then
      warn "  Could not fetch node list (no token? run: kri.sh token)"
    else
      local node_status
      node_status=$(echo "$nodes_json" | python3 -c "
import sys,json
nodes = json.load(sys.stdin).get('items',[])
match = [n for n in nodes if n.get('bootstrap_ip')=='$target' or n.get('minion_id')=='$target' or n.get('hostname','').startswith('$target')]
if match:
    n = match[0]
    print(f'  Node: {n.get(\"minion_id\",\"?\")} | status={n.get(\"status\",\"?\")} | bootstrap={n.get(\"bootstrap_status\",\"?\")}')
    if n.get('bootstrap_error'):
        print(f'  Last error: {n[\"bootstrap_error\"][:120]}')
else:
    print('  NOT_FOUND')
" 2>/dev/null || echo "  parse-error")
      if [[ "$node_status" == "  NOT_FOUND" ]]; then
        warn "  Node $target not found in kri database"
        echo "       Next step: add the node via Fleet → Add Node"
      else
        echo "$node_status"
      fi
    fi
  fi

  echo ""
  echo "  ── Re-bootstrap steps ──────────────────────────────────────────────"
  echo "  1. Ensure node is reachable (steps 1–2 above)"
  echo "  2. Accept/delete salt key if needed (step 3 above)"
  echo "  3. In kri UI: Fleet → select node → Bootstrap tab → Run Bootstrap"
  echo "  4. Or via API:"
  echo "     curl -X POST http://localhost:8000/api/v1/ansible/bootstrap/<node_id>"
  echo "          -H 'Authorization: Bearer <token>'"
  echo ""
}

# ── PKI management ───────────────────────────────────────────────────────────
# Salt-master keys live in deploy/salt-pki/ (bind mount, not Docker volume).
# They MUST NOT change after minions are deployed — changing them disconnects
# every minion until they are manually re-keyed.
#
# pki-init:   Generate keys on first deploy (before `kri start`)
# pki-backup: Print vault-encrypt commands for disaster recovery

PKI_DIR="$REPO_DIR/deploy/salt-pki"

cmd_pki_init() {
  echo ""
  echo "  kri pki-init — generate salt-master keys"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  if [[ -f "$PKI_DIR/master.pem" ]]; then
    err "Keys already exist in $PKI_DIR/master.pem"
    echo "  If you intended to rotate keys, first back up the old keys,"
    echo "  then re-bootstrap ALL minions after rotation."
    echo "  Rotating unexpectedly disconnects the entire fleet."
    exit 1
  fi

  mkdir -p "$PKI_DIR/minions" "$PKI_DIR/minions_pre" \
           "$PKI_DIR/minions_denied" "$PKI_DIR/minions_autosign" \
           "$PKI_DIR/minions_rejected"

  echo "  Generating 4096-bit RSA key pair…"
  openssl genrsa -out "$PKI_DIR/master.pem" 4096 2>/dev/null
  openssl rsa -in "$PKI_DIR/master.pem" -pubout -out "$PKI_DIR/master.pub" 2>/dev/null
  chmod 600 "$PKI_DIR/master.pem"
  chmod 644 "$PKI_DIR/master.pub"

  ok "Keys written to deploy/salt-pki/"
  echo ""
  warn "IMPORTANT: Back up master.pem immediately — run:  ./scripts/kri.sh pki-backup"
  echo ""
  echo "  Also set salt_master_pub_key in playbooks/host_vars/<minion>.yml:"
  echo ""
  cat "$PKI_DIR/master.pub"
  echo ""
}

cmd_pki_push() {
  # M-1 fix: salt 3008 rotates its RSA key on every container startup (by design).
  # This command pushes the CURRENT master.pub to all known minions so they can
  # reconnect. Must be run after every `kri deploy salt-master` or `kri restart`.
  #
  # Usage: kri pki-push [<minion-ip> ...]
  #   No args:  reads minion IPs from docker exec salt-key -L
  #   With IPs: pushes to specified hosts only
  echo ""
  echo "  kri pki-push — push current master.pub to all minions"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  # Get current master.pub from running container
  local MASTER_PUB
  MASTER_PUB=$(docker exec deploy-salt-master-1 cat /etc/salt/pki/master/master.pub 2>/dev/null)
  if [[ -z "$MASTER_PUB" ]]; then
    err "Cannot read master.pub from salt-master container — is it running?"
    exit 1
  fi
  ok "Got master.pub (fingerprint: $(echo "$MASTER_PUB" | openssl pkey -pubin -noout -text 2>/dev/null | grep -i "key\|bit" | head -1 || echo "ok"))"

  # Collect target IPs: args or from salt-key accepted list
  local TARGETS=("${@:2}")  # args after 'pki-push'
  if [[ ${#TARGETS[@]} -eq 0 ]]; then
    # Read accepted minion keys and get their IPs from DB via API
    echo "  No IPs specified — reading from salt accepted keys + node DB…"
    # Get IPs via direct DB query (requires kri to be running)
    local DB_IPS
    DB_IPS=$(docker exec deploy-db-1 psql -U fleet -d fleet_demo -t -c \
      "SELECT bootstrap_ip FROM nodes WHERE bootstrap_ip IS NOT NULL AND minion_id IN \
       (SELECT name FROM (SELECT unnest(string_to_array(accepted_keys, ',')) AS name FROM \
       (SELECT string_agg(f.relname::text, ',') AS accepted_keys FROM \
        pg_class f WHERE f.relname = 'nodes') x) y) UNION \
       SELECT bootstrap_ip FROM nodes WHERE bootstrap_ip IS NOT NULL;" \
      2>/dev/null | tr -d ' ' | grep -v '^$' || true)

    # Simpler: just get all node IPs
    DB_IPS=$(docker exec deploy-db-1 psql -U fleet -d fleet_demo -t -c \
      "SELECT bootstrap_ip FROM nodes WHERE bootstrap_ip IS NOT NULL;" \
      2>/dev/null | tr -d ' ' | grep -v '^$' || true)

    if [[ -z "$DB_IPS" ]]; then
      err "No node IPs found in DB — specify IPs manually: kri pki-push <ip1> <ip2>"
      exit 1
    fi
    mapfile -t TARGETS <<< "$DB_IPS"
  fi

  echo "  Pushing to ${#TARGETS[@]} host(s)…"
  echo "$MASTER_PUB" > /tmp/kri_master_push.pub

  local ok_count=0
  local fail_count=0
  for ip in "${TARGETS[@]}"; do
    [[ -z "$ip" ]] && continue
    echo -n "  → $ip … "
    if scp -q -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
        /tmp/kri_master_push.pub "${ip}:/tmp/kri_master_push.pub" 2>/dev/null && \
       ssh -q -o StrictHostKeyChecking=no -o ConnectTimeout=5 "$ip" \
        "sudo cp /tmp/kri_master_push.pub /etc/salt/pki/minion/minion_master.pub && \
         sudo chmod 644 /etc/salt/pki/minion/minion_master.pub && \
         sudo launchctl stop com.saltstack.salt.minion 2>/dev/null; sleep 2; \
         sudo launchctl start com.saltstack.salt.minion 2>/dev/null" 2>/dev/null; then
      ok "done"
      ok_count=$((ok_count + 1))
    else
      warn "unreachable or SSH failed (push manually)"
      fail_count=$((fail_count + 1))
    fi
  done
  rm -f /tmp/kri_master_push.pub

  echo ""
  ok "$ok_count host(s) updated"
  [[ $fail_count -gt 0 ]] && warn "$fail_count host(s) unreachable — push manually"
  echo ""
  echo "  Waiting 15s for minions to reconnect, then triggering grain report…"
  sleep 15
  docker exec deploy-salt-master-1 salt '*' state.apply base.grain_report \
    --timeout=60 --async 2>/dev/null && \
  ok "Grain report queued — nodes should appear online in ~30s" || \
  warn "Grain report queue failed — run manually after minions reconnect"
  echo ""
}

cmd_pki_backup() {
  echo ""
  echo "  kri pki-backup — print ansible-vault backup commands"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  if [[ ! -f "$PKI_DIR/master.pem" ]]; then
    err "No keys found in $PKI_DIR/master.pem — run:  ./scripts/kri.sh pki-init"
    exit 1
  fi

  echo "  Run these commands to store the master key in ansible vault:"
  echo ""
  echo "    ansible-vault encrypt_string \\"
  echo "      --stdin-name salt_master_pem \\"
  echo "      < deploy/salt-pki/master.pem \\"
  echo "      >> playbooks/host_vars/vault.yml"
  echo ""
  echo "  master.pub (add to playbooks/group_vars/all.yml as salt_master_pub_key):"
  echo ""
  cat "$PKI_DIR/master.pub"
  echo ""
  ok "Back up master.pem — anyone with it can impersonate the salt-master"
}

# ── Dispatch ──────────────────────────────────────────────────────────────────

case "${1:-help}" in
  start)          cmd_start ;;
  stop)           cmd_stop ;;
  status)         cmd_status ;;
  restart)        cmd_restart ;;
  deploy)         cmd_deploy "$@" ;;
  rolling-deploy) cmd_rolling_deploy ;;
  rollback)       cmd_rollback ;;
  logs)           cmd_logs "$@" ;;
  seed)           cmd_seed ;;
  dev)            cmd_dev ;;
  dev-stop)       cmd_dev_stop ;;
  test)           cmd_test "$@" ;;
  diagnose)       cmd_diagnose "$@" ;;
  pki-init)       cmd_pki_init ;;
  pki-backup)     cmd_pki_backup ;;
  pki-push)       cmd_pki_push "$@" ;;
  *)
    echo "Usage: $(basename "$0") {start|stop|restart|status|deploy [svc]|logs [svc]|seed|dev|dev-stop|test [unit|integration|all|e2e] [filter]}"
    echo ""
    echo "  start                        — build and start all services in Docker"
    echo "  stop                         — stop all Docker services"
    echo "  restart                      — stop then start"
    echo "  status                       — show Docker Compose service status"
    echo "  deploy                       — rebuild ALL images and redeploy (stamps version)"
    echo "  deploy <svc>                 — rebuild one service (api|worker|frontend|salt-master)"
    echo "  rolling-deploy               — zero-downtime rolling restart (stateless services only)"
    echo "  rollback                     — restore :previous images and restart stateless services"
    echo "  logs [svc]                   — tail logs for all or a specific service"
    echo "  seed                         — create default users (admin@fleet.local / changeme)"
    echo "  dev                          — local dev: host uvicorn + celery + vite (infra in Docker)"
    echo "  dev-stop                     — stop local dev processes + infra"
    echo "  test unit [filter]           — run pytest tests/unit/ (optionally filtered)"
    echo "  test integration [filter]    — run pytest tests/integration/ (needs DB + Redis)"
    echo "  test all                     — run unit + integration"
    echo "  test e2e [grep]              — run Playwright E2E suite (needs kri running)"
    echo "  test [grep]                  — alias for test e2e [grep]"
    echo "  diagnose <ip|minion-id>      — check network, SSH, salt key, and kri status for an offline node"
    echo "  pki-init                     — generate salt-master RSA keys (first deploy only)"
    echo "  pki-backup                   — print ansible-vault commands to back up master.pem"
  echo "  pki-push [ip ...]            — push current master.pub to minions after salt-master restart"
    exit 1
    ;;
esac
