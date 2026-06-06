# kri Standalone / Systemd Deployment

This directory contains systemd unit files for running kri directly on a bare Linux host
(no container runtime required). This is the **standalone** deployment mode — see the
multi-mode deployment rule in the project CLAUDE.md for the full picture.

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Linux with systemd | Ubuntu 22.04+ / Debian 12+ / RHEL 9+ |
| `uv` | Install from <https://docs.astral.sh/uv/getting-started/installation/> |
| PostgreSQL 15+ | Local install or remote — must be reachable at `DATABASE_URL` |
| Redis 7+ | Local install or remote — must be reachable at `REDIS_URL` |
| Python 3.11+ | Managed by `uv` via `.python-version` |

## Install Steps

### 1. Create the kri system user

```bash
sudo useradd --system --create-home --home-dir /opt/kri --shell /usr/sbin/nologin kri
```

### 2. Deploy the project

```bash
sudo git clone https://github.com/your-org/kri.git /opt/kri
sudo chown -R kri:kri /opt/kri
# Install Python dependencies (uv reads pyproject.toml)
cd /opt/kri && sudo -u kri uv sync --frozen
```

### 3. Configure environment

```bash
sudo mkdir -p /etc/kri
sudo cp /opt/kri/deploy/systemd/kri.env.example /etc/kri/kri.env
sudo nano /etc/kri/kri.env        # fill in all CHANGE_ME values
sudo chmod 600 /etc/kri/kri.env
sudo chown kri:kri /etc/kri/kri.env
```

Key variables to set:
- `DATABASE_URL` — PostgreSQL connection string (use `127.0.0.1`, not a container hostname)
- `REDIS_URL` — Redis connection string (use `127.0.0.1`, not a container hostname)
- `JWT_SECRET` — generate with `python3 -c "import secrets; print(secrets.token_hex(32))"`
- `SALT_API_URL`, `SALT_API_USER`, `SALT_API_PASSWORD` — Salt HTTP API credentials
- `KRI_API_URL` — public URL of this server (how Mac Minis call back)

### 4. Install service units

```bash
sudo cp /opt/kri/deploy/systemd/kri-api.service    /etc/systemd/system/
sudo cp /opt/kri/deploy/systemd/kri-worker.service /etc/systemd/system/
sudo cp /opt/kri/deploy/systemd/kri-beat.service   /etc/systemd/system/
sudo systemctl daemon-reload
```

### 5. Enable and start services

```bash
sudo systemctl enable --now kri-api kri-worker kri-beat
```

The `kri-api` unit runs `deploy/migrate.sh` (Alembic migrations) before starting uvicorn.
Migrations are advisory-lock-protected — safe to run with the service restart cycle.

### 6. Verify

```bash
sudo systemctl status kri-api kri-worker kri-beat
journalctl -u kri-api -f
journalctl -u kri-worker -f
```

Check the API health endpoint:

```bash
curl http://localhost:8000/health/ready
```

## Service management

```bash
# Restart all three
sudo systemctl restart kri-api kri-worker kri-beat

# View logs (last 100 lines)
journalctl -u kri-api -n 100
journalctl -u kri-worker -n 100
journalctl -u kri-beat -n 100

# Disable on boot (without stopping)
sudo systemctl disable kri-api kri-worker kri-beat
```

## Updating kri

```bash
cd /opt/kri
sudo -u kri git pull
sudo -u kri uv sync --frozen
sudo systemctl restart kri-api kri-worker kri-beat
# kri-api's ExecStartPre will run migrations automatically on restart
```

## Other deployment modes

This project also supports:
- **docker-compose** — `deploy/docker-compose.yml`, single `docker compose up -d`
- **Kubernetes** — `deploy/k8s/` manifests (Deployments, Services, SealedSecrets, ServiceMonitor)

All three modes share the same application artifact and the same environment variable names.
Configuration is delivered via environment only — no mode-specific code paths.
