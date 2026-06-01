# Node System Health, Process Management & Service Management
## Plan for Review — kri Fleet Platform

> **Date:** 2026-05-31 | **Status:** DECISIONS RECORDED — ready for implementation
> **Trigger:** Fleet nodes will host AI models (exo, MLX); need CPU/memory/disk/IO
> profiling, process kill/stop capability, and launchctl service management.

## Decisions Made (2026-05-31)

| # | Question | Decision |
|---|---|---|
| Q1 | Salt master transport | **Native mm1 salt-master only.** `_run_salt()` must call Salt API on mm1 directly, not `docker exec`. Docker salt-master is dead. |
| Q2 | Kill signals | **STOP, KILL, and CONT** — pause/resume without losing state (STOP/CONT), plus hard kill (KILL). |
| Q3 | Service list scope | **All services with search/filter** — filter by domain (user/system/gui) AND by resource type (CPU-heavy, memory-heavy, IOPS, GPU). |
| Q4 | Agent deployment | **Salt state push mechanism** — deploy node_exporter as a Salt state pushed to minions, not Ansible. |
| Q5 | Auto-remediation | **Never auto-kill.** Always human confirmation. High-resource processes trigger email notification to operator. |
| Q6 | Thermal monitoring | **Yes — first-class metric** alongside CPU/RAM/Disk/IO. Apple Neural Engine utilization included. |

---

## 0. Problem Statement

Mac Mini fleet nodes (mm1, mm2) will run AI inference workloads (exo cluster, MLX models, potentially ollama/vllm). These workloads:

- Consume 8–32 GB RAM per loaded model
- Pin CPU to 80–100% during inference
- Generate significant disk I/O (model loading from NVMe)
- Can leave zombie processes if the inference server crashes
- Must coexist with build workloads (Xcode, gradle, fastlane)

**What an operations person needs — in priority order:**

1. **See** — resource usage per node, per process, fleet-wide overview
2. **Identify** — which process is consuming too much (AI model? runaway build?)
3. **Act** — kill/stop that process safely; recommend when to act
4. **Manage services** — start/stop/restart/enable/disable macOS services (launchctl) and any kri-deployed daemons
5. **Prevent** — thresholds, alerts, auto-recommendations before things melt

---

## 1. What Already Exists

`fleet_platform/services/salt_maintenance_svc.py` already collects via `_run_salt()`:

| Metric | Salt call | Status |
|---|---|---|
| Disk usage (%, GB) | `disk.usage` | ✅ |
| Inode usage | `disk.inodeusage` | ✅ |
| Load average | `status.loadavg` | ✅ |
| Memory (vm_stat + hw.memsize) | `cmd.run 'vm_stat'` | ✅ |
| GPU info | `cmd.run 'system_profiler ...'` | ✅ |
| Uptime | `cmd.run 'uptime'` | ✅ |

**Gaps (everything needed for this feature):**
- Per-process list with CPU%, RAM, PID, state, command
- Process kill/terminate
- ANE (Apple Neural Engine) utilization
- Disk I/O throughput (not just capacity)
- Network I/O per interface
- launchctl service list, status, start/stop/enable/disable
- AI process detection and tagging (exo, mlx_lm, ollama)
- Recommendations engine
- Fleet-wide resource overview (all nodes side by side)

---

## 2. Proposed Architecture

### 2.1 Data Collection Strategy

**Decision: Hybrid — Salt for on-demand queries + Prometheus/node_exporter for continuous metrics**

| Use case | Tool | Reason |
|---|---|---|
| Process list, kill, service control | Salt (`cmd.run`, `service.*`) | Existing pattern; on-demand; authoritative |
| Continuous CPU/mem/disk time-series | Prometheus + node_exporter | Prometheus already deployed; historical charts |
| AI model detection | Salt `cmd.run 'ps aux'` | Pattern-match against known AI process names |
| Real-time resource snapshot | Salt poll on page load | Acceptable latency (1–3s) for an operator dashboard |

