#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# kri — Mac Mini Fleet Management Platform CLI
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Colors ─────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

info()    { echo -e "${BLUE}[info]${NC}  $*"; }
success() { echo -e "${GREEN}[ok]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[warn]${NC}  $*"; }
error()   { echo -e "${RED}[error]${NC} $*"; exit 1; }
header()  { echo -e "\n${BOLD}${CYAN}$*${NC}\n"; }

# ── Interactive helpers ────────────────────────────────────────────────────────
PROMPT_RESULT=""

_prompt_select() {
    local prompt="$1"; shift
    local options=("$@")
    echo -e "\n${BOLD}${prompt}${NC}"
    for i in "${!options[@]}"; do
        echo -e "  ${CYAN}$((i+1)))${NC} ${options[$i]}"
    done
    local choice
    while true; do
        echo -en "${DIM}  Select [1-${#options[@]}]:${NC} "
        read -r choice </dev/tty || true
        if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#options[@]} )); then
            echo -e "  ${GREEN}→${NC} ${options[$((choice-1))]}"
            PROMPT_RESULT="${options[$((choice-1))]}"
            return
        fi
        echo -e "  ${RED}Invalid. Try again.${NC}"
    done
}

_prompt_input() {
    local prompt="$1"
    local default="${2:-}"
    local value
    if [[ -n "$default" ]]; then
        echo -en "${DIM}  ${prompt} [${default}]:${NC} "
    else
        echo -en "${DIM}  ${prompt}:${NC} "
    fi
    read -r value </dev/tty || true
    PROMPT_RESULT="${value:-$default}"
}

prompt_confirm() {
    local prompt="$1"
    local reply
    echo -en "${BOLD}  ${prompt} (y/N):${NC} "
    read -r reply </dev/tty || true
    [[ "$reply" =~ ^[Yy]$ ]]
}

# ── Paths & helpers ────────────────────────────────────────────────────────────
COMPOSE_FILE="$REPO_DIR/deploy/docker-compose.yml"
ENV_FILE="$REPO_DIR/.env.docker"
PKI_DIR="$REPO_DIR/deploy/salt-pki"
VENV="$REPO_DIR/.venv/bin/activate"
FRONTEND_DIR="$REPO_DIR/frontend"

version() { cat "$REPO_DIR/VERSION" 2>/dev/null || echo "unknown"; }

require_env() {
    if [[ ! -f "$ENV_FILE" ]]; then
        error ".env.docker not found at $ENV_FILE — copy .env.docker.example and fill in values"
    fi
}

compose() {
    docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" "$@"
}

# ══════════════════════════════════════════════════════════════════════════════
# UP / DOWN / RESTART / STATUS / LOGS
# ══════════════════════════════════════════════════════════════════════════════

_pki_push_after_salt_restart() {
    # No-op: salt-master now runs natively on mm1 (not in Docker).
    # Keys are stable — no rotation on deploy. pki push only needed after
    # mm1 reboot or explicit salt-master restart on mm1.
    # Kept for backward compat if someone runs kri against a Docker salt-master.
    local salt_restarted="${1:-false}"
    [[ "$salt_restarted" != "true" ]] && return
    info "Salt-master runs on mm1 — no pki push needed on Docker deploy"
}

cmd_up() {
    require_env
    header "Starting kri v$(version)"
    local svc="${1:-}"
    local salt_restarted=false
    export APP_VERSION
    APP_VERSION=$(version)
    if [[ -n "$svc" ]]; then
        info "Building and starting: $svc"
        [[ "$svc" == "salt-master" ]] && salt_restarted=true
        compose up -d --build "$svc"
    else
        info "Building and starting all services…"
        compose up -d --build
        salt_restarted=true  # full up always restarts salt-master
    fi
    success "kri is up → http://localhost"
    info "API docs → http://localhost/api/docs"
    _pki_push_after_salt_restart "$salt_restarted"
}

cmd_down() {
    require_env
    header "Stopping kri"
    compose down
    success "All services stopped"
}

cmd_restart() {
    cmd_down
    cmd_up "$@"
}

cmd_status() {
    require_env
    header "kri service status"
    compose ps
}

