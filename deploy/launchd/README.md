# kri Native macOS Deployment (launchd)

This directory contains LaunchDaemon plist files for running kri natively on
macOS — no Docker, no Podman, no Linux VM. Use this for a Mac mini fleet host
that runs kri itself (the control plane) on the same hardware family it
manages. For Linux hosts, use [../systemd/](../systemd/) instead.

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| macOS 13+ | Apple Silicon (M1/M2/M3/M4) or Intel |
| Homebrew | `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"` |
| `uv` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` *or* `brew install uv` |
| PostgreSQL 17 | `brew install postgresql@17 && brew services start postgresql@17` |
| Redis 7 | `brew install redis && brew services start redis` |
| Python 3.13 | Managed by `uv` via `pyproject.toml` |

## Install Steps

### 1. Create the kri service user

macOS uses `sysadminctl`, not `useradd`:

```bash
sudo sysadminctl -addUser kri \
    -fullName "kri Fleet Platform" \
    -shell /usr/bin/false \
    -home /opt/kri
sudo dscl . -create /Users/kri IsHidden 1
sudo dseditgroup -o create kri
sudo dseditgroup -o edit -a kri -t user kri
```

### 2. Deploy the project

```bash
sudo mkdir -p /opt/kri /var/log/kri /etc/kri
sudo chown -R kri:kri /opt/kri /var/log/kri /etc/kri
sudo -u kri git clone https://github.com/your-org/kri.git /opt/kri
cd /opt/kri
sudo -u kri uv sync --frozen
```

### 3. Configure environment

```bash
sudo cp /opt/kri/deploy/systemd/kri.env.example /etc/kri/kri.env
sudo nano /etc/kri/kri.env       # fill in CHANGE_ME values
sudo chmod 600 /etc/kri/kri.env
sudo chown kri:kri /etc/kri/kri.env
```

Adjust paths for macOS:
- `WORKER_SSH_DIR=/opt/kri/deploy/ssh`
- `PILLAR_DIR=/opt/kri/srv/salt/pillar` (macOS ships no `/srv` by convention)
- `KRI_API_URL=http://YOUR_MAC_MINI_IP:8000` (LAN IP or hostname)

### 4. Install the LaunchDaemons

```bash
sudo cp /opt/kri/deploy/launchd/com.kri.api.plist            /Library/LaunchDaemons/
sudo cp /opt/kri/deploy/launchd/com.kri.worker.plist         /Library/LaunchDaemons/
sudo cp /opt/kri/deploy/launchd/com.kri.worker-ansible.plist /Library/LaunchDaemons/
sudo cp /opt/kri/deploy/launchd/com.kri.beat.plist           /Library/LaunchDaemons/
sudo chown root:wheel /Library/LaunchDaemons/com.kri.*.plist
sudo chmod 644       /Library/LaunchDaemons/com.kri.*.plist
```

### 5. Bootstrap and load services

```bash
sudo launchctl bootstrap system /Library/LaunchDaemons/com.kri.api.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/com.kri.worker.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/com.kri.worker-ansible.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/com.kri.beat.plist
```

The `com.kri.api` job runs Alembic migrations (advisory-locked, see
[deploy/migrate.sh](../migrate.sh)) before starting uvicorn.

### 6. Verify

```bash
sudo launchctl list | grep com.kri
curl http://localhost:8000/health/ready
tail -f /var/log/kri/api.out.log
```

## Service Management

```bash
# Stop / start
sudo launchctl bootout system /Library/LaunchDaemons/com.kri.api.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/com.kri.api.plist

# Force a restart of the running job
sudo launchctl kickstart -k system/com.kri.api

# Inspect job state (PID, last exit code, KeepAlive reasons)
sudo launchctl print system/com.kri.api
```

## Log Rotation

launchd does not rotate logs. Add a `newsyslog` rule:

```bash
sudo tee /etc/newsyslog.d/kri.conf <<'EOF'
# logfilename       [owner:group]   mode   count   size    when    flags
/var/log/kri/*.log  kri:kri         640    7       *       $D0     GJ
EOF
```

This keeps 7 daily rotations gzipped.

## Updating kri

```bash
cd /opt/kri
sudo -u kri git pull
sudo -u kri uv sync --frozen
sudo launchctl kickstart -k system/com.kri.api
sudo launchctl kickstart -k system/com.kri.worker
sudo launchctl kickstart -k system/com.kri.worker-ansible
sudo launchctl kickstart -k system/com.kri.beat
```

`com.kri.api` re-runs the migrations on each kickstart.

## Other Deployment Modes

This project also supports:

- **docker-compose** — `deploy/docker-compose.yml`, `docker compose up -d`
- **podman-compose** — same compose file with `NGINX_RESOLVER` overridden
- **Kubernetes** — `deploy/k8s/` Kustomize base, `kubectl apply -k deploy/k8s/`
- **systemd (Linux native)** — [deploy/systemd/](../systemd/)

All modes share the same Python artifact and the same env-var contract.
