# Salt Stack Onboarding Guide

This guide walks through connecting Mac Mini nodes to the Fleet Platform using SaltStack. By the end, every Mac Mini will automatically report its system state (grains), trigger drift computation, and run nightly SBOM scans.

## Architecture

```
Mac Mini (Salt Minion)
    │  ZeroMQ TCP 4505/4506
    ▼
Control Plane (Salt Master + Fleet Platform API + Celery Workers)
    │  POST /api/v1/ingest/*
    ▼
PostgreSQL (nodes, node_facts, drift_records, sbom_scans)
```

The Salt Master and Fleet Platform API run on the same server (or the same LAN). Mac Minis are minions — they receive commands from the master and push data to the API using per-node tokens stored in Salt Pillar.

## Prerequisites

| Component | Where |
|-----------|-------|
| Fleet Platform API | Control plane, port 8000 |
| Salt Master | Control plane (same server or separate) |
| Salt Minion | Each Mac Mini |
| Redis | Control plane (for Celery) |
| PostgreSQL | Control plane |
| Syft | Each Mac Mini (for SBOM scans) |

---

## Step 1 — Install Salt Master

### Linux (Ubuntu/Debian)

```bash
curl -o /tmp/bootstrap-salt.sh -L https://bootstrap.saltproject.io
sudo sh /tmp/bootstrap-salt.sh -M -N stable
sudo systemctl enable salt-master
sudo systemctl start salt-master
```

### macOS (control plane is a Mac Mini)

```bash
brew install saltstack
sudo salt-master -d
```

Verify:
```bash
sudo salt-master --versions-report | head -3
```

---

## Step 2 — Configure Salt Master

Edit `/etc/salt/master` (Linux) or `/usr/local/etc/salt/master` (macOS):

```yaml
# Network
interface: 0.0.0.0

# State and pillar roots
file_roots:
  base:
    - /srv/salt/states

pillar_roots:
  base:
    - /srv/salt/pillar

# Auto-accept keys (safe on a private LAN; remove for stricter environments)
auto_accept: True

# Logging
log_level: info
log_file: /var/log/salt/master
```

Create directories and restart:

```bash
sudo mkdir -p /srv/salt/states /srv/salt/pillar
sudo systemctl restart salt-master   # Linux
# or: sudo pkill -HUP salt-master   # macOS
```

---

## Step 3 — Deploy Salt States from the Repo

The Fleet Platform repo ships the required Salt states under `salt/states/`. Copy them to the master:

```bash
# Run from the kri repo root on the control plane
sudo cp -r salt/states/* /srv/salt/states/

# Verify
ls /srv/salt/states/base/
# grain_report.sls   sbom_scan.sls
```

### What each state does

**`base/grain_report.sls`** — Posts system grains (hardware, OS, IP, packages) to the Fleet Platform ingest API. Called on every minion start via the reactor, and manually for immediate updates.

**`base/sbom_scan.sls`** — Runs Syft to produce a CycloneDX JSON SBOM of the entire system, then uploads it to the Fleet Platform. Scheduled nightly at 2am via Salt schedule.

---

## Step 4 — Install Salt Minion on each Mac Mini

SSH into each Mac Mini and run:

```bash
# Option A — Homebrew
brew install saltstack

# Option B — Official bootstrap script
curl -o /tmp/bootstrap-salt.sh -L https://bootstrap.saltproject.io
sudo sh /tmp/bootstrap-salt.sh stable
```

---

## Step 5 — Configure Salt Minion on each Mac Mini

Edit `/usr/local/etc/salt/minion`:

```yaml
# Replace with the control plane's LAN IP
master: 10.0.0.1

# Must match the hostname you will register in Fleet Platform
id: mac-mini-01

log_level: info
log_file: /var/log/salt/minion
```

Start the minion:

```bash
sudo salt-minion -d
# macOS launchd alternative:
# sudo launchctl load /Library/LaunchDaemons/com.saltstack.salt.minion.plist
```

Check it's connecting:
```bash
sudo tail -f /var/log/salt/minion | grep -E "Authentication|Minion|Connected"
```