**node_exporter:** Already deployed in the monitoring namespace? If not, deploy as a Salt state on each minion — a single `.sls` file. It exposes `/metrics` on port 9100; Prometheus scrapes it.

**Salt master transport — DECIDED:** Docker salt-master is removed. `_run_salt()` must call the Salt API on mm1 directly using HTTP (`http://mm1-ip:8080`). The existing `salt_maintenance_svc.py` `docker exec` approach must be replaced. Abstract behind a single `_run_salt()` call; all callers stay unchanged. Salt API authentication uses the existing `kri_salt_api_password`.

### 2.2 Backend Services

**New file:** `fleet_platform/services/node_system_svc.py`

Extends the existing pattern from `salt_maintenance_svc.py`:

```python
# Process list
def collect_processes(target: str) -> list[ProcessInfo]:
    """Top 30 processes by memory. Uses ps aux on macOS."""
    raw = _run_salt("cmd.run", target,
        args=["ps aux -r | head -31 | awk 'NR>1 {print $1,$2,$3,$4,$11}'"])
    return parse_processes(raw, target)

# Kill a process
def kill_process(target: str, pid: int, signal: str = "TERM") -> bool:
    """Send signal to PID. Returns True if salt command succeeded."""
    raw = _run_salt("cmd.run", target, args=[f"kill -{signal} {pid}"])
    return bool(raw.get(target))

# Disk I/O snapshot
def collect_disk_io(target: str) -> dict:
    raw = _run_salt("cmd.run", target, args=["iostat -d 1 2 | tail -2"])
    return parse_disk_io(raw, target)

# Network I/O
def collect_network_io(target: str) -> dict:
    raw = _run_salt("cmd.run", target, args=["netstat -ib | head -20"])
    return parse_network_io(raw, target)

# launchctl service list
def collect_services(target: str, domain: str = "system") -> list[ServiceInfo]:
    raw = _run_salt("cmd.run", target,
        args=[f"launchctl list | awk '{{print $1, $2, $3}}'"])
    return parse_services(raw, target)

# Service action
def service_action(target: str, service_name: str,
                   action: str) -> ServiceActionResult:
    """action: start|stop|restart|enable|disable|status"""
    # Uses salt service module — abstracts launchctl on macOS, systemctl on Linux
    if action in ("start", "stop", "restart"):
        fn = f"service.{action}"
        raw = _run_salt(fn, target, args=[service_name])
    elif action == "enable":
        raw = _run_salt("service.enable", target, args=[service_name])
    elif action == "disable":
        raw = _run_salt("service.disable", target, args=[service_name])
    elif action == "status":
        raw = _run_salt("service.status", target, args=[service_name])
    return parse_service_action_result(raw, target, action)
```

### 2.3 New API Endpoints

**Router:** `fleet_platform/api/routes/system.py`

```
GET  /api/v1/nodes/{node_id}/system/snapshot     — resource snapshot (CPU, mem, disk, load)
GET  /api/v1/nodes/{node_id}/system/processes    — process list (top 30 by mem)
POST /api/v1/nodes/{node_id}/system/processes/{pid}/kill  — kill process (operator+)
GET  /api/v1/nodes/{node_id}/system/disk-io      — disk throughput snapshot
GET  /api/v1/nodes/{node_id}/system/services     — launchctl service list
POST /api/v1/nodes/{node_id}/system/services/{name}/action  — service control (operator+)
GET  /api/v1/fleet/system/overview               — all nodes: CPU/mem/disk/top-process
GET  /api/v1/nodes/{node_id}/system/recommendations  — threshold-based recommendations
```

### 2.4 Recommendations Engine

Rule-based first (reliable, auditable), statistical later.