cmd_logs() {
    require_env
    local svc="${1:-}"
    if [[ -n "$svc" ]]; then
        compose logs -f "$svc"
    else
        compose logs -f
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
# DEPLOY / ROLLING-DEPLOY / ROLLBACK
# ══════════════════════════════════════════════════════════════════════════════

_wait_healthy() {
    local svc="$1"
    local timeout="${2:-60}"
    local elapsed=0
    info "Waiting for $svc to become healthy…"
    while [[ $elapsed -lt $timeout ]]; do
        local health
        health=$(compose ps --format json "$svc" 2>/dev/null \
            | python3 -c "import sys,json; d=json.load(sys.stdin); \
              print(d[0].get('Health','') if isinstance(d,list) and d else d.get('Health',''))" \
            2>/dev/null || echo "unknown")
        if [[ "$health" == "healthy" ]]; then
            success "$svc is healthy"
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    warn "$svc did not become healthy within ${timeout}s"
    return 0
}

cmd_deploy() {
    require_env
    local sub="${1:-}"
    shift 2>/dev/null || true

    if [[ -z "$sub" ]]; then
        _prompt_select "Deploy what?" \
            "full (rebuild everything)" \
            "api" "worker" "frontend" "salt-master" "beat"
        sub="$PROMPT_RESULT"
    fi

    export APP_VERSION
    APP_VERSION=$(version)
    header "Deploying → v${APP_VERSION}"

    case "$sub" in
        "full (rebuild everything)"|full)
            info "Building all services…"
            compose build
            compose up -d
            success "Full deploy complete → v${APP_VERSION}"
            _pki_push_after_salt_restart true
            ;;
        salt-master)
            info "Building salt-master…"
            compose build salt-master
            compose up -d salt-master
            _wait_healthy salt-master
            success "Deployed salt-master → v${APP_VERSION}"
            _pki_push_after_salt_restart true
            ;;
        api|worker|frontend|beat)
            info "Building $sub…"
            compose build "$sub"
            compose up -d "$sub"
            _wait_healthy "$sub"
            success "Deployed $sub → v${APP_VERSION}"
            ;;
        *)
            info "Deploying specific service: $sub"
            compose build "$sub"
            compose up -d "$sub"
            success "Done"
            ;;
    esac
}

cmd_rolling_deploy() {
    require_env
    header "Rolling deploy (zero-downtime)"
    export APP_VERSION
    APP_VERSION=$(version)

    info "Tagging current images as :previous…"
    for svc in api worker beat frontend; do
        local img
        img=$(compose images --format json "$svc" 2>/dev/null \
            | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['Image'] if d else '')" \
            2>/dev/null || echo "")
        [[ -n "$img" ]] && docker tag "$img" "${img%:*}:previous" 2>/dev/null || true
    done

    echo "${APP_VERSION}" > "$REPO_DIR/.kri-last-version"
    info "Building all → v${APP_VERSION}"
    compose build

    for svc in frontend beat worker api; do
        info "Restarting $svc…"
        compose up -d --no-deps "$svc"
        _wait_healthy "$svc" 60
    done
    success "Rolling deploy complete → v${APP_VERSION} → http://localhost"
    # Rolling deploy does NOT restart salt-master — skip pki push
}

cmd_rollback() {
    require_env
    header "Rolling back"
    local last_version
    last_version=$(cat "$REPO_DIR/.kri-last-version" 2>/dev/null || echo "unknown")
    [[ "$last_version" == "unknown" ]] && error "No previous version found (.kri-last-version missing)"
    info "Rolling back to v${last_version}…"
    for svc in frontend beat worker api; do
        local img
        img=$(compose images --format json "$svc" 2>/dev/null \
            | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['Image'] if d else '')" \
            2>/dev/null || echo "")
        if [[ -n "$img" ]]; then
            local prev="${img%:*}:previous"
            if docker image inspect "$prev" >/dev/null 2>&1; then
                info "Restoring $svc from $prev…"
                docker tag "$prev" "${img%:*}:latest" 2>/dev/null || true
                compose up -d --no-deps "$svc"
                _wait_healthy "$svc" 60
            else
                warn "No :previous image for $svc — skipping"
            fi
        fi
    done
    success "Rollback complete (back to v${last_version})"
}

# ══════════════════════════════════════════════════════════════════════════════
# INFRA — destroy, recreate, reset
# ══════════════════════════════════════════════════════════════════════════════