---

## Step 6 — Accept Minion Keys

On the **Salt Master**:

```bash
# View pending keys
sudo salt-key -L

# Accept one at a time (recommended first time)
sudo salt-key -a mac-mini-01

# Or accept all pending at once
sudo salt-key -A
```

Test connectivity:
```bash
sudo salt '*' test.ping
# mac-mini-01: True
# mac-mini-02: True
# ...
```

---

## Step 7 — Register Nodes in Fleet Platform

Each Mac Mini needs a **node token** — a secret used to authenticate ingest requests. Tokens are generated once by the Fleet Platform API and stored in Salt Pillar. **The token is shown only once; copy it immediately.**

### Get an admin token

```bash
FLEET_API="http://localhost:8000"

ADMIN_TOKEN=$(curl -s -X POST $FLEET_API/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@fleet.local","password":"changeme123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

### Register each node

```bash
curl -s -X POST $FLEET_API/api/v1/nodes/register \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"minion_id": "mac-mini-01", "hostname": "mac-mini-01"}' \
  | python3 -m json.tool
```

Response:
```json
{
  "node_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "minion_id": "mac-mini-01",
  "token": "xK9mP2...",
  "message": "Token shown once. Store it in Salt pillar immediately."
}
```

Repeat this for every Mac Mini, saving each token.

### Bulk registration script

For a large fleet, use this loop:

```bash
FLEET_API="http://localhost:8000"
ADMIN_TOKEN=$(...)   # as above

NODES=(mac-mini-01 mac-mini-02 mac-mini-03 builder-01 builder-02)