**Rules:**
```python
RULES = [
    Rule(
        id="mem_critical",
        condition=lambda m: m.memory_pct > 90,
        severity="critical",
        message="Memory critical ({memory_pct}%) on {hostname}. "
                "Consider stopping: {top_mem_process}",
        action_hint="kill_process",
    ),
    Rule(
        id="mem_ai_model_dominant",
        condition=lambda m: m.ai_process_mem_gb > 20,
        severity="warning",
        message="AI model using {ai_process_mem_gb}GB RAM ({ai_process_name}). "
                "Free memory: {free_mem_gb}GB. Offload if build jobs are queued.",
        action_hint="stop_service",
    ),
    Rule(
        id="disk_near_full",
        condition=lambda m: m.disk_root_pct > 85,
        severity="warning",
        message="Disk {disk_root_pct}% full on {hostname}. "
                "Check ~/.cache/huggingface and /tmp",
        action_hint="investigate",
    ),
    Rule(
        id="cpu_sustained_high",
        condition=lambda m: m.load_1m > m.cpu_core_count * 1.5,
        severity="warning",
        message="Load average {load_1m} exceeds core count ({cpu_core_count}). "
                "Top process: {top_cpu_process}",
        action_hint="investigate",
    ),
    Rule(
        id="thermal_throttling",
        condition=lambda m: m.thermal_pressure in ("warn", "critical"),
        severity="warning",
        message="Mac Mini {hostname} is thermal throttling ({thermal_pressure}). "
                "Performance may be degraded. Reduce concurrent AI load.",
        action_hint="reduce_load",
    ),
    Rule(
        id="ai_process_zombie",
        condition=lambda p: p.state == "Z" and p.name in AI_PROCESS_NAMES,
        severity="high",
        message="Zombie AI process ({name}, PID {pid}) on {hostname}. "
                "Parent process may have crashed.",
        action_hint="kill_process",
    ),
]
```

**AI process detection** — pattern-match by executable name:
```python
AI_PROCESS_NAMES = {
    "exo", "mlx_lm.generate", "mlx_lm", "ollama", "ollama_llama_server",
    "vllm.entrypoints.openai.api_server", "python3",  # ← needs secondary check for mlx imports
    "llama.cpp", "llama-server", "ggml-metal",
}
# Secondary check: if process name is "python3", check cmdline for mlx/transformers/vllm
```

---

## 3. Frontend Pages

### 3.1 Node System Health Tab (in NodeDetail)

Add a **"System"** tab to the existing NodeDetail tabs (currently: Overview, Executions, Secrets, Drift).

**Layout:**

```
┌─ Resource Gauges (4 cards) ──────────────────────────────┐
│  CPU Load    Memory      Disk        Network I/O          │
│  ████░░ 65%  ████░ 82%  ██░░ 45%    ↑ 1.2MB/s ↓ 0.3MB/s │
└──────────────────────────────────────────────────────────┘

┌─ Recommendations ────────────────────────────────────────┐
│  ⚠ Memory 82% — exo using 18GB. Free: 4GB.             │
│    [Stop exo service]  [Kill process 2341]              │
└──────────────────────────────────────────────────────────┘

┌─ Processes ──────────────────────── [Refresh] [↑ Sort by Mem] ──┐
│  PID    Name              CPU%   Mem (GB)  State  Tags           │
│  2341   exo               12.4%  18.2GB    S      🤖 AI Model    │
│  4521   Xcode             4.2%   3.1GB     S      🔨 Build       │
│  891    com.apple.mdworker 0.1%   0.2GB    S      —             │
│  ...                                                              │
│  [Kill] button per row (confirm dialog, operator+ only)          │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 Service Manager Tab (in NodeDetail)

Add a **"Services"** tab to NodeDetail.

**Layout:**

```
┌─ Filter: [All ▾] [🔍 Search] ─────── Domain: [System ▾] [User] ──┐
│                                                                    │
│  Service                    Status    PID    Actions              │
│  ─────────────────────────────────────────────────────────────── │
│  com.kri.exo-worker         ● Running  2341  [Stop] [Restart]     │
│  com.apple.AirPlayXPCHelper ● Running  891   [Stop] [Restart]     │
│  homebrew.mxcl.postgresql   ○ Stopped  —     [Start]             │
│  com.kri.salt-minion        ● Running  1204  [Stop] [Restart]     │
│                                                                    │
│  Legend: ● Running  ○ Stopped  ⚠ Error  — Disabled               │
│                                                                    │
│  [Enable on Boot] [Disable on Boot] — requires admin role         │
└────────────────────────────────────────────────────────────────────┘