cmd_infra() {
    local sub="${1:-}"
    shift 2>/dev/null || true

    if [[ -z "$sub" ]]; then
        _prompt_select "Infrastructure operation:" \
            "status    — show containers, volumes, images" \
            "destroy   — stop + remove containers (keeps volumes)" \
            "recreate  — destroy + rebuild + restart everything" \
            "reset     — WIPE all data (volumes) + rebuild fresh" \
            "prune     — remove unused Docker resources"
        sub="${PROMPT_RESULT%% *}"
    fi

    case "$sub" in
        status)   cmd_infra_status ;;
        destroy)  cmd_infra_destroy ;;
        recreate) cmd_infra_recreate ;;
        reset)    cmd_infra_reset ;;
        prune)    cmd_infra_prune ;;
        *) error "Unknown infra subcommand: $sub" ;;
    esac
}

cmd_infra_status() {
    header "Infrastructure status"

    info "Containers (Docker):"
    docker ps --format "  {{.Names}}  {{.Status}}  {{.Ports}}" | grep -E "deploy-|kri" 2>/dev/null || echo "  (none running)"
    # Warn about orphan salt-master container (removed from compose but may still run)
    if docker ps --format "{{.Names}}" | grep -q "salt-master"; then
        warn "  deploy-salt-master-1 is running as an orphan (removed from compose)"
        warn "  Run 'kri infra destroy' to remove it, or: docker rm -f deploy-salt-master-1"
    fi
    echo ""

    info "External services (not managed by Docker):"
    echo -e "  ${CYAN}salt-master${NC}  mm1 (100.102.68.75) — native launchd service"
    local sm_status
    sm_status=$(ssh -o ConnectTimeout=3 -o StrictHostKeyChecking=no 100.102.68.75 \
        "sudo launchctl list com.saltstack.salt.master 2>/dev/null | grep PID | awk '{print \$3}'" 2>/dev/null || echo "")
    if [[ -n "$sm_status" && "$sm_status" != "-" ]]; then
        echo -e "    ${GREEN}[ok]${NC}    running (PID $sm_status)"
    else
        echo -e "    ${YELLOW}[warn]${NC}  not running or unreachable"
    fi
    echo ""

    info "Volumes:"
    docker volume ls --format "  {{.Name}}" | grep -E "deploy_|kri" 2>/dev/null || echo "  (none)"
    echo ""

    info "Images:"
    docker images --format "  {{.Repository}}:{{.Tag}}  {{.Size}}" \
        | grep -E "deploy-|hellodk/kri|deploy-api|deploy-worker|deploy-frontend|deploy-beat" \
        2>/dev/null || echo "  (none)"
}

cmd_infra_destroy() {
    require_env
    header "Destroying containers"
    warn "This stops and removes all kri Docker containers. Volumes (data) are preserved."
    warn "Salt-master on mm1 is NOT affected."
    prompt_confirm "Proceed?" || { info "Cancelled."; return; }
    compose down --remove-orphans   # --remove-orphans cleans up old salt-master container too
    success "All containers removed. Volumes preserved."
    info "Run 'kri up' to restart."
}

cmd_infra_recreate() {
    require_env
    header "Recreating infrastructure"
    warn "This destroys all Docker containers and rebuilds them from scratch."
    warn "Volumes (database, redis data) are preserved."
    warn "Salt-master on mm1 is NOT touched."
    prompt_confirm "Proceed?" || { info "Cancelled."; return; }
    info "Stopping and removing containers (including orphans)…"
    compose down --remove-orphans
    info "Rebuilding all images…"
    export APP_VERSION
    APP_VERSION=$(version)
    compose build --no-cache
    info "Starting services…"
    compose up -d
    success "Infrastructure recreated → v${APP_VERSION} → http://localhost"
    info "Salt-master on mm1 continues running — no pki push needed."
}