for NODE in "${NODES[@]}"; do
  echo "Registering $NODE..."
  curl -s -X POST $FLEET_API/api/v1/nodes/register \
    -H "Authorization: Bearer $ADMIN_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"minion_id\": \"$NODE\", \"hostname\": \"$NODE\"}" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  node_id={d[\"node_id\"]}'); print(f'  token={d[\"token\"]}')"
  echo ""
done
```

---

## Step 8 — Configure Salt Pillar with Node Tokens

### One pillar file per node

Create `/srv/salt/pillar/<node>.sls` for each Mac Mini:

```bash
# Example for mac-mini-01
cat > /srv/salt/pillar/mac-mini-01.sls << 'EOF'
fleet_platform:
  ingest_url: http://10.0.0.1:8000/api/v1/ingest
  node_token: PASTE_TOKEN_HERE
EOF
```

The `ingest_url` must end with `/api/v1/ingest` — the states append `/grains` and `/sbom/{minion_id}` to it.

### Pillar top file

```yaml
# /srv/salt/pillar/top.sls
base:
  'mac-mini-01':
    - mac-mini-01
  'mac-mini-02':
    - mac-mini-02
  'mac-mini-03':
    - mac-mini-03
  'builder-01':
    - builder-01
  'builder-02':
    - builder-02
  # Add every registered node here
```

### Verify pillar is available on the minion

```bash
sudo salt 'mac-mini-01' pillar.get fleet_platform
# mac-mini-01:
#   ----------
#   ingest_url: http://10.0.0.1:8000/api/v1/ingest
#   node_token: xK9mP2...
```

If the token is missing, check `/srv/salt/pillar/top.sls` and that `auto_accept` is on (or the key was accepted in Step 6).

---

## Step 9 — Test Grain Reporting

Push grains from one node manually:

```bash
sudo salt 'mac-mini-01' state.apply base.grain_report
```

Expected output:
```
mac-mini-01:
----------
  ID: report_grains_to_fleet_platform
  Function: module.run
  Result: True
  Comment: Module function http.query executed
  Changes:
    ----------
    ret:
      ----------
      status: 200
      body: {"status":"accepted","node_id":"..."}
```

Verify the node appeared in Fleet Platform:
```bash
curl -s $FLEET_API/api/v1/nodes \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  | python3 -c "import sys,json; [print(n['hostname'], n['status'], n['ip_address']) for n in json.load(sys.stdin)['items']]"
```

Push grains from all nodes:
```bash
sudo salt '*' state.apply base.grain_report
```

---

## Step 10 — Auto-report on Minion Start (Reactor)

Add this to `/etc/salt/master`:

```yaml
reactor:
  - 'salt/minion/*/start':
    - /srv/salt/reactors/grain_report.sls
```

Create the reactor file:

```bash
sudo mkdir -p /srv/salt/reactors

cat > /srv/salt/reactors/grain_report.sls << 'EOF'
# Triggered when any minion connects. Runs grain_report on that minion.
report_grains_on_start:
  local.state.apply:
    - tgt: {{ data['id'] }}
    - arg:
      - base.grain_report
EOF
```

Restart the master to load the reactor:
```bash
sudo systemctl restart salt-master
```

Now every Mac Mini automatically pushes its grains to Fleet Platform whenever it boots or reconnects to the master. The API queues a drift computation task immediately after ingestion.

---

## Step 11 — Install Syft for SBOM Scans

On each Mac Mini (via Salt):

```bash
sudo salt '*' cmd.run 'brew install syft'

# Verify
sudo salt '*' cmd.run 'syft version'
# mac-mini-01: syft 1.3.0
```

---

## Step 12 — Test SBOM Scan

Trigger a manual scan on one node:

```bash
sudo salt 'mac-mini-01' state.apply base.sbom_scan
```

This will take 1–5 minutes (Syft scans the full filesystem). Expected output:

```
mac-mini-01:
----------
  ID: sbom_scan_run
  Function: cmd.run
  Result: True
  Comment: Command ran as expected
  Changes: ...

  ID: sbom_upload
  Function: module.run
  Result: True
  Comment: Module function http.query executed
  Changes:
    ----------
    ret:
      ----------
      status: 202
      body: {"status":"queued"}

  ID: sbom_cleanup
  Function: cmd.run
  Result: True
```

Verify in Fleet Platform:
```bash
curl -s $FLEET_API/api/v1/sbom/$(curl -s $FLEET_API/api/v1/nodes -H "Authorization: Bearer $ADMIN_TOKEN" | python3 -c "import sys,json; print(json.load(sys.stdin)['items'][0]['id'])")/latest \
  -H "Authorization: Bearer $ADMIN_TOKEN" | python3 -m json.tool
```

---

## Step 13 — Schedule Nightly SBOM Scans

Add a schedule to each node's pillar file (or a shared pillar file):

```yaml
# /srv/salt/pillar/mac-mini-01.sls
fleet_platform:
  ingest_url: http://10.0.0.1:8000/api/v1/ingest
  node_token: PASTE_TOKEN_HERE

schedule:
  fleet_sbom_nightly:
    function: state.apply
    args:
      - base.sbom_scan
    when: "02:00am"
    enabled: True
```

Apply the schedule to the minion:
```bash
sudo salt 'mac-mini-01' saltutil.refresh_pillar
sudo salt 'mac-mini-01' schedule.list
# fleet_sbom_nightly: enabled, next fire: 02:00
```

---

## Step 14 — Start Celery Workers

Celery workers must be running on the control plane to process drift and SBOM tasks that the API queues.

```bash
cd /home/dk/Documents/git/kri
source .venv/bin/activate

# Drift worker — processes compute_drift tasks queued after grain ingestion
celery -A fleet_platform.workers.celery_app worker \
  --queues=drift \
  --concurrency=4 \
  --loglevel=info \
  --logfile=/var/log/fleet/celery-drift.log \
  --detach

# SBOM worker — indexes CycloneDX documents uploaded by Mac Minis
celery -A fleet_platform.workers.celery_app worker \
  --queues=sbom \
  --concurrency=2 \
  --loglevel=info \
  --logfile=/var/log/fleet/celery-sbom.log \
  --detach

# Maintenance worker + beat scheduler (stale-node sweep, archive old SBOM scans)
celery -A fleet_platform.workers.celery_app worker \
  --queues=maintenance \
  --concurrency=1 \
  --detach

celery -A fleet_platform.workers.celery_app beat \
  --loglevel=info \
  --logfile=/var/log/fleet/celery-beat.log \
  --detach
```

Check workers are alive:
```bash
celery -A fleet_platform.workers.celery_app inspect active
```

---

## End-to-End Flow

```
Mac Mini boots
  └─ Salt Minion starts → master receives salt/minion/mac-mini-01/start
       └─ Reactor fires: state.apply base.grain_report
            └─ POST /api/v1/ingest/grains   (X-Node-Token: <token>)
                 └─ API queues: compute_drift.delay(node_id)
                      └─ Celery drift worker:
                           grains vs global YAML baseline
                           → writes DriftRecord
                           → updates Node.drift_score
                           → Dashboard shows node with drift badge

2:00am daily
  └─ Salt schedule fires: state.apply base.sbom_scan
       └─ Syft scans / → /tmp/sbom-<id>.json
            └─ POST /api/v1/ingest/sbom/mac-mini-01
                 └─ API saves temp file, queues index_sbom.delay()
                      └─ Celery SBOM worker:
                           parses CycloneDX JSON
                           → writes SBOMScan + SBOMComponent rows
                           → archives old scans (keep last 3)
                           → SBOM Explorer searchable immediately

Every 5 minutes
  └─ Celery maintenance worker: mark_stale_nodes()
       → nodes not seen for 15+ minutes → status=stale
       → nodes not seen for 60+ minutes → status=offline
```

---

## Troubleshooting

### Minion not connecting
```bash
# Check master is reachable from the minion
nc -zv 10.0.0.1 4505   # publish port
nc -zv 10.0.0.1 4506   # return port

# Check key was accepted
sudo salt-key -L   # on master
```

### Grain report fails with 401
```bash
# Verify token in pillar
sudo salt 'mac-mini-01' pillar.get fleet_platform:node_token

# Re-register if token was lost (generates a new token)
curl -s -X POST $FLEET_API/api/v1/nodes/register \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"minion_id": "mac-mini-01"}'
```

### Grain report fails with 404 (node not registered)
The minion_id in the grain report must match the minion_id used during registration. Check `grains['id']` on the minion:
```bash
sudo salt 'mac-mini-01' grains.get id
# mac-mini-01
```
If it doesn't match, update the `id:` field in the minion config and re-register.

### SBOM scan hangs
Syft scanning the full filesystem (`/`) can take 2–5 minutes on a Mac with many installed packages. If it times out, increase the timeout in `sbom_scan.sls`:
```yaml
sbom_scan_run:
  cmd.run:
    - timeout: 600   # 10 minutes
```

### Drift score not updating after grain report
Check the Celery drift worker is running:
```bash
celery -A fleet_platform.workers.celery_app inspect active --destination celery@$(hostname)
```
Check the task queue:
```bash
celery -A fleet_platform.workers.celery_app inspect reserved
```

---

## Firewall Rules

Open these ports on the **Salt Master** host:

| Port | Protocol | Direction | Purpose |
|------|----------|-----------|---------|
| 4505 | TCP | Minion → Master | Salt publish bus (master pushes commands) |
| 4506 | TCP | Minion → Master | Salt return bus (minions push results) |
| 8000 | TCP | Minion → API | Fleet Platform ingest endpoints |

---

## Adding a New Node

1. Install Salt Minion (Step 4)
2. Configure `/usr/local/etc/salt/minion` with `master:` and `id:` (Step 5)
3. Start the minion — key appears in `salt-key -L` on master
4. Accept the key: `sudo salt-key -a <node-name>` (Step 6)
5. Register in Fleet Platform: `POST /api/v1/nodes/register` → save token (Step 7)
6. Create `/srv/salt/pillar/<node>.sls` with token (Step 8)
7. Add to `/srv/salt/pillar/top.sls` (Step 8)
8. Verify: `sudo salt '<node>' state.apply base.grain_report` (Step 9)

The node appears in the Fleet Dashboard within seconds of a successful grain report.
