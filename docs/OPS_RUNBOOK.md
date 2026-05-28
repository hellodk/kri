# kri Ops Runbook

Primary reference for running and troubleshooting the kri fleet management platform.

---

## Table of Contents

1. [Starting and Stopping kri](#starting-and-stopping-kri)
2. [Log Files](#log-files)
3. [Bootstrap Troubleshooting](#bootstrap-troubleshooting)
4. [Bootstrap Telemetry](#bootstrap-telemetry)
5. [Database Inspection](#database-inspection)
6. [Service Health Checks](#service-health-checks)
7. [Common Failure Scenarios](#common-failure-scenarios)
8. [Backup and Restore](#backup-and-restore)
9. [Rolling Restart vs Full Restart](#rolling-restart-vs-full-restart)
10. [Environment Variables](#environment-variables)

---

## One-Time Setup

Before running kri for the first time, create the Salt pillar directory on the **kri server** (the machine running the API and Celery worker). The Celery worker writes node config files here before each Ansible bootstrap run.

```bash
sudo mkdir -p /srv/salt/pillar
sudo chown -R $(whoami):$(whoami) /srv/salt
```

> **Why on this machine?** kri's Celery worker writes a `.sls` pillar file locally before Ansible runs. Salt on the Mac Mini then reads its pillar from the Salt master (also this server). If you're deploying kri on a dedicated server, run these commands there.
>
> **Alternative:** Set `PILLAR_DIR=/your/writable/path` in `.env` to use a non-standard location instead of `/srv/salt/pillar`.

---

## Starting and Stopping kri

All lifecycle operations go through `./scripts/kri.sh`. The script manages PIDs in `.kri-pids/` and writes logs to `.kri-logs/`.

```bash
./scripts/kri.sh start    # Start postgres + redis (Docker), API, Celery worker, Vite frontend
./scripts/kri.sh stop     # Stop all services in reverse order
./scripts/kri.sh restart  # Stop then start
./scripts/kri.sh status   # Show PID and health of each service
./scripts/kri.sh logs api|worker|frontend   # Tail a log file (Ctrl-C to exit)
./scripts/kri.sh test [grep-pattern]        # Run E2E test suite (kri must be running)
```

After a successful `start`:

| Service  | URL                            |
|----------|--------------------------------|
| Frontend | http://localhost:5173          |
| API docs | http://localhost:8000/docs     |

The script waits up to 20 seconds for both Docker containers to report `healthy` before bringing up the application services. If either container does not become healthy the script exits with an error — run `docker compose -f deploy/docker-compose.yml ps` to investigate.

---

## Log Files

| Log | Path | What's in it |
|-----|------|--------------|
| API | `.kri-logs/api.log` | HTTP requests, SQL queries, auth events, FastAPI startup |
| Celery worker | `.kri-logs/worker.log` | Bootstrap jobs, drift compute, SBOM tasks, task lifecycle |
| Frontend | `.kri-logs/frontend.log` | Vite dev server output, HMR events |

### Useful tailing commands

```bash
# Follow the API log
tail -f .kri-logs/api.log

# Follow the worker log
tail -f .kri-logs/worker.log

# Filter bootstrap-specific log lines (worker)
grep -i "bootstrap" .kri-logs/worker.log | tail -50

# Find errors in the last 200 lines of the API log
tail -200 .kri-logs/api.log | grep -i "error\|exception\|traceback"

# Live filter — only show worker lines that mention a task name
tail -f .kri-logs/worker.log | grep --line-buffered "Task\|TASK\|bootstrap"
```

---

## Bootstrap Troubleshooting

A bootstrap runs as a Celery task (`bootstrap_node`) that:
1. Reads SSH credentials and Salt master address from platform Settings
2. Generates a pillar file at `/srv/salt/pillar/<minion_id>.sls`
3. Runs `ansible-runner` against the target Mac Mini
4. Waits up to 20 minutes for the Salt minion to connect

### Common failures

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `UNREACHABLE` in ansible stdout | Target IP wrong or Mac Mini is off/unreachable | Verify IP; test with `ping <ip>`; check that port 22 is open |
| `Authentication failure` | Wrong SSH credentials | Go to Settings → Bootstrap and update SSH username / password |
| Timeout after 20 minutes | Salt minion installed but cannot reach Salt master | Check network path; verify Salt master address in Settings |
| `no hosts matched` | minion_id format rejected by Salt | minion_id must match `[a-zA-Z0-9._-]{1,128}` — no spaces or special characters |
| `ansible.posix not found` | ansible-runner environment missing the posix collection | Re-install with `ansible-galaxy collection install ansible.posix` |
| Bootstrap stuck in `bootstrapping` | Celery worker died mid-task | Cancel via API (see below) and retry |

### How to check a stuck bootstrap

```bash
# Find node by minion ID in database
docker exec deploy-postgres-1 psql -U fleet -d fleet_demo -c \
  "SELECT id, minion_id, bootstrap_status, bootstrap_error, bootstrap_ip \
   FROM nodes WHERE minion_id LIKE '%mm1%';"

# Cancel a stuck bootstrap via API (returns the node to 'failed' so it can be retried)
curl -s -X POST http://localhost:8000/api/v1/ansible/bootstrap/<node_id>/cancel \
  -H "Authorization: Bearer <token>"

# Get full bootstrap logs for a node
curl -s http://localhost:8000/api/v1/ansible/bootstrap/<node_id>/logs \
  -H "Authorization: Bearer <token>" | jq '{status: .bootstrap_status, error: .ansible_stdout}'
```

After cancelling, fix the underlying issue and trigger a new bootstrap from the Fleet → Add Node flow.

---

## Bootstrap Telemetry

kri stores telemetry for every bootstrap attempt directly on the `nodes` row.

### What is captured

| Field | Column | Notes |
|-------|--------|-------|
| Current status | `bootstrap_status` | `pending` → `bootstrapping` → `completed` or `failed` |
| Target IP | `bootstrap_ip` | IP used for the Ansible connection |
| Error message | `bootstrap_error` | Human-readable failure reason or `[blocked at: TASK <name>]` when stuck |
| Full Ansible stdout | `bootstrap_logs` | Stored after the run completes (success or failure) |
| Last Ansible task | embedded in `bootstrap_error` | Written live every 5 s while bootstrapping — shows where a slow run is blocked |

All user actions (triggering bootstrap, cancelling, changing Settings) are also recorded in the `audit_events` table with the actor's username, action, and timestamp.

### API endpoints for telemetry

```bash
# Lightweight status poll — returns status + error (no stdout)
GET /api/v1/ansible/bootstrap/{node_id}/status

# Full detail — returns status, ansible_stdout, and pillar file contents
GET /api/v1/ansible/bootstrap/{node_id}/logs
```

Example — extract just what you need from the logs endpoint:

```bash
curl -s http://localhost:8000/api/v1/ansible/bootstrap/<node_id>/logs \
  -H "Authorization: Bearer <token>" \
  | jq '{
      status:      .bootstrap_status,
      last_error:  (.ansible_stdout // "no stdout yet"),
      pillar_ok:   (.pillar | startswith("(") | not)
    }'
```

### Enabling verbose Ansible output

Set `ANSIBLE_VERBOSITY=2` in your shell before starting the worker (or add it to `.env`):

```bash
# In .env
ANSIBLE_VERBOSITY=2

# Then restart the worker
./scripts/kri.sh restart
```

With verbosity 2, SSH connection details, module arguments, and return values are written to `.kri-logs/worker.log`. Set to `4` for full debug (very noisy).

---

## Database Inspection

```bash
# Open an interactive psql session
docker exec -it deploy-postgres-1 psql -U fleet -d fleet_demo

# Or run a one-liner
docker exec deploy-postgres-1 psql -U fleet -d fleet_demo -c "<SQL>"
```

### Useful queries

```sql
-- List all tables
\dt

-- Recent nodes (most recently created first)
SELECT minion_id, status, bootstrap_status, bootstrap_error
FROM nodes
ORDER BY created_at DESC
LIMIT 10;

-- Recent audit events
SELECT action, actor, resource_type, event_at
FROM audit_events
ORDER BY event_at DESC
LIMIT 20;

-- Recent Ansible / playbook jobs
SELECT key, status, created_at
FROM ansible_jobs
ORDER BY created_at DESC
LIMIT 10;

-- Nodes stuck in bootstrapping
SELECT id, minion_id, bootstrap_ip, bootstrap_error
FROM nodes
WHERE bootstrap_status = 'bootstrapping';

-- Wipe bootstrap state for a node (use when cancel API is not enough)
UPDATE nodes
SET bootstrap_status = 'failed',
    bootstrap_error  = 'Reset by operator'
WHERE minion_id = '<minion_id>';
```

---

## Environment Variables

Configuration lives in `.env` at the repo root. Never commit this file to version control.

| Variable | Example | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | `postgresql+psycopg://fleet:fleet@localhost:5432/fleet_demo` | PostgreSQL connection string used by the API and Celery worker |
| `TEST_DATABASE_URL` | `postgresql+psycopg://fleet:fleet@localhost:5432/fleet_test` | Separate DB used by pytest — kept isolated from demo data |
| `REDIS_URL` | `redis://:redispass@localhost:6379/0` | Redis connection for Celery broker and result backend |
| `JWT_SECRET` | `change-me-…` | HMAC key for signing JWTs — **must be changed before any production use** (generate with `openssl rand -hex 32`) |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | Access token lifetime |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token lifetime |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | Allowed CORS origin for the API |
| `ENVIRONMENT` | `development` | Controls debug behaviour — set to `production` to disable debug routes |
| `ANSIBLE_VERBOSITY` | `0` | Ansible output verbosity (0–4); increase to debug stuck bootstraps |

---

## Service Health Checks

Run from the kri server:

```bash
# All services status
./scripts/kri.sh status

# API readiness (returns {"status":"ok"})
curl -s http://localhost:8000/health/ready

# Individual Docker healthcheck status
docker inspect --format='{{.State.Health.Status}}' deploy-api-1
docker inspect --format='{{.State.Health.Status}}' deploy-worker-1
```

---

## Common Failure Scenarios

### API container crash-looping

**Diagnosis:**

```bash
docker logs deploy-api-1 | tail -50
```

Look for database connection errors, Redis errors, or import failures.

**Fix:**
```bash
# Check DB is running and accessible
docker exec deploy-postgres-1 pg_isready -U fleet -d fleet_demo

# Check Redis is running
docker exec deploy-redis-1 redis-cli ping

# Restart the API
docker restart deploy-api-1
```

### Celery worker not processing tasks

**Diagnosis:**

```bash
# Check worker is running
ps aux | grep celery | grep -v grep

# Check Redis queue depth
docker exec deploy-redis-1 redis-cli LLEN celery

# Check worker logs for errors
tail -50 .kri-logs/worker.log
```

**Fix:**
```bash
# Restart the worker
./scripts/kri.sh stop
./scripts/kri.sh start

# Or individually
pkill -f "celery worker"
sleep 2
celery -A fleet_platform.workers.app worker --loglevel=info
```

### Salt minion not connecting to Salt master

**Diagnosis:**

```bash
# Check if ZeroMQ ports are open on the kri server
netstat -tlnp | grep -E '4505|4506'

# Check Salt master logs
docker logs deploy-saltmaster-1 2>&1 | tail -50

# Check minion key status
docker exec deploy-saltmaster-1 salt-key -L
```

**Fix:**
```bash
# Ensure firewall allows 4505/4506 from target Mac Mini
sudo ufw allow from <target_ip> to any port 4505:4506

# If minion key is unaccepted
docker exec deploy-saltmaster-1 salt-key -A -y

# Verify minion can reach Salt master
ssh <mac_mini_ip> "ping <salt_master_ip>"
```

### Node stuck in "bootstrapping"

**Diagnosis:**

```bash
# Find the node
docker exec deploy-postgres-1 psql -U fleet -d fleet_demo -c \
  "SELECT id, minion_id, bootstrap_status, bootstrap_error FROM nodes WHERE bootstrap_status = 'bootstrapping';"

# Check the last recorded Ansible task
curl -s http://localhost:8000/api/v1/ansible/bootstrap/<node_id>/logs \
  -H "Authorization: Bearer <token>" | jq '.bootstrap_error'
```

**Fix:**
```bash
# Try to cancel via API first
curl -s -X POST http://localhost:8000/api/v1/ansible/bootstrap/<node_id>/cancel \
  -H "Authorization: Bearer <token>"

# If API not available, reset directly in database
docker exec deploy-postgres-1 psql -U fleet -d fleet_demo -c \
  "UPDATE nodes SET bootstrap_status = 'failed', bootstrap_error = 'Reset by operator' WHERE id = <node_id>;"
```

### Database disk full

**Diagnosis:**

```bash
# Check volume usage
docker exec deploy-postgres-1 df -h /var/lib/postgresql

# Check backup directory
docker exec deploy-pg_backup-1 du -sh /var/backups/postgresql
```

**Fix:**
```bash
# Remove old backup dumps (keep last 5)
docker exec deploy-pg_backup-1 bash -c \
  "ls -1tr /var/backups/postgresql/*.dump 2>/dev/null | head -n -5 | xargs rm -f"

# Or manually trigger a cleanup
docker exec deploy-postgres-1 VACUUM FULL;
```

### Redis running out of memory

**Diagnosis:**

```bash
docker exec deploy-redis-1 redis-cli info memory
```

Look for `used_memory_human` and `maxmemory_human`. If used is near max, OOM will trigger eviction.

**Fix:**
```bash
# Check Celery queue and task counts
docker exec deploy-redis-1 redis-cli DBSIZE

# Flush completed tasks (use carefully)
docker exec deploy-redis-1 redis-cli FLUSHDB

# Restart Redis to clear all data
docker restart deploy-redis-1
./scripts/kri.sh restart  # Restart worker and API to reconnect
```

### Database migration failed at startup

**Diagnosis:**

```bash
# Check API logs
tail -100 .kri-logs/api.log | grep -i "migration\|alembic"

# Check for migration advisory locks
docker exec deploy-postgres-1 psql -U fleet -d fleet_demo -c \
  "SELECT * FROM pg_locks WHERE NOT granted;"
```

**Fix:**
```bash
# Manually unlock migration (if advisory lock is stuck)
docker exec deploy-postgres-1 psql -U fleet -d fleet_demo -c \
  "SELECT pg_advisory_unlock_all();"

# Restart the API (will retry migration)
docker restart deploy-api-1
```

---

## Backup and Restore

### Verify latest backup

```bash
docker exec deploy-pg_backup-1 ls -lh /var/backups/postgresql/ | tail -5
```

### Manual backup

```bash
docker exec deploy-pg_backup-1 \
  pg_dump -h db -U fleet -Fc fleet_demo \
  -f /var/backups/postgresql/manual_$(date +%Y%m%d_%H%M%S).dump
```

### Restore from backup

```bash
# Stop services first
./scripts/kri.sh stop

# Restore (replace DUMPFILE with actual filename)
docker run --rm \
  -v pgbackups:/var/backups/postgresql \
  -e PGPASSWORD=<POSTGRES_PASSWORD> \
  timescale/timescaledb:2.17.2-pg17 \
  pg_restore -h db -U fleet -d fleet_demo \
  /var/backups/postgresql/<DUMPFILE>

./scripts/kri.sh start
```

---

## Rolling Restart vs Full Restart

### Full restart
```bash
./scripts/kri.sh restart
```

Use when:
- Database migrations are pending
- Redis data loss is acceptable
- A clean slate is needed (e.g., after code deployment, configuration change)
- Debugging a hung or unresponsive state

### Rolling restart (zero-downtime)
```bash
docker-compose -f deploy/docker-compose.yml up -d --no-deps --build api worker
```

Use when:
- Only code changes in API/worker (no schema changes)
- Running a task-critical bootstrap
- Minimal disruption is required
- Redis broker state must be preserved

For most operational scenarios, a full restart via `./scripts/kri.sh restart` is recommended. Rolling restart is most useful during active deployments to avoid interrupting long-running Ansible jobs.