┌─ Service Detail (slide-in panel) ─────────────────────────────────┐
│  Name:     com.kri.exo-worker                                      │
│  Domain:   System                                                  │
│  PID:      2341                                                    │
│  Status:   Running  Last exit: 0  Exit count: 0                    │
│  Plist:    /Library/LaunchDaemons/com.kri.exo-worker.plist        │
│                                                                    │
│  [Start] [Stop] [Restart] [Enable] [Disable]                      │
│  [View Plist]  — read-only JSON viewer of the .plist              │
└────────────────────────────────────────────────────────────────────┘
```

### 3.3 Fleet Resource Overview (New Page)

**Route:** `/fleet/system` — accessible from main nav under "Fleet"

**Layout:**

```
Fleet System Overview                          [Refresh All] [Auto: 30s ▾]

┌─ mm1 ──────────────────────┐  ┌─ mm2 ──────────────────────┐
│ ● Online                   │  │ ○ Offline (3h ago)         │
│ CPU  ████████░░ 80%        │  │ —                          │
│ RAM  ████░░░░░░ 45%        │  │ —                          │
│ Disk ██░░░░░░░░ 23%        │  │ —                          │
│ Top: exo (18GB, 12% CPU)   │  │                            │
│ 🤖 AI load: High           │  │                            │
│ ⚠ CPU sustained >80% 5m   │  │                            │
│ [View Details]             │  │ [Last known metrics ▾]     │
└────────────────────────────┘  └────────────────────────────┘
```

---

## 4. launchctl Specifics (macOS)

Salt's `service` module wraps launchctl but has limitations. For full control:

| Desired action | Salt module | Raw launchctl |
|---|---|---|
| List all services | `cmd.run 'launchctl list'` | `launchctl list` |
| Service status | `service.status <label>` | `launchctl print system/<label>` |
| Start | `service.start <label>` | `launchctl kickstart system/<label>` |
| Stop | `service.stop <label>` | `launchctl kill SIGTERM system/<label>` |
| Restart | `service.restart <label>` | `launchctl kickstart -k system/<label>` |
| Enable (boot) | `service.enable <label>` | `launchctl enable system/<label>` |
| Disable (boot) | `service.disable <label>` | `launchctl disable system/<label>` |
| Fully unload | N/A | `launchctl bootout system/<label>` |
| Load a plist | N/A | `launchctl bootstrap system /path/to.plist` |

**Domains to expose in UI:**
- `system` — runs as root, persists across user sessions (most daemons)
- `user/<uid>` — runs as user, e.g., `user/501` for dk's agents
- `gui/<uid>` — runs in GUI session (screen-sharing, app launch agents)

**Safety guardrails (non-negotiable):**
```python
PROTECTED_SERVICES = {
    "com.apple.coreduetd",
    "com.apple.loginwindow",
    "com.apple.WindowServer",
    "com.apple.sshd",          # ← do not disable — locks out operator
    "com.apple.SystemConfiguration.SCNetworkReachability",
    # ... full list to be curated
}

def service_action(target, service_name, action):
    if service_name in PROTECTED_SERVICES and action in ("stop", "disable"):
        raise ValueError(f"Service {service_name} is protected and cannot be {action}d via kri")