cmd_infra_reset() {
    require_env
    header "Full infrastructure reset"
    echo -e "${RED}${BOLD}  ⚠  WARNING: This WIPES ALL DATA${NC}"
    echo -e "${RED}     • PostgreSQL database (all fleet data)${NC}"
    echo -e "${RED}     • Redis (all queues, sessions)${NC}"
    echo -e "${RED}     • All Docker volumes${NC}"
    echo -e "${RED}     Salt-master on mm1 is NOT wiped (pillar data preserved there).${NC}"
    echo -e "${RED}     This cannot be undone.${NC}\n"
    prompt_confirm "Are you absolutely sure?" || { info "Cancelled."; return; }

    local confirm
    echo -en "${RED}${BOLD}  Type 'wipe' to confirm:${NC} "
    read -r confirm </dev/tty || true
    if [[ "$confirm" != "wipe" ]]; then
        info "Cancelled — 'wipe' not entered."
        return
    fi

    info "Stopping all containers (including orphans)…"
    compose down --remove-orphans

    info "Removing volumes…"
    local project_name
    project_name=$(basename "$(dirname "$COMPOSE_FILE")")
    # Remove current volumes
    docker volume rm "${project_name}_pgdata" "${project_name}_redisdata" \
        "${project_name}_pgbackups" 2>/dev/null || true
    # Remove legacy salt volumes (may exist from pre-mm1 setup)
    docker volume rm "${project_name}_salt-pillar" "${project_name}_salt-master-pki" 2>/dev/null || true

    warn "All data wiped."
    info "Rebuilding from scratch…"
    export APP_VERSION
    APP_VERSION=$(version)
    compose build --no-cache
    compose up -d
    echo ""
    success "Fresh infrastructure started → v${APP_VERSION}"
    info "Run 'kri seed' to create default users."
    _pki_push_after_salt_restart true
}

cmd_infra_prune() {
    header "Docker prune"
    warn "Removes stopped containers, unused networks, dangling images."
    prompt_confirm "Proceed?" || { info "Cancelled."; return; }
    docker system prune -f
    success "Docker cleanup done"
}

# ══════════════════════════════════════════════════════════════════════════════
# TEST
# ══════════════════════════════════════════════════════════════════════════════

cmd_test() {
    local sub="${1:-}"
    shift 2>/dev/null || true

    if [[ -z "$sub" ]]; then
        _prompt_select "What would you like to test?" \
            "unit" "integration" "all" "e2e"
        sub="$PROMPT_RESULT"
    fi

    case "$sub" in
        unit)        cmd_test_unit "$@" ;;
        integration) cmd_test_integration "$@" ;;
        all)         cmd_test_all "$@" ;;
        e2e)         cmd_test_e2e "$@" ;;
        *)           error "Unknown test type: $sub" ;;
    esac
}

cmd_test_unit() {
    header "Unit tests"
    local filter="${1:-}"
    # shellcheck disable=SC1090
    source "$VENV"
    cd "$REPO_DIR"
    if [[ -n "$filter" ]]; then
        info "Filter: $filter"
        uv run pytest tests/unit/ -q -k "$filter"
    else
        uv run pytest tests/unit/ -q
    fi
}

cmd_test_integration() {
    header "Integration tests"
    info "Requires running DB + Redis (kri up first)"
    local filter="${1:-}"
    # shellcheck disable=SC1090
    source "$VENV"
    cd "$REPO_DIR"
    if [[ -n "$filter" ]]; then
        uv run pytest tests/integration/ -q -k "$filter"
    else
        uv run pytest tests/integration/ -q
    fi
}

cmd_test_all() {
    header "Full test suite (unit + integration)"
    # shellcheck disable=SC1090
    source "$VENV"
    cd "$REPO_DIR"
    uv run pytest tests/unit/ tests/integration/ -q
}

cmd_test_e2e() {
    header "E2E tests (Playwright)"
    local filter="${1:-}"
    info "Requires kri running at http://localhost"
    local PW="$FRONTEND_DIR/node_modules/.bin/playwright"
    if [[ -n "$filter" ]]; then
        "$PW" test --grep "$filter" --reporter=line 2>&1
    else
        "$PW" test --reporter=line 2>&1
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
# PKI
# ══════════════════════════════════════════════════════════════════════════════

cmd_pki() {
    local sub="${1:-}"
    shift 2>/dev/null || true

    if [[ -z "$sub" ]]; then
        _prompt_select "PKI operation:" \
            "init   — generate salt-master RSA keys (first deploy only)" \
            "backup — print ansible-vault commands to back up master.pem" \
            "push   — push current master.pub to minions after restart"
        sub="${PROMPT_RESULT%% *}"
    fi

    case "$sub" in
        init)   cmd_pki_init ;;
        backup) cmd_pki_backup ;;
        push)   cmd_pki_push "$@" ;;
        *)      error "Unknown pki subcommand: $sub" ;;
    esac
}