```

---

## 5. Security Considerations

| Risk | Mitigation |
|---|---|
| Process kill used to disrupt build jobs | `operator` role required for kill; audit log every kill with actor, PID, process name, timestamp |
| launchctl disable locks out SSH | `com.apple.sshd` in PROTECTED_SERVICES; cannot be stopped or disabled via kri |
| Arbitrary command injection via service name | Whitelist validation: service name must match `^[a-zA-Z0-9._\-]{1,128}$` |
| Killing critical OS processes | PROTECTED_SERVICES list; confirm dialog on frontend |
| Viewing full process list exposes sensitive cmdline args | `ps` output sanitised — strip env vars and credential-looking args before DB storage or API response |

---

## 6. Implementation Phases

### Phase 1 — System Snapshot + Process List (M, ~3 days)
- `node_system_svc.py` with process list, disk I/O, network I/O
- New API endpoints: snapshot, processes
- NodeDetail "System" tab with resource gauges + process table
- No kill, no service management yet

### Phase 2 — Process Kill + Recommendations (M, ~2 days)
- `kill_process()` in service layer
- `recommendations()` with 6 rules above
- Kill button in UI (with confirm dialog)
- Recommendations panel in System tab

### Phase 3 — Service Manager (L, ~4 days)
- `collect_services()` and `service_action()` in service layer
- `POST /services/{name}/action` endpoint
- NodeDetail "Services" tab with full launchctl management
- PROTECTED_SERVICES list + audit logging

### Phase 4 — Fleet Overview (M, ~2 days)
- `/fleet/system` page with node grid
- Auto-refresh polling (30s default, configurable)
- AI workload tagging (exo, mlx, ollama badges)

### Phase 5 — Prometheus/node_exporter Historical Charts (L, ~3 days)
- Deploy node_exporter via Salt state on each minion
- Add ServiceMonitor in each node's namespace
- Grafana panels: CPU/mem/disk time series per node
- Embed Grafana panel iframes in NodeDetail "System" tab or link out

---

## 7. Open Questions for Discussion

**Q1 — Salt master migration timing**
The `_run_salt()` function currently uses `docker exec deploy-salt-master-1`. When salt-master moves to mm1 (native), this breaks. Should Phase 1 use the current docker exec pattern, or wait for and implement a real Salt API call first?

**Q2 — Process kill granularity**
Should the kill action only allow signals TERM and KILL, or also STOP/CONT (pause/resume)? STOP is safer than KILL for AI models (it pauses them, doesn't lose state) but adds complexity.

**Q3 — Service management scope**
Should the service manager show ALL launchctl services (hundreds on macOS) or only:
- (a) kri-deployed services (filtered by `com.kri.*` label prefix)
- (b) User-bookmarked services
- (c) All services with a search/filter (preferred for ops but noisy)

**Q4 — node_exporter deployment**
Do we deploy node_exporter via the existing Salt states (clean, repeatable) or as a launchd plist via Ansible (since we now have the playbook runner)? Ansible is arguably more appropriate for "install an agent on a node."

**Q5 — Auto-remediation**
Should the recommendations engine eventually be able to auto-kill runaway processes (e.g., if memory > 95% and process is clearly runaway based on growth rate) or always require human confirmation? The safe default is always-confirm, but worth discussing for 4am incidents.

**Q6 — Thermal monitoring**
macOS `powermetrics` gives ANE utilization and thermal pressure. We already call it in `salt_maintenance_svc.py`. Should thermal pressure be a first-class metric in the System tab (alongside CPU/RAM/Disk), given AI models cause significant thermal load?

---

## 8. Files to Create / Modify

| File | Action | Phase |
|---|---|---|
| `fleet_platform/services/node_system_svc.py` | **New** | 1 |
| `fleet_platform/api/routes/system.py` | **New** | 1 |
| `fleet_platform/schemas/system.py` | **New** | 1 |
| `fleet_platform/api/main.py` | Register system router | 1 |
| `frontend/src/api/system.ts` | **New** | 1 |
| `frontend/src/pages/NodeDetail.tsx` | Add System + Services tabs | 1, 3 |
| `frontend/src/pages/FleetSystemPage.tsx` | **New** | 4 |
| `frontend/src/App.tsx` | Add `/fleet/system` route | 4 |
| Salt state: `salt/states/base/node_exporter.sls` | **New** | 5 |
| `tests/unit/test_node_system_svc.py` | **New** | 1 |
| `tests/unit/test_service_manager.py` | **New** | 3 |
| `tests/integration/test_system_api.py` | **New** | 1, 3 |