cmd_pki_init() {
    header "Generate salt-master PKI keys"
    if [[ -f "$PKI_DIR/master.pem" ]]; then
        error "Keys already exist in $PKI_DIR/master.pem — rotating keys disconnects all minions"
    fi
    mkdir -p "$PKI_DIR/minions" "$PKI_DIR/minions_pre" \
             "$PKI_DIR/minions_denied" "$PKI_DIR/minions_autosign" \
             "$PKI_DIR/minions_rejected"
    info "Generating 4096-bit RSA key pair…"
    openssl genrsa -out "$PKI_DIR/master.pem" 4096 2>/dev/null
    openssl rsa -in "$PKI_DIR/master.pem" -pubout -out "$PKI_DIR/master.pub" 2>/dev/null
    chmod 600 "$PKI_DIR/master.pem"
    chmod 644 "$PKI_DIR/master.pub"
    success "Keys written to deploy/salt-pki/"
    warn "Back up master.pem: kri pki backup"
}

cmd_pki_backup() {
    header "PKI backup instructions"
    [[ ! -f "$PKI_DIR/master.pem" ]] && error "No keys found — run: kri pki init"
    info "Run these commands to store the master key in ansible vault:"
    echo ""
    echo "  ansible-vault encrypt_string \\"
    echo "    --stdin-name salt_master_pem \\"
    echo "    < deploy/salt-pki/master.pem \\"
    echo "    >> playbooks/host_vars/vault.yml"
    echo ""
    info "master.pub (set in playbooks/group_vars/all.yml as salt_master_pub_key):"
    echo ""
    cat "$PKI_DIR/master.pub"
}

cmd_pki_push() {
    header "Push master.pub to minions"
    local MASTER_PUB
    MASTER_PUB=$(docker exec deploy-salt-master-1 cat /etc/salt/pki/master/master.pub 2>/dev/null)
    [[ -z "$MASTER_PUB" ]] && error "Cannot read master.pub — is salt-master running?"
    success "Got master.pub"

    local TARGETS=("${@}")
    if [[ ${#TARGETS[@]} -eq 0 ]]; then
        info "Reading node IPs from DB…"
        mapfile -t TARGETS < <(docker exec deploy-db-1 psql -U fleet -d fleet_demo -t -c \
            "SELECT bootstrap_ip FROM nodes WHERE bootstrap_ip IS NOT NULL;" \
            2>/dev/null | tr -d ' ' | grep -v '^$' || true)
    fi

    [[ ${#TARGETS[@]} -eq 0 ]] && error "No node IPs found — specify IPs: kri pki push <ip1> <ip2>"
    info "Pushing to ${#TARGETS[@]} host(s)…"
    echo "$MASTER_PUB" > /tmp/kri_master_push.pub

    local ok_count=0 fail_count=0
    for ip in "${TARGETS[@]}"; do
        [[ -z "$ip" ]] && continue
        echo -en "  → $ip … "
        if scp -q -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
               /tmp/kri_master_push.pub "${ip}:/tmp/kri_master_push.pub" 2>/dev/null && \
           ssh -q -o StrictHostKeyChecking=no -o ConnectTimeout=5 "$ip" \
               "sudo cp /tmp/kri_master_push.pub /etc/salt/pki/minion/minion_master.pub && \
                sudo chmod 644 /etc/salt/pki/minion/minion_master.pub && \
                sudo launchctl stop com.saltstack.salt.minion 2>/dev/null; sleep 2; \
                sudo launchctl start com.saltstack.salt.minion 2>/dev/null" 2>/dev/null; then
            echo -e "${GREEN}ok${NC}"
            ok_count=$((ok_count + 1))
        else
            echo -e "${YELLOW}unreachable${NC}"
            fail_count=$((fail_count + 1))
        fi
    done
    rm -f /tmp/kri_master_push.pub

    success "$ok_count host(s) updated"
    [[ $fail_count -gt 0 ]] && warn "$fail_count host(s) unreachable"
    info "Waiting 15s then triggering grain report…"
    sleep 15
    docker exec deploy-salt-master-1 salt '*' state.apply base.grain_report \
        --timeout=60 --async 2>/dev/null && \
        success "Grain report queued — nodes should appear online in ~30s" || \
        warn "Grain report failed — run manually after minions reconnect"
}

# ══════════════════════════════════════════════════════════════════════════════
# DIAGNOSE / SEED / DEV
# ══════════════════════════════════════════════════════════════════════════════

cmd_diagnose() {
    local target="${1:-}"
    if [[ -z "$target" ]]; then
        _prompt_input "Node IP or minion ID to diagnose" ""
        target="$PROMPT_RESULT"
    fi
    [[ -z "$target" ]] && error "Target required"

    header "Diagnosing: $target"

    info "[1/4] Network reachability…"
    if ping -c 2 -W 2 "$target" >/dev/null 2>&1; then
        success "Host $target responds to ping"
    else
        warn "Host $target does not respond to ping"
    fi

    info "[2/4] SSH port (22)…"
    if timeout 5 bash -c "</dev/tcp/$target/22" 2>/dev/null; then
        success "Port 22 is open"
    else
        warn "Port 22 unreachable — ensure Remote Login is enabled"
    fi

    info "[3/4] Salt minion key status (via mm1 salt-api)…"
    local salt_api_url="${SALT_API_URL:-http://100.102.68.75:8080}"
    local salt_keys
    # Query mm1 salt-api for accepted keys (auth via SALT_API_USER/SALT_API_PASSWORD env vars)
    local salt_pass="${SALT_API_PASSWORD:-}"
    local salt_user="${SALT_API_USER:-krisalt}"
    if curl -sf --max-time 5 "$salt_api_url/health" >/dev/null 2>&1; then
        local salt_token
        salt_token=$(curl -sf --max-time 10 \
            -d "username=${salt_user}" -d "passwd=${salt_pass}" -d "eauth=pam" \
            "$salt_api_url/login" 2>/dev/null \
            | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('return',[{}])[0].get('token',''))" 2>/dev/null || echo "")
        salt_keys=$(curl -sf --max-time 10 -H "X-Auth-Token: ${salt_token}" \
            "$salt_api_url/keys" 2>/dev/null \
            | python3 -c "import sys,json;d=json.load(sys.stdin);print('\n'.join(d.get('return',{}).get('minions',[])))" 2>/dev/null || echo "")
        if echo "$salt_keys" | grep -q "$target"; then
            success "Minion key for $target is ACCEPTED on mm1"
        else
            warn "No accepted salt key for $target on mm1 (check: ssh mm1 sudo salt-key -L)"
        fi
    else
        warn "Cannot reach mm1 salt-api at $salt_api_url — check mm1 salt-master service"
    fi

    info "[4/4] kri API — node record…"
    local api_url="http://localhost:8000/health/ready"
    if curl -sf --max-time 5 "$api_url" >/dev/null 2>&1; then
        success "kri API is responding"
    else
        warn "kri API not responding at localhost:8000 — run: kri status"
    fi

    info "[5/5] kri node record in DB…"
    docker exec deploy-db-1 psql -U fleet -d fleet_platform -t -c \
        "SELECT hostname, minion_id, status, last_seen_at FROM nodes \
         WHERE bootstrap_ip='$target' OR minion_id='$target' OR hostname LIKE '%$target%';" \
        2>/dev/null | grep -v '^$' || warn "Node not found in DB (or DB container not running)"
}

cmd_seed() {
    header "Seeding default users"
    docker cp "$REPO_DIR/scripts/seed.py" deploy-api-1:/app/seed.py
    docker exec deploy-api-1 uv run python3 /app/seed.py
    success "Default users created"
}

cmd_dev() {
    local sub="${1:-start}"
    case "$sub" in
        start)
            header "Local dev mode"
            require_env
            docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" \
                -f "$REPO_DIR/deploy/docker-compose.override.yml" \
                up -d db redis --quiet-pull 2>&1 | tail -2
            # shellcheck disable=SC1090
            source "$VENV"
            cd "$REPO_DIR"
            uvicorn fleet_platform.api.main:app --host 0.0.0.0 --port 8000 --log-level info &
            echo $! > /tmp/kri-dev-api.pid
            cd "$FRONTEND_DIR" && npm run dev -- --host 0.0.0.0 &
            echo $! > /tmp/kri-dev-frontend.pid
            success "Dev mode: API :8000, Frontend :5173"
            ;;
        stop)
            info "Stopping dev processes…"
            kill "$(cat /tmp/kri-dev-api.pid 2>/dev/null)" 2>/dev/null || true
            kill "$(cat /tmp/kri-dev-frontend.pid 2>/dev/null)" 2>/dev/null || true
            rm -f /tmp/kri-dev-api.pid /tmp/kri-dev-frontend.pid
            success "Dev stopped"
            ;;
    esac
}

# ══════════════════════════════════════════════════════════════════════════════
# VERSION
# ══════════════════════════════════════════════════════════════════════════════

cmd_version() {
    echo -e "${BOLD}kri${NC} v$(version) — Mac Mini Fleet Management Platform"
}

# ══════════════════════════════════════════════════════════════════════════════
# USAGE / MAIN
# ══════════════════════════════════════════════════════════════════════════════

usage() {
    cat <<EOF

${BOLD}kri${NC} — Mac Mini Fleet Management Platform v$(version)

${BOLD}Usage:${NC}  kri [command] [subcommand] [flags]

${BOLD}Service management:${NC}
  ${CYAN}up${NC}               Start all services (kri up [svc])
  ${CYAN}down${NC}             Stop all services
  ${CYAN}restart${NC}          Stop then start
  ${CYAN}status${NC}           Show service status
  ${CYAN}logs${NC}             Tail logs (kri logs [svc])

${BOLD}Deploy:${NC}
  ${CYAN}deploy${NC}           Build and deploy (interactive or kri deploy [svc])
  ${CYAN}rolling-deploy${NC}   Zero-downtime rolling restart
  ${CYAN}rollback${NC}         Restore :previous images

${BOLD}Infrastructure:${NC}
  ${CYAN}infra status${NC}     Show containers, volumes, images
  ${CYAN}infra destroy${NC}    Remove containers (keep volumes)
  ${CYAN}infra recreate${NC}   Destroy + rebuild + restart
  ${CYAN}infra reset${NC}      WIPE all data + rebuild fresh
  ${CYAN}infra prune${NC}      Remove unused Docker resources

${BOLD}Testing:${NC}
  ${CYAN}test${NC}             Run tests (interactive or kri test [unit|integration|all|e2e])

${BOLD}PKI:${NC}
  ${CYAN}pki init${NC}         Generate salt-master keys (first deploy)
  ${CYAN}pki backup${NC}       Print vault commands to back up master.pem
  ${CYAN}pki push [ip...]${NC} Push master.pub to minions after restart

${BOLD}Tools:${NC}
  ${CYAN}diagnose [ip]${NC}    Investigate an offline node
  ${CYAN}seed${NC}             Create default users
  ${CYAN}dev${NC}              Local dev mode (host uvicorn + vite)
  ${CYAN}version${NC}          Show version

Run ${BOLD}kri${NC} without arguments for interactive mode.

EOF
}

main() {
    local cmd="${1:-}"
    shift 2>/dev/null || true

    if [[ -z "$cmd" ]]; then
        echo -e "\n${BOLD}${CYAN}kri${NC} — Mac Mini Fleet Management Platform v$(version)"
        _prompt_select "What would you like to do?" \
            "up" "down" "restart" "status" "logs" \
            "deploy" "rolling-deploy" "rollback" \
            "infra" \
            "test" "diagnose" "seed" "dev" \
            "pki" "version"
        cmd="$PROMPT_RESULT"
    fi

    case "$cmd" in
        up)             cmd_up "$@" ;;
        down)           cmd_down ;;
        restart)        cmd_restart "$@" ;;
        status)         cmd_status ;;
        logs)           cmd_logs "$@" ;;
        deploy)         cmd_deploy "$@" ;;
        rolling-deploy) cmd_rolling_deploy ;;
        rollback)       cmd_rollback ;;
        infra)          cmd_infra "$@" ;;
        test)           cmd_test "$@" ;;
        pki)            cmd_pki "$@" ;;
        pki-init)       cmd_pki_init ;;        # backwards compat
        pki-backup)     cmd_pki_backup ;;      # backwards compat
        pki-push)       cmd_pki_push "$@" ;;   # backwards compat
        diagnose)       cmd_diagnose "$@" ;;
        seed)           cmd_seed ;;
        dev)            cmd_dev "$@" ;;
        version|-v|--version) cmd_version ;;
        help|-h|--help) usage ;;
        *)              echo -e "${RED}[error]${NC} Unknown command: $cmd"; usage; exit 1 ;;
    esac
}

main "$@"
