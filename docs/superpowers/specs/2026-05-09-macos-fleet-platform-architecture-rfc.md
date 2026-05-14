# macOS Fleet Management and Observability Platform — Architecture RFC

**RFC-001 | Status: Draft | Date: 2026-05-09**
**Classification: Internal Engineering Document**

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Overview](#2-architecture-overview)
3. [Final Recommendation: SaltStack](#3-final-recommendation-saltstack)
4. [Ansible vs SaltStack Analysis](#4-ansible-vs-saltstack-analysis)
5. [System Diagram](#5-system-diagram)
6. [Frontend Architecture](#6-frontend-architecture)
7. [Backend Architecture](#7-backend-architecture)
8. [Event and Data Flow](#8-event-and-data-flow)
9. [Database Design](#9-database-design)
10. [Drift Detection Design](#10-drift-detection-design)
11. [SBOM Pipeline](#11-sbom-pipeline)
12. [API Design](#12-api-design)
13. [Security Architecture](#13-security-architecture)
14. [Scalability Strategy](#14-scalability-strategy)
15. [Operational Considerations](#15-operational-considerations)
16. [Failure Handling](#16-failure-handling)
17. [GitOps Workflow](#17-gitops-workflow)
18. [Repository Structure](#18-repository-structure)
19. [Future Enhancements](#19-future-enhancements)
20. [Risks and Tradeoffs](#20-risks-and-tradeoffs)

---

## 1. Executive Summary

This RFC defines the full architecture for a production-grade macOS fleet management and observability platform targeting an initial fleet of 40+ Mac Minis, designed from the ground up to scale to 1000+ nodes without architectural rework.

The platform is a control plane and observability layer — not a custom MDM replacement. It delegates all node execution to SaltStack and provides fleet-wide visibility, drift detection, SBOM inspection, grouping, and execution history through a React frontend backed by a Python/FastAPI monolith.

**Core architectural decisions:**

| Decision | Choice | Rationale |
|---|---|---|
| Configuration management | SaltStack | Native event bus, structured grains, macOS execution modules, push-based state |
| Backend | Python + FastAPI (monolith) | Async-native, OpenAPI built-in, team's Python fluency, single deployable |
| Primary database | PostgreSQL 16 | Relational correctness, JSONB for flexible facts, ecosystem maturity |
| Time-series | TimescaleDB extension | Hypertables for drift/fact history — no second DB to operate |
| Task queue | Celery + Redis | Drift computation, SBOM ingestion, background maintenance workers |
| SBOM format | CycloneDX JSON (via Syft) | Richer component metadata, native Syft output, active tooling ecosystem |
| Frontend | React + Tailwind + React Query + Zustand | Server-state caching built-in, no Redux ceremony |
| Auth | JWT + RBAC | Stateless, scales horizontally, works across k8s replicas |
| Deployment | Docker Compose → Helm chart | Zero-friction start, clean k8s migration path |
| Desired state | Git-backed YAML baselines | Immutable audit trail, diff-able, GitOps-native |

The control plane runs on the same LAN as the fleet, with direct Salt ZeroMQ connectivity to all minions. It is deployment-agnostic: runnable on a single Linux server, a dedicated Mac Mini, or as containerized k8s workloads.

---

## 2. Architecture Overview

The platform is composed of five logical layers:

```
┌────────────────────────────────────────────────────┐
│  PRESENTATION LAYER                                │
│  React + Tailwind (Fleet Dashboard, Drift,         │
│  SBOM Explorer, Group Explorer, Exec History)      │
└────────────────────┬───────────────────────────────┘
                     │ HTTPS / REST
┌────────────────────▼───────────────────────────────┐
│  API LAYER                                         │
│  FastAPI — nodes, groups, drift, sbom,             │
│  executions, auth, audit                           │
└──────────┬─────────────────────┬───────────────────┘
           │ async DB writes     │ task dispatch
┌──────────▼──────────┐  ┌──────▼──────────────────┐
│  WORKER LAYER        │  │  INGEST LAYER            │
│  Celery workers:     │  │  /ingest/* endpoints:    │
│  drift computation   │  │  grain sync receiver     │
│  sbom indexing       │  │  event relay             │
│  node health sweep   │  │  sbom upload handler     │
└──────────┬──────────┘  └──────┬──────────────────┘
           │                    │
┌──────────▼────────────────────▼──────────────────┐
│  PERSISTENCE LAYER                                │
│  PostgreSQL + TimescaleDB                         │
│  Redis (Celery broker + API cache)                │
│  Git repository (desired state baselines)         │
└──────────────────────────────────────────────────┘
           │
┌──────────▼────────────────────────────────────────┐
│  EXECUTION LAYER  (outside the platform boundary) │
│  SaltStack Master + Minions on Mac Minis          │
│  Salt states, grains, event bus, returner         │
└───────────────────────────────────────────────────┘
```

**What the platform does NOT own:**
- SSH orchestration
- Remote shell execution
- Package installation
- Service management
- Any node-side daemon

All of the above are SaltStack's responsibility. The platform is a consumer of Salt's output, not a replacement for it.

---

## 3. Final Recommendation: SaltStack

**Use SaltStack. Not Ansible.**

For the specific requirements of this platform — real-time drift detection, event-driven state reporting, structured fact collection, and macOS compatibility — SaltStack is the clearly superior choice for a greenfield deployment.

The three decisive factors:

**1. Native event bus eliminates polling architecture.**
Salt's ZeroMQ event bus emits structured events on every grain sync, highstate execution, job completion, and beacon trigger. The platform subscribes to this stream. Drift detection runs as a reaction to state change, not on a cron schedule. At 1000 nodes, polling-based drift detection creates a thundering herd problem that is architecturally difficult to solve. Salt's reactor system makes it a non-problem.

**2. Salt grains provide a structured, queryable fact schema out of the box.**
On a macOS minion, `grains.items` returns a structured dictionary: OS version, hardware model, CPU count, RAM, disk, installed packages (via `brew` grain module), running services, network interfaces. This data is available without writing a single playbook. With Ansible, you write `setup` module tasks and normalize the output yourself on every collection run.

**3. Salt returners enable push-based result reporting.**
A custom Salt returner (a single Python file) intercepts every execution result and POSTs it as structured JSON to the platform's ingest API. This gives real-time execution history with no polling. Ansible equivalents (callback plugins + AWX webhooks) achieve the same result with significantly more configuration surface area.

The tradeoff is operational: Salt master is a stateful service with a key management lifecycle. At 40 nodes, this is a non-issue. At 1000 nodes, it requires a deliberate key rotation workflow (documented in Section 15).

---

## 4. Ansible vs SaltStack Analysis

This is a genuine engineering comparison, not a marketing comparison.

### Architecture Model

| Dimension | SaltStack | Ansible |
|---|---|---|
| Execution model | Push (master → minions via ZeroMQ) | Push (control node → targets via SSH) |
| Persistent connection | Yes — minion daemon maintains ZeroMQ connection | No — SSH connection per run |
| Fact collection | Continuous via grains (cached on minion) | Per-run via setup module |
| Event system | Native — ZeroMQ event bus, reactor, beacons | None native (AWX webhooks approximate it) |
| State representation | Structured grain dictionary, persistent | Ephemeral per-run facts |
| Result reporting | Returners — pluggable push to external systems | Callback plugins — file/stdout/webhook |

### macOS Compatibility

SaltStack has native execution modules for macOS:
- `brew` — Homebrew package management
- `macpackage` — .pkg installer management
- `service` — launchctl service management (macOS-aware)
- `mac_user`, `mac_group` — user/group management via dscl
- `osxdefaults` — macOS defaults system

Ansible has macOS community modules that are generally reliable but not as deeply integrated. The `community.general.homebrew` module works, but fact normalization for macOS hardware facts requires more custom work.

**Winner: SaltStack** for macOS-specific management depth.

### Event-Driven Capability

SaltStack's event system is production-grade:

```
minion grain sync
    └─► salt/minion/{id}/grain_sync event on event bus
          └─► reactor: fleet_platform/grain_received
                └─► runner: http.query POST /api/v1/ingest/grains
```

Beacons add proactive monitoring:
```yaml
# /etc/salt/minion.d/beacons.conf
beacons:
  diskusage:
    - interval: 60
    - /: 85%   # fire event if disk > 85%
  service:
    - interval: 30
    - com.apple.screensharing:
        running: False  # alert if screen sharing is enabled
```

Ansible has no equivalent. AWX/Semaphore can trigger on webhooks, but there is no minion-side event emission without building a custom daemon — which contradicts the constraints of this platform.

**Winner: SaltStack** — not even close for event-driven requirements.

### Operational Complexity

| Aspect | SaltStack | Ansible |
|---|---|---|
| Initial setup | Salt master + minion install, key accept | SSH key distribution only |
| Ongoing ops | Key management, ZeroMQ port (4505/4506) | SSH access maintenance |
| Failure blast radius | Salt master down → no push execution, grains stale | Control node down → no execution |
| Debugging | `salt-run jobs.lookup_jid {jid}`, event bus debug | `ansible -vvv`, callback log files |
| Secrets | Salt pillar with GPG or Vault integration | Ansible Vault |
| macOS minion install | `brew install salt` or pkg installer | Agentless (no install) |
| Learning curve | Higher — master/minion/state/pillar/grain concepts | Lower — YAML playbooks |

Ansible's agentless model is genuinely simpler to bootstrap. The first run works in 10 minutes. Salt requires key acceptance workflow per minion. For a 40-node fleet managed by experienced engineers, this is a one-time cost, not an ongoing burden.

**Ansible wins on initial simplicity. SaltStack wins on long-term operational capability.**

### Fleet Visibility

| Capability | SaltStack | Ansible |
|---|---|---|
| Structured facts | grains — always available, persistent | setup module facts — available per run |
| Fleet-wide fact query | `salt '*' grains.items` — instant | Requires running setup module on all hosts |
| Real-time state | grain changes emit events | No equivalent |
| Offline detection | minion heartbeat expires → detected | No native detection |
| Custom facts | `_grains/` directory, auto-loaded | custom fact scripts in `/etc/ansible/facts.d/` |

### Scaling Behavior

| Scale | SaltStack | Ansible |
|---|---|---|
| 40 nodes | Trivial — single master | Trivial — single control node |
| 200 nodes | Still trivial | Still manageable with parallelism tuning (`forks`) |
| 500 nodes | Master handles comfortably | SSH connection overhead becomes noticeable |
| 1000 nodes | Consider Salt syndic for geo-distribution | `forks=50` with SSH multiplexing required; thundering herd risk on scheduled runs |
| 5000+ nodes | Syndic + multi-master | Becomes a significant operational problem without AWX clustering |

At 1000 nodes, Ansible's stateless SSH model means every scheduled grain collection is 1000 concurrent SSH connections from the control node. With `forks=10` (default), a fact collection sweep takes 100 sequential batches. With `forks=100`, you're stressing the control node's file descriptors. Salt's ZeroMQ persistent connections handle 1000 minions on a single master with minimal overhead.

### Maintenance Burden

SaltStack requires:
- Salt master service management
- Minion key lifecycle (accept, reject, rotate)
- ZeroMQ port accessibility (4505/4506)
- Salt master config versioning
- Periodic minion package updates

Ansible requires:
- Control node Python environment
- SSH key distribution
- Inventory management
- AWX/Semaphore (if using web UI) — adds a database, a web service, and a Redis instance

Both require ongoing maintenance. Salt's maintenance is more predictable once set up. Ansible's maintenance scales linearly with fleet size (more SSH keys, more inventory management).

### Final Verdict

| Criterion | Winner |
|---|---|
| macOS compatibility | SaltStack |
| Event-driven state | SaltStack |
| Real-time drift detection | SaltStack |
| Fleet-wide queries | SaltStack |
| Initial simplicity | Ansible |
| Agentless operation | Ansible |
| Scaling to 1000+ nodes | SaltStack |
| Community size | Ansible |
| Integration depth for this platform | SaltStack |

**Choose SaltStack.** The event bus alone justifies the choice for a drift-detection-focused platform. Every other benefit compounds on top of it.

---

## 5. System Diagram

### Full System Topology

```
┌──────────────────────────────────────────────────────────────────────┐
│                           LAN / SAME NETWORK                         │
│                                                                      │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐      │
│  │   Mac Mini 01   │  │   Mac Mini 02   │  │   Mac Mini N    │      │
│  │                 │  │                 │  │                 │      │
│  │  salt-minion    │  │  salt-minion    │  │  salt-minion    │      │
│  │  syft (daily)   │  │  syft (daily)   │  │  syft (daily)   │      │
│  │  beacons        │  │  beacons        │  │  beacons        │      │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘      │
│           │ ZeroMQ             │                     │               │
│           │ (4505 pub)         │                     │               │
│           │ (4506 ret)         │                     │               │
│           └────────────────────┴─────────────────────┘               │
│                                          │                            │
│                             ┌────────────▼─────────────┐             │
│                             │       SALT MASTER         │             │
│                             │                           │             │
│                             │  ┌─────────────────────┐ │             │
│                             │  │  Event Bus (ZeroMQ)  │ │             │
│                             │  │  Reactor             │ │             │
│                             │  │  Job Cache           │ │             │
│                             │  │  Custom Returner     │ │             │
│                             │  └──────────┬──────────┘ │             │
│                             └─────────────┼────────────┘             │
│                                           │ HTTP POST                 │
│                                           │ /api/v1/ingest/*          │
│  ┌────────────────────────────────────────▼─────────────────────┐    │
│  │                     CONTROL PLANE SERVER                      │    │
│  │                                                               │    │
│  │  ┌─────────────────────────────────────────────────────────┐ │    │
│  │  │                  FastAPI Application                     │ │    │
│  │  │                                                          │ │    │
│  │  │  ┌──────────────┐  ┌───────────────┐  ┌─────────────┐  │ │    │
│  │  │  │  Ingest API   │  │  Fleet API    │  │  Auth API   │  │ │    │
│  │  │  │  /ingest/*    │  │  /api/v1/*    │  │  /auth/*    │  │ │    │
│  │  │  └──────┬────────┘  └───────┬───────┘  └──────┬──────┘  │ │    │
│  │  │         │                   │                   │         │ │    │
│  │  │  ┌──────▼───────────────────▼─────────────────▼──────┐  │ │    │
│  │  │  │             Service Layer                          │  │ │    │
│  │  │  │  DriftEngine | SBOMParser | GroupResolver | Audit  │  │ │    │
│  │  │  └──────┬─────────────────────────────────────────────┘  │ │    │
│  │  └─────────┼────────────────────────────────────────────────┘ │    │
│  │            │                                                    │    │
│  │  ┌─────────▼────────────────────────────────┐                  │    │
│  │  │         Celery Workers (Redis broker)     │                  │    │
│  │  │                                           │                  │    │
│  │  │  ┌────────────┐  ┌──────────┐  ┌───────┐ │                  │    │
│  │  │  │drift_worker│  │sbom_worker│  │maint  │ │                  │    │
│  │  │  │compute_drift│ │index_sbom │  │beat   │ │                  │    │
│  │  │  └────────────┘  └──────────┘  └───────┘ │                  │    │
│  │  └──────────────────────────────────────────┘                  │    │
│  │                                                                 │    │
│  │  ┌──────────────────────────────────────────┐                  │    │
│  │  │   PostgreSQL 16 + TimescaleDB             │                  │    │
│  │  │                                           │                  │    │
│  │  │  nodes          node_facts (hypertable)   │                  │    │
│  │  │  tags           packages                  │                  │    │
│  │  │  groups         sbom_scans                │                  │    │
│  │  │  group_members  sbom_components           │                  │    │
│  │  │  drift_records (hypertable)               │                  │    │
│  │  │  execution_jobs  execution_results        │                  │    │
│  │  │  audit_events (hypertable)                │                  │    │
│  │  │  users                                    │                  │    │
│  │  └──────────────────────────────────────────┘                  │    │
│  │                                                                 │    │
│  │  ┌──────────────────────────────────────────┐                  │    │
│  │  │   Redis 7                                 │                  │    │
│  │  │   Celery broker | API cache               │                  │    │
│  │  └──────────────────────────────────────────┘                  │    │
│  │                                                                 │    │
│  │  ┌──────────────────────────────────────────┐                  │    │
│  │  │   Git Repository (desired state)          │                  │    │
│  │  │   baselines/  salt/states/  salt/pillar/  │                  │    │
│  │  └──────────────────────────────────────────┘                  │    │
│  └─────────────────────────────────────────────────────────────┘  │    │
│                                                                      │    │
│  ┌───────────────────────────────────────────────────────────────┐ │    │
│  │             React Frontend (served by Nginx)                  │ │    │
│  │  Fleet Dashboard | Node Detail | Drift Explorer | SBOM        │ │    │
│  │  Group Explorer | Execution History                           │ │    │
│  └───────────────────────────────────────────────────────────────┘ │    │
└──────────────────────────────────────────────────────────────────────┘
```

### Salt Returner Data Flow

```
Mac Mini (minion)
  │
  ├── Every 5 min: grain sync
  │     salt-minion → Salt Master (ZeroMQ 4506)
  │       → Reactor: grain_sync event
  │         → Custom returner: HTTP POST /api/v1/ingest/grains
  │           → FastAPI: validate node token, write node_facts
  │             → Celery task: compute_drift(node_id)
  │               → DriftEngine: compare actual vs baseline
  │                 → Write drift_records, update nodes.drift_score
  │
  ├── Every 24h (or on demand): SBOM scan
  │     Salt state: syft execution
  │       → CycloneDX JSON output
  │         → Salt returner: HTTP POST /api/v1/ingest/sbom/{node_id}
  │           → FastAPI: parse and queue
  │             → Celery task: index_sbom(node_id, scan_data)
  │               → Write sbom_scans + sbom_components
  │
  └── On state execution: highstate / state.apply
        Salt Master → Minion → execution result
          → Salt Job Cache + Custom returner
            → HTTP POST /api/v1/ingest/executions
              → Write execution_jobs + execution_results
```

---

## 6. Frontend Architecture

### Stack

| Library | Version | Purpose |
|---|---|---|
| React | 18+ | UI framework |
| Tailwind CSS | 3+ | Styling |
| React Query (TanStack) | 5+ | Server state management, caching, pagination |
| Zustand | 4+ | UI-only state (filters, sidebar, modals) |
| TanStack Table | 8+ | Virtualized, sortable, filterable data tables |
| TanStack Virtual | 3+ | Row virtualization for large datasets |
| React Router | 6+ | Client-side routing |
| Recharts | 2+ | Timeline charts, drift history |
| react-diff-viewer-continued | — | Side-by-side drift diff rendering |
| date-fns | 3+ | Date formatting and relative time |
| Vite | 5+ | Build tooling |

### Component Hierarchy

```
App
├── Router
│   ├── AuthGuard (JWT validation, redirect to /login)
│   └── Layout
│       ├── Sidebar
│       │   ├── NavLinks (Fleet, Drift, SBOM, Groups, Executions)
│       │   └── UserMenu (role display, logout)
│       ├── TopBar
│       │   ├── GlobalSearch (debounced, searches nodes + packages)
│       │   └── NotificationBell (offline node alerts)
│       └── PageContent
│           ├── /fleet                → FleetDashboard
│           ├── /nodes/:nodeId        → NodeDetail
│           ├── /drift                → DriftExplorer
│           ├── /sbom                 → SBOMExplorer
│           ├── /groups               → GroupExplorer
│           ├── /groups/:groupId      → GroupDetail
│           ├── /executions           → ExecutionHistory
│           └── /executions/:jobId    → JobDetail
│
├── FleetDashboard
│   ├── FleetStatsBar
│   │   ├── StatCard (Total Nodes)
│   │   ├── StatCard (Online)
│   │   ├── StatCard (Offline / Stale)
│   │   └── StatCard (Avg Drift Score)
│   ├── FleetFilters (group, tag, status, OS version)
│   └── NodeTable
│       ├── columns: hostname, status, OS, drift score, last seen, tags
│       ├── TanStack Table (sortable, filterable)
│       ├── TanStack Virtual (virtualized rows)
│       └── NodeRow → links to /nodes/:nodeId
│
├── NodeDetail
│   ├── NodeHeader
│   │   ├── NodeName + Status badge
│   │   ├── DriftScore (0-100 gauge)
│   │   └── LastSeen (relative time)
│   └── NodeTabs
│       ├── OverviewTab
│       │   ├── HardwareCard (model, CPU, RAM, disk)
│       │   ├── OSCard (version, build, uptime)
│       │   ├── ServicesTable (running/stopped)
│       │   └── TagsEditor (inline tag add/remove for operators)
│       ├── PackagesTab
│       │   ├── PackageSearch (local filter)
│       │   └── PackageTable (name, version, source, installed_at)
│       ├── DriftTab
│       │   ├── DriftSummaryCard (score, severity, baseline ref)
│       │   ├── DriftDiffViewer (desired vs actual, expandable sections)
│       │   └── DriftTimeline (recharts line chart, 30-day history)
│       ├── SBOMTab
│       │   ├── ScanMetadata (scan date, syft version, component count)
│       │   └── ComponentTable (name, version, purl, license)
│       └── ExecutionsTab
│           └── ExecutionTable (job type, status, triggered by, duration)
│
├── DriftExplorer
│   ├── DriftFilters (group, severity tier, date range, baseline)
│   ├── DriftLeaderboard (nodes ranked by drift score, bar chart)
│   └── DriftTable
│       ├── NodeRow → expandable drift detail inline
│       └── DriftDiffViewer (shared component)
│
├── SBOMExplorer
│   ├── FleetPackageSearch (global, searches all nodes)
│   │   └── SearchInput (debounced 300ms, min 3 chars)
│   ├── SearchResults
│   │   ├── PackageRow (name, version, nodes count, purl)
│   │   └── NodeList (which nodes have this package)
│   └── NodeFilter (scope search to group or single node)
│
├── GroupExplorer
│   ├── GroupList (static vs dynamic badge)
│   ├── GroupForm (create/edit, predicate builder for dynamic groups)
│   └── GroupDetail
│       ├── GroupMetadata
│       └── NodeTable (members)
│
└── ExecutionHistory
    ├── JobFilters (type, status, node, date range)
    ├── JobTable (job type, target, triggered_by, status, duration)
    └── JobDetail
        ├── JobMetadata
        └── NodeResultTable (per-node status, stdout/stderr expandable)
```

### State Management

**React Query** handles all server state. Configuration:

```typescript
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,        // 30s default
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
});

// Per-query stale time overrides:
// Fleet overview:     staleTime: 15_000   (15s — dashboard needs freshness)
// Node list:          staleTime: 30_000   (30s)
// Node detail:        staleTime: 60_000   (60s)
// SBOM components:    staleTime: 300_000  (5m — rarely changes)
// Drift history:      staleTime: 60_000   (60s)
// Execution history:  staleTime: 10_000   (10s — active jobs)
```

**Zustand** handles UI-only state:

```typescript
// stores/filterStore.ts
interface FilterStore {
  nodeFilters: { group?: string; tag?: string; status?: string };
  driftFilters: { severity?: string; group?: string };
  sidebarOpen: boolean;
  setNodeFilter: (key: string, value: string) => void;
  resetFilters: () => void;
}
```

No Redux. No Context API for server data. React Query's cache IS the server data store.

### Pagination Strategy

- **Node list**: offset pagination (sortable columns require stable ordering)
  - `GET /api/v1/nodes?page=1&per_page=50&sort=drift_score:desc`
- **Execution history**: cursor pagination (append-only time-series)
  - `GET /api/v1/executions?cursor={last_id}&limit=50&direction=before`
- **SBOM components**: offset with 100-row cap (search results bounded)
- **Drift records timeline**: time-range bounded (`from` + `to` params)

### Virtualized Rendering

TanStack Virtual renders only visible rows. Configuration for the NodeTable:

```typescript
const rowVirtualizer = useVirtualizer({
  count: nodes.length,
  getScrollElement: () => tableContainerRef.current,
  estimateSize: () => 56,     // px per row
  overscan: 10,               // pre-render 10 rows above/below viewport
});
```

This handles 1000-row lists without DOM bloat. Combined with React Query's pagination, the UI never loads more than 50 rows per request, but renders the already-loaded ones efficiently.

### Search Architecture

**Global search** (TopBar):
- Input debounced 300ms
- Hits `GET /api/v1/search?q={term}` — searches node hostname and minion_id (IP search deferred — INET cast is driver-specific)
- Returns categorized results: nodes, packages
- Keyboard navigable (↑↓ + Enter)

**SBOM fleet search**:
- Hits `GET /api/v1/sbom/search?q={term}` — PostgreSQL full-text on `tsvector`
- Results show package name, version, purl, and which nodes have it
- Scoped to group or all-fleet via filter

**Package tab search** (node-scoped):
- Client-side filter (packages already loaded for the node)
- No additional API call

### Error Handling

```typescript
// Centralized error boundary per page
<ErrorBoundary
  fallback={<ErrorState message="Failed to load fleet data" retry={refetch} />}
>
  <NodeTable />
</ErrorBoundary>

// React Query error states surfaced per-component:
if (isError) return <InlineError message={error.message} />;
if (isLoading) return <Skeleton rows={10} />;
```

Mutations (tag updates, group changes) use optimistic updates:

```typescript
const addTagMutation = useMutation({
  mutationFn: addNodeTag,
  onMutate: async (newTag) => {
    await queryClient.cancelQueries({ queryKey: ['node', nodeId] });
    const prev = queryClient.getQueryData(['node', nodeId]);
    queryClient.setQueryData(['node', nodeId], (old) => ({
      ...old,
      tags: [...old.tags, newTag],
    }));
    return { prev };
  },
  onError: (err, newTag, context) => {
    queryClient.setQueryData(['node', nodeId], context.prev);
  },
  onSettled: () => {
    queryClient.invalidateQueries({ queryKey: ['node', nodeId] });
  },
});
```

Read operations are pessimistic — no optimistic updates for data you haven't confirmed from the server.

---

## 7. Backend Architecture

### Monolith Module Structure

The backend is a single FastAPI application with clear internal module boundaries. It is NOT microservices. At 40 nodes, one process is sufficient. At 1000 nodes, you scale the number of instances horizontally — the module boundaries don't change, the deployment topology does.

```
platform/
├── api/
│   ├── main.py              # FastAPI app factory, middleware, lifespan
│   ├── deps.py              # Shared dependencies (DB session, auth)
│   └── routes/
│       ├── nodes.py         # GET/PATCH /api/v1/nodes/*
│       ├── groups.py        # CRUD /api/v1/groups/*
│       ├── drift.py         # GET /api/v1/drift/*, POST compute
│       ├── sbom.py          # GET /api/v1/sbom/*
│       ├── executions.py    # GET /api/v1/executions/*
│       ├── ingest.py        # POST /api/v1/ingest/* (node-auth)
│       ├── auth.py          # POST /auth/login, /auth/refresh
│       ├── audit.py         # GET /api/v1/audit
│       └── health.py        # GET /health
├── core/
│   ├── config.py            # pydantic-settings: env vars
│   ├── auth.py              # JWT encode/decode, RBAC decorators
│   ├── audit.py             # audit_event() writer
│   ├── logging.py           # structlog JSON configuration
│   └── exceptions.py        # HTTPException subclasses
├── models/
│   ├── node.py              # SQLAlchemy ORM: Node, Tag, NodeFact
│   ├── group.py             # Group, GroupMember
│   ├── drift.py             # DriftRecord, DesiredStateBaseline
│   ├── sbom.py              # SBOMScan, SBOMComponent
│   ├── execution.py         # ExecutionJob, ExecutionResult
│   └── audit.py             # AuditEvent
├── schemas/
│   ├── node.py              # Pydantic request/response models
│   ├── group.py
│   ├── drift.py
│   ├── sbom.py
│   └── ingest.py            # Salt returner payload schemas
├── services/
│   ├── drift_engine.py      # Core diff computation logic
│   ├── baseline_loader.py   # Load desired state from Git/DB
│   ├── sbom_parser.py       # CycloneDX JSON → normalized components
│   ├── group_resolver.py    # Dynamic group predicate evaluator
│   └── node_status.py       # Online/stale/offline classification
├── workers/
│   ├── celery_app.py        # Celery app factory, Redis config
│   ├── drift_tasks.py       # compute_drift, batch_drift_recompute
│   ├── sbom_tasks.py        # index_sbom, archive_old_scans
│   └── maintenance.py       # mark_stale_nodes, purge_old_facts (Celery beat)
└── db/
    ├── session.py           # SQLAlchemy async engine + session
    └── migrations/
        └── versions/        # Alembic migrations
```

### Key Service: DriftEngine

```python
# services/drift_engine.py

class DriftEngine:
    def compute(self, node_id: UUID, actual: NodeFacts, baseline: DesiredStateBaseline) -> DriftResult:
        missing_packages = self._diff_missing_packages(actual.packages, baseline.required_packages)
        extra_packages = self._diff_extra_packages(actual.packages, baseline.forbidden_packages)
        version_mismatches = self._diff_versions(actual.packages, baseline.required_packages)
        service_drift = self._diff_services(actual.services, baseline.services)
        config_drift = self._diff_configs(actual.configs, baseline.configs)

        score = self._compute_score(
            missing_packages, extra_packages, version_mismatches,
            service_drift, config_drift
        )

        return DriftResult(
            node_id=node_id,
            baseline_id=baseline.id,
            drift_score=score,
            missing_packages=missing_packages,
            extra_packages=extra_packages,
            version_mismatches=version_mismatches,
            service_drift=service_drift,
            config_drift=config_drift,
        )

    def _compute_score(self, *drift_categories) -> int:
        weights = {
            'missing_package': 20,
            'extra_package': 10,
            'version_major': 15,
            'version_minor': 5,
            'service': 15,
            'config': 20,
        }
        total = sum(len(cat) * weights[cat_key] for cat, cat_key in zip(drift_categories, weights))
        return min(100, total)
```

### Queue Architecture

```
Redis (broker)
├── Queue: default          (grain ingest, tag updates)
├── Queue: drift            (drift computation — higher priority)
├── Queue: sbom             (SBOM indexing — lower priority, large payloads)
└── Queue: maintenance      (node status sweeps, archival — Celery beat)

Worker processes:
├── worker-drift:    concurrency=4, queues=[drift, default]
├── worker-sbom:     concurrency=2, queues=[sbom]
└── beat:            singleton, schedules maintenance tasks
```

Celery beat schedule:

```python
CELERY_BEAT_SCHEDULE = {
    'mark-stale-nodes': {
        'task': 'workers.maintenance.mark_stale_nodes',
        'schedule': crontab(minute='*/5'),   # every 5 min
    },
    'purge-old-facts': {
        'task': 'workers.maintenance.purge_old_facts',
        'schedule': crontab(hour=2, minute=0),  # 2am daily
        'kwargs': {'retain_days': 90},
    },
    'refresh-dynamic-groups': {
        'task': 'workers.maintenance.refresh_dynamic_groups',
        'schedule': crontab(minute='*/10'),  # every 10 min
    },
    'archive-old-sbom-scans': {
        'task': 'workers.sbom_tasks.archive_old_scans',
        'schedule': crontab(hour=3, minute=0),  # 3am daily
        'kwargs': {'retain_days': 30},
    },
}
```

### FastAPI Application Factory

```python
# api/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db_session.init_pool()
    yield
    await db_session.close_pool()

def create_app() -> FastAPI:
    app = FastAPI(title="Fleet Platform API", version="1.0.0", lifespan=lifespan)

    app.add_middleware(CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.include_router(auth_router, prefix="/auth", tags=["auth"])
    app.include_router(nodes_router, prefix="/api/v1/nodes", tags=["nodes"])
    app.include_router(groups_router, prefix="/api/v1/groups", tags=["groups"])
    app.include_router(drift_router, prefix="/api/v1/drift", tags=["drift"])
    app.include_router(sbom_router, prefix="/api/v1/sbom", tags=["sbom"])
    app.include_router(executions_router, prefix="/api/v1/executions", tags=["executions"])
    app.include_router(ingest_router, prefix="/api/v1/ingest", tags=["ingest"])
    app.include_router(audit_router, prefix="/api/v1/audit", tags=["audit"])
    app.include_router(health_router, prefix="/health", tags=["health"])

    return app
```

---

## 8. Event and Data Flow

### Grain Sync Flow (primary state update path)

```
t=0   salt-minion grain sync triggers (every 5 min)
t=1   ZeroMQ: minion sends grain data to salt master (port 4506)
t=2   Salt master: grain data written to job cache
t=3   Reactor: salt/minion/{id}/start event fires
t=4   Custom returner invoked: fleet_platform_return.py
t=5   HTTP POST /api/v1/ingest/grains
        Headers: X-Node-Token: {hashed_token}
        Body: { minion_id, grains: {...}, timestamp }
t=6   FastAPI: token validation → node lookup → 200 OK
t=7   DB write: node_facts row (TimescaleDB hypertable)
t=8   DB update: nodes.last_seen_at, nodes.ip_address, nodes.os_version
t=9   Celery task dispatched: compute_drift(node_id) → queue: drift
t=10  DriftEngine: load latest node_facts + resolve baseline for node
t=11  DriftEngine: compute diff across packages, services, configs
t=12  DB write: drift_records row (TimescaleDB hypertable)
t=13  DB update: nodes.drift_score
t=14  Dynamic groups re-evaluated for this node (if group predicates reference grain fields)
t=15  React Query on frontend: stale data detected on next poll → refetch
```

Total latency from minion grain sync to UI update: ~10-30 seconds (dominated by Celery queue depth).

### SBOM Scan Flow

```
t=0    Celery beat triggers: schedule_sbom_scans() at 2am
t=1    For each node: salt.cmd('node-01', 'state.apply', ['base.sbom_scan'])
t=2    Salt state on minion:
         syft packages --scope installed-packages --output cyclonedx-json \
           > /tmp/sbom-$(date +%Y%m%d).json
t=3    Salt file.managed: push /tmp/sbom-*.json to returner
t=4    Custom returner: HTTP POST /api/v1/ingest/sbom/{node_id}
         Body: CycloneDX JSON document (~2-20MB)
t=5    FastAPI: queue sbom indexing task → Celery queue: sbom
t=6    sbom_worker: parse CycloneDX → extract components
t=7    DB write: sbom_scans row + sbom_components rows (bulk insert)
t=8    tsvector columns auto-generated (GENERATED ALWAYS AS)
t=9    Old sbom_scans archived (retain last 3 scans per node by default)
```

### Baseline Drift Recompute Flow (on Git push)

```
t=0   Engineer pushes baseline YAML change to Git
t=1   CI webhook: POST /api/v1/ingest/baseline-update
        Body: { baseline_name, git_commit_sha, changed_files }
t=2   FastAPI: load new baseline YAML from Git (gitpython / file read)
t=3   DB update: desired_state_baselines.state_json, .git_commit_sha
t=4   Determine affected nodes: all nodes in the baseline's target group
t=5   Celery task: batch_drift_recompute(node_ids=[...]) → queue: drift
t=6   DriftEngine runs for each node against new baseline
t=7   drift_records updated, nodes.drift_score updated
t=8   Frontend shows updated drift scores on next poll
```

### Execution Flow (Salt state run)

```
t=0   Salt highstate triggered (manual or scheduled)
t=1   Salt master pushes state to minion
t=2   Minion executes state: package installs, service restarts, config writes
t=3   Minion returns result to Salt master (job cache)
t=4   Custom returner: HTTP POST /api/v1/ingest/executions
        Body: { jid, minion_id, return_data, retcode, changes }
t=5   FastAPI: write execution_results row
t=6   DB update: execution_jobs.status = 'complete'
t=7   Celery task: compute_drift(node_id) — re-run drift after state change
t=8   Frontend Executions tab shows result, Drift tab updates
```

---

## 9. Database Design

### Schema Overview

All schemas use PostgreSQL 16 with the TimescaleDB extension. Tables marked `[hypertable]` use TimescaleDB's time-partitioned storage.

```sql
-- Enable TimescaleDB
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
```

### Users and Auth

```sql
CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,  -- bcrypt
    role          VARCHAR(20) NOT NULL DEFAULT 'viewer'
                    CHECK (role IN ('viewer', 'operator', 'admin')),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ
);
```

### Nodes

```sql
CREATE TABLE nodes (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    minion_id        VARCHAR(255) UNIQUE NOT NULL,
    hostname         VARCHAR(255),
    ip_address       INET,
    os_version       VARCHAR(50),
    os_build         VARCHAR(50),
    hardware_model   VARCHAR(100),
    cpu_cores        SMALLINT,
    ram_gb           DECIMAL(8,2),
    storage_gb       DECIMAL(10,2),
    status           VARCHAR(20) NOT NULL DEFAULT 'unknown'
                       CHECK (status IN ('online', 'stale', 'offline', 'unknown')),
    drift_score      SMALLINT NOT NULL DEFAULT 0 CHECK (drift_score BETWEEN 0 AND 100),
    node_token_hash  VARCHAR(64) NOT NULL,  -- bcrypt of node registration token
    first_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_nodes_status ON nodes(status);
CREATE INDEX idx_nodes_last_seen ON nodes(last_seen_at);
CREATE INDEX idx_nodes_drift_score ON nodes(drift_score DESC);
```

### Tags and Groups

```sql
CREATE TABLE tags (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id    UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    key        VARCHAR(100) NOT NULL,
    value      VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(node_id, key)
);

CREATE INDEX idx_tags_node_id ON tags(node_id);
CREATE INDEX idx_tags_key_value ON tags(key, value);

CREATE TABLE groups (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    type        VARCHAR(20) NOT NULL CHECK (type IN ('static', 'dynamic')),
    predicate   JSONB,
    -- Example dynamic predicate:
    -- {"and": [{"key": "env", "value": "prod"}, {"key": "role", "value": "builder"}]}
    created_by  UUID REFERENCES users(id),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE group_members (
    group_id UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    node_id  UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (group_id, node_id)
);

CREATE INDEX idx_group_members_node_id ON group_members(node_id);
```

### Node Facts — [hypertable]

```sql
CREATE TABLE node_facts (
    id           BIGSERIAL,
    node_id      UUID NOT NULL REFERENCES nodes(id),
    collected_at TIMESTAMPTZ NOT NULL,
    grains       JSONB NOT NULL,  -- full Salt grains dump
    PRIMARY KEY (id, collected_at)
);

-- Convert to TimescaleDB hypertable, partition by day
SELECT create_hypertable('node_facts', 'collected_at', chunk_time_interval => INTERVAL '1 day');

-- Retain 90 days of fact history
SELECT add_retention_policy('node_facts', INTERVAL '90 days');

CREATE INDEX idx_node_facts_node_id ON node_facts(node_id, collected_at DESC);
```

### Packages

```sql
CREATE TABLE packages (
    id           BIGSERIAL PRIMARY KEY,
    node_id      UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    name         VARCHAR(255) NOT NULL,
    version      VARCHAR(100),
    source       VARCHAR(50) NOT NULL  -- 'brew', 'pip', 'gem', 'pkg', 'app', 'port'
                   CHECK (source IN ('brew', 'pip', 'gem', 'pkg', 'app', 'port', 'npm')),
    collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(node_id, name, source)
);

CREATE INDEX idx_packages_node_id ON packages(node_id);
CREATE INDEX idx_packages_name ON packages(name);
CREATE INDEX idx_packages_name_version ON packages(name, version);
```

### SBOM

```sql
CREATE TABLE sbom_scans (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id      UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    syft_version VARCHAR(20),
    format       VARCHAR(20) NOT NULL DEFAULT 'cyclonedx',
    scanned_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    component_count INTEGER
);

CREATE INDEX idx_sbom_scans_node_id ON sbom_scans(node_id, scanned_at DESC);

CREATE TABLE sbom_components (
    id             BIGSERIAL PRIMARY KEY,
    scan_id        UUID NOT NULL REFERENCES sbom_scans(id) ON DELETE CASCADE,
    node_id        UUID NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    name           VARCHAR(255) NOT NULL,
    version        VARCHAR(100),
    purl           VARCHAR(500),            -- pkg:brew/openssl@3.1.0
    component_type VARCHAR(50),            -- library, application, framework, file
    licenses       JSONB DEFAULT '[]',     -- ["MIT", "Apache-2.0"]
    cpes           JSONB DEFAULT '[]',     -- CPE 2.3 strings
    search_vector  tsvector GENERATED ALWAYS AS (
        to_tsvector('english',
            name || ' ' ||
            COALESCE(version, '') || ' ' ||
            COALESCE(purl, '')
        )
    ) STORED
);

CREATE INDEX idx_sbom_components_search ON sbom_components USING GIN(search_vector);
CREATE INDEX idx_sbom_components_node_id ON sbom_components(node_id);
CREATE INDEX idx_sbom_components_name ON sbom_components(name);
CREATE INDEX idx_sbom_components_purl ON sbom_components(purl) WHERE purl IS NOT NULL;
```

### Drift — [hypertable]

```sql
CREATE TABLE desired_state_baselines (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name           VARCHAR(100) NOT NULL,
    description    TEXT,
    target_type    VARCHAR(20) NOT NULL CHECK (target_type IN ('group', 'node', 'global')),
    target_id      UUID,             -- group_id or node_id; NULL if global
    git_commit_sha VARCHAR(40) NOT NULL,
    state_json     JSONB NOT NULL,
    version        INTEGER NOT NULL DEFAULT 1,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE drift_records (
    id                 BIGSERIAL,
    node_id            UUID NOT NULL REFERENCES nodes(id),
    baseline_id        UUID REFERENCES desired_state_baselines(id),
    computed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    drift_score        SMALLINT NOT NULL CHECK (drift_score BETWEEN 0 AND 100),
    missing_packages   JSONB DEFAULT '[]',
    extra_packages     JSONB DEFAULT '[]',
    version_mismatches JSONB DEFAULT '[]',
    service_drift      JSONB DEFAULT '[]',
    config_drift       JSONB DEFAULT '[]',
    PRIMARY KEY (id, computed_at)
);

SELECT create_hypertable('drift_records', 'computed_at', chunk_time_interval => INTERVAL '1 day');
SELECT add_retention_policy('drift_records', INTERVAL '180 days');

CREATE INDEX idx_drift_records_node_id ON drift_records(node_id, computed_at DESC);
CREATE INDEX idx_drift_records_score ON drift_records(drift_score DESC, computed_at DESC);
```

### Execution History

```sql
CREATE TABLE execution_jobs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    salt_jid     VARCHAR(100),               -- Salt job ID
    type         VARCHAR(50) NOT NULL,       -- 'highstate', 'state_apply', 'sbom_scan', 'grain_sync'
    target_type  VARCHAR(20) NOT NULL,       -- 'node', 'group', 'glob'
    target_id    UUID,                       -- node_id or group_id
    triggered_by VARCHAR(255) NOT NULL,      -- user email or 'system'
    status       VARCHAR(20) NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'running', 'complete', 'failed', 'timeout')),
    started_at   TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    metadata     JSONB DEFAULT '{}'
);

CREATE INDEX idx_exec_jobs_status ON execution_jobs(status, started_at DESC);
CREATE INDEX idx_exec_jobs_salt_jid ON execution_jobs(salt_jid) WHERE salt_jid IS NOT NULL;

CREATE TABLE execution_results (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id       UUID NOT NULL REFERENCES execution_jobs(id) ON DELETE CASCADE,
    node_id      UUID NOT NULL REFERENCES nodes(id),
    status       VARCHAR(20) NOT NULL CHECK (status IN ('success', 'failure', 'timeout', 'skipped')),
    exit_code    INTEGER,
    stdout       TEXT,
    stderr       TEXT,
    changes      JSONB DEFAULT '{}',        -- Salt return data (changed resources)
    completed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_exec_results_job_id ON execution_results(job_id);
CREATE INDEX idx_exec_results_node_id ON execution_results(node_id, completed_at DESC);
```

### Audit Events — [hypertable]

```sql
CREATE TABLE audit_events (
    id            BIGSERIAL,
    event_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor         VARCHAR(255) NOT NULL,   -- user email or 'system'
    action        VARCHAR(100) NOT NULL,   -- 'node.tag.create', 'group.delete', 'baseline.update'
    resource_type VARCHAR(50),
    resource_id   UUID,
    old_value     JSONB,
    new_value     JSONB,
    ip_address    INET,
    PRIMARY KEY (id, event_at)
);

SELECT create_hypertable('audit_events', 'event_at', chunk_time_interval => INTERVAL '7 days');
SELECT add_retention_policy('audit_events', INTERVAL '2 years');

CREATE INDEX idx_audit_events_actor ON audit_events(actor, event_at DESC);
CREATE INDEX idx_audit_events_resource ON audit_events(resource_type, resource_id, event_at DESC);
```

### Continuous Aggregates (TimescaleDB)

Pre-computed rollups for the fleet dashboard — avoid full-table scans on every page load.

```sql
-- Hourly fleet drift summary
CREATE MATERIALIZED VIEW fleet_drift_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', computed_at) AS bucket,
    AVG(drift_score)::SMALLINT AS avg_drift_score,
    MAX(drift_score) AS max_drift_score,
    COUNT(*) FILTER (WHERE drift_score > 50) AS nodes_high_drift,
    COUNT(DISTINCT node_id) AS nodes_evaluated
FROM drift_records
GROUP BY bucket;

SELECT add_continuous_aggregate_policy('fleet_drift_hourly',
    start_offset => INTERVAL '3 hours',
    end_offset   => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour'
);
```

### Indexing Strategy

| Table | Index | Reason |
|---|---|---|
| nodes | (status) | Dashboard filter by online/offline |
| nodes | (drift_score DESC) | Sort by most-drifted |
| tags | (key, value) | Dynamic group predicate evaluation |
| sbom_components | GIN(search_vector) | Full-text package search |
| sbom_components | (name) | Package name lookup |
| drift_records | (node_id, computed_at DESC) | Node drift timeline |
| node_facts | (node_id, collected_at DESC) | Latest fact lookup |
| audit_events | (actor, event_at DESC) | Audit trail by user |

---

## 10. Drift Detection Design

### Desired State Model

Desired state is defined as YAML files in the Git repository under `baselines/`. Each baseline targets a group, a single node, or all nodes (global). On import, baselines are parsed and stored in `desired_state_baselines.state_json` alongside the Git commit SHA.

```yaml
# baselines/roles/builder.yaml
name: builder
version: "1.2"
description: "State for all CI builder Mac Minis"

packages:
  required:
    - name: git
      version: ">=2.39.0"
    - name: python3
      version: ">=3.11.0"
    - name: xcode-select
    - name: node
      version: ">=20.0.0"
    - name: docker
      source: brew
  forbidden:
    - name: teamviewer
    - name: anydesk
    - name: vlc        # no media players on builders

services:
  required_stopped:
    - com.apple.screensharing
    - com.apple.ARDAgent
  required_running:
    - com.docker.helper

configs:
  - path: /etc/ssh/sshd_config
    assertions:
      - key: PermitRootLogin
        operator: eq
        value: "no"
      - key: PasswordAuthentication
        operator: eq
        value: "no"
```

### Drift Scoring Model

```
Severity weights:
  missing_required_package:  20 points per occurrence
  forbidden_package_present: 10 points per occurrence
  version_mismatch_major:    15 points per occurrence
  version_mismatch_minor:     5 points per occurrence
  service_drift:             15 points per occurrence
  config_drift:              20 points per occurrence

Score = min(100, sum of all weighted violations)

Severity tiers:
  Clean:    0–5     (no action needed)
  Low:      6–20    (informational)
  Medium:  21–50    (review recommended)
  High:    51–80    (remediation required)
  Critical: 81–100  (immediate action required)
```

### Diff Computation

```python
# services/drift_engine.py (excerpt)

def _diff_missing_packages(self, actual_pkgs, required_pkgs):
    actual_names = {(p['name'], p['source']) for p in actual_pkgs}
    missing = []
    for req in required_pkgs:
        key = (req['name'], req.get('source', '*'))
        if not any(a_name == req['name'] and (req.get('source', '*') in ('*', a_src))
                   for a_name, a_src in actual_names):
            missing.append({
                'name': req['name'],
                'required_version': req.get('version'),
                'source': req.get('source'),
            })
    return missing

def _diff_versions(self, actual_pkgs, required_pkgs):
    mismatches = []
    actual_by_name = {p['name']: p for p in actual_pkgs}
    for req in required_pkgs:
        if 'version' not in req:
            continue
        actual = actual_by_name.get(req['name'])
        if not actual:
            continue  # handled by missing_packages diff
        violation = self._check_version_constraint(actual['version'], req['version'])
        if violation:
            mismatches.append({
                'name': req['name'],
                'actual': actual['version'],
                'required': req['version'],
                'severity': violation,  # 'major' or 'minor'
            })
    return mismatches
```

### Incremental Drift Processing

Drift is NOT recomputed for all nodes on a schedule. It is triggered:

1. **On grain sync** — `compute_drift(node_id)` queued immediately after ingest
2. **On baseline Git push** — `batch_drift_recompute(node_ids)` for all nodes in the baseline's target group
3. **On demand** — `POST /api/v1/drift/{node_id}/compute` (operator role required)

This means drift is always current with respect to both actual state (grain syncs) and desired state (baseline commits). No polling cron job processes the entire fleet.

### Historical Drift Timeline

The `drift_records` hypertable retains 180 days of per-node drift scores. The frontend renders a Recharts line chart:

```
drift score
 100 │           ●
  80 │      ●─●  │
  60 │   ●  │    ●─●
  40 │   │  │         ●
  20 │───┘  │              ●─────●
   0 │      │
     ├──────────────────────────────── time (30 days)
     Apr 9   Apr 16  Apr 23  Apr 30  May 7
```

Each data point is a `drift_records` row. Hover reveals the diff breakdown (missing packages, extra packages, etc.) for that timestamp.

### Diff Visualization

The DriftDiffViewer component renders a side-by-side comparison:

```
DESIRED STATE (baseline v1.2)          ACTUAL STATE (collected 10:42am)
─────────────────────────────          ──────────────────────────────────
Packages:                              Packages:
  ✓ git >= 2.39.0          ←→           ✓ git 2.43.0
  ✓ python3 >= 3.11        ←→           ✓ python3 3.12.2
  ✗ node >= 20.0.0         ←→           ✗ node 18.19.1 (version too old)
  ✗ docker (brew)          ←→           ✗ MISSING

Forbidden:                             Extra packages detected:
  ✗ teamviewer             ←→           ✓ teamviewer 15.51.0 PRESENT

Services:                              Services:
  ✗ screensharing=stopped  ←→           ✗ com.apple.screensharing RUNNING
```

---

## 11. SBOM Pipeline

### Format Choice: CycloneDX over SPDX

| Criterion | CycloneDX | SPDX |
|---|---|---|
| Syft native output | `cyclonedx-json`, `cyclonedx-xml` | `spdx-json`, `spdx-tag-value` |
| Package URL (purl) | First-class field | Supported but secondary |
| CPE support | Native | Available |
| Component types | library, application, framework, file | package, file, snippet |
| License expression | SPDX license IDs + expressions | SPDX native |
| Ecosystem richness | Richer component metadata | More license-focused |
| Tooling | Grype, Trivy, Dependency-Track | NTIA compliance tools |

**Verdict: CycloneDX JSON.** Richer component metadata (purl, CPE, component type), native Syft output, better tooling ecosystem for vulnerability correlation in future enhancements.

### Syft Execution via Salt State

```yaml
# salt/states/base/sbom_scan.sls
sbom_scan_run:
  cmd.run:
    - name: |
        /usr/local/bin/syft packages \
          --scope all-layers \
          --output cyclonedx-json \
          / > /tmp/sbom-{{ grains['id'] }}-$(date +%Y%m%d%H%M%S).json
    - creates: /tmp/sbom-{{ grains['id'] }}-*.json
    - timeout: 300

sbom_upload:
  module.run:
    - name: http.query
    - url: {{ pillar['fleet_platform']['ingest_url'] }}/api/v1/ingest/sbom/{{ grains['id'] }}
    - method: POST
    - header_list:
        - "X-Node-Token: {{ pillar['fleet_platform']['node_token'] }}"
        - "Content-Type: application/json"
    - data: __slot__:salt:file.read(/tmp/sbom-*.json)
    - require:
        - cmd: sbom_scan_run
```

### Ingest and Normalization

```python
# api/routes/ingest.py

@router.post("/sbom/{minion_id}")
async def ingest_sbom(
    minion_id: str,
    request: Request,
    token: str = Header(alias="X-Node-Token"),
    db: AsyncSession = Depends(get_db),
):
    node = await verify_node_token(db, minion_id, token)
    # Stream request body to a temp file to avoid loading large SBOMs into memory
    # Queue for async processing — don't block the returner
    await celery_app.send_task(
        'workers.sbom_tasks.index_sbom',
        kwargs={'node_id': str(node.id), 'tmp_path': '<temp_file_path>'},
        queue='sbom',
    )
    return {"status": "queued"}
```

```python
# workers/sbom_tasks.py

@celery_app.task(bind=True, max_retries=3, queue='sbom')
def index_sbom(self, node_id: str, raw_json: dict):
    try:
        parser = SBOMParser()
        scan, components = parser.parse_cyclonedx(node_id, raw_json)

        with get_sync_db() as db:
            db.add(scan)
            db.flush()
            db.bulk_save_objects([
                SBOMComponent(**c, scan_id=scan.id, node_id=node_id)
                for c in components
            ])
            db.commit()

        # Archive old scans (keep last 3 per node)
        archive_old_scans.delay(node_id=node_id, keep_count=3)

    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)
```

### Storage Schema

CycloneDX component → `sbom_components` mapping:

```
CycloneDX field       → Column
─────────────────────────────────────────
component.name        → name
component.version     → version
component.purl        → purl
component.type        → component_type
component.licenses    → licenses (JSONB array of SPDX IDs)
component.cpes        → cpes (JSONB array)
[derived]             → search_vector (tsvector of name+version+purl)
```

Raw CycloneDX JSON is NOT stored in full — only normalized component rows. This avoids JSONB bloat (20MB+ CycloneDX docs in JSONB columns) and enables efficient full-text search.

### Search Optimization

Fleet-wide package search uses PostgreSQL full-text:

```sql
-- Find all nodes with openssl 1.x
SELECT
    c.name,
    c.version,
    c.purl,
    n.hostname,
    n.ip_address
FROM sbom_components c
JOIN sbom_scans s ON c.scan_id = s.id
JOIN nodes n ON c.node_id = n.id
WHERE c.search_vector @@ to_tsquery('english', 'openssl')
  AND s.scanned_at = (
    SELECT MAX(s2.scanned_at)
    FROM sbom_scans s2
    WHERE s2.node_id = c.node_id
  )
ORDER BY c.name, n.hostname
LIMIT 100;
```

The `search_vector` GIN index makes this query fast even with millions of component rows. No Elasticsearch needed at this scale.

---

## 12. API Design

All user-facing APIs require JWT. Ingest APIs require node token (`X-Node-Token`). All responses follow a consistent envelope.

### Response Envelope

```json
// Success (list)
{
  "items": [...],
  "total": 42,
  "page": 1,
  "per_page": 25
}

// Success (single)
{
  "data": { ... }
}

// Error
{
  "error": {
    "code": "NODE_NOT_FOUND",
    "message": "Node 'abc123' does not exist",
    "request_id": "req_01J..."
  }
}
```

### Fleet Overview

```
GET /api/v1/fleet/overview

Response 200:
{
  "data": {
    "total_nodes": 42,
    "online": 38,
    "stale": 3,
    "offline": 1,
    "unknown": 0,
    "avg_drift_score": 14,
    "nodes_clean": 30,
    "nodes_low": 6,
    "nodes_medium": 4,
    "nodes_high": 2,
    "nodes_critical": 0,
    "last_updated": "2026-05-12T10:30:00Z"
  }
}
```

### Node Listing

```
GET /api/v1/nodes?status=online&group_id=uuid&tag=role:builder&sort=drift_score:desc&page=1&per_page=25

Response 200:
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "minion_id": "mac-mini-01.local",
      "hostname": "mac-mini-01",
      "ip_address": "192.168.1.101",
      "os_version": "14.4.1",
      "hardware_model": "Mac mini (2023)",
      "cpu_cores": 10,
      "ram_gb": 32,
      "storage_gb": 512,
      "status": "online",
      "drift_score": 45,
      "last_seen_at": "2026-05-09T10:28:00Z",
      "tags": [{"key": "env", "value": "prod"}, {"key": "role", "value": "builder"}]
    }
  ],
  "total": 38,
  "page": 1,
  "per_page": 25
}
```

### Node Detail

```
GET /api/v1/nodes/{node_id}

GET /api/v1/nodes/{node_id}/facts
Response: latest grain snapshot as JSONB

GET /api/v1/nodes/{node_id}/packages?source=brew&page=1&per_page=50
Response: { items: [{name, version, source}], total, page, per_page }

GET /api/v1/nodes/{node_id}/drift
NOTE: Implemented in Plan 4 — not yet available.
Response:
{
  "data": {
    "node_id": "...",
    "computed_at": "2026-05-09T10:28:00Z",
    "drift_score": 45,
    "severity": "medium",
    "baseline": { "name": "builder", "version": "1.2", "git_commit_sha": "abc1234" },
    "missing_packages": [
      {"name": "docker", "required_version": null, "source": "brew"}
    ],
    "extra_packages": [
      {"name": "teamviewer", "version": "15.51.0"}
    ],
    "version_mismatches": [
      {"name": "node", "actual": "18.19.1", "required": ">=20.0.0", "severity": "major"}
    ],
    "service_drift": [
      {"service": "com.apple.screensharing", "expected": "stopped", "actual": "running"}
    ],
    "config_drift": []
  }
}

GET /api/v1/nodes/{node_id}/drift/history?from=2026-04-09&to=2026-05-09&interval=1h
Response: { items: [{bucket, avg_drift_score, max_drift_score}] }
```

### Drift Explorer

```
GET /api/v1/drift?severity=medium&group_id=uuid&from=2026-05-01&page=1&per_page=25
Response: { items: [{node_id, hostname, drift_score, severity, computed_at}], total }

POST /api/v1/drift/{node_id}/compute
Authorization: Bearer {token} (operator role required)
Response 202: { "task_id": "celery-task-uuid", "status": "queued" }
```

### SBOM

```
GET /api/v1/sbom/search?q=openssl&node_id=uuid&page=1&per_page=100
Response:
{
  "items": [
    {
      "name": "openssl",
      "version": "3.3.0",
      "purl": "pkg:brew/openssl@3.3.0",
      "licenses": ["Apache-2.0"],
      "nodes": [
        {"node_id": "...", "hostname": "mac-mini-01", "scanned_at": "..."}
      ]
    }
  ],
  "total": 38,
  "query_time_ms": 12
}

GET /api/v1/sbom/nodes/{node_id}/latest
Response: { scan_id, scanned_at, syft_version, component_count, items: [...] }

GET /api/v1/sbom/nodes/{node_id}/history
Response: { items: [{scan_id, scanned_at, component_count}] }
```

### Groups

```
GET /api/v1/groups
POST /api/v1/groups
  Body: { "name": "prod-builders", "type": "dynamic",
          "predicate": {"and": [{"key":"env","value":"prod"},{"key":"role","value":"builder"}]} }

GET  /api/v1/groups/{group_id}
PUT  /api/v1/groups/{group_id}
DELETE /api/v1/groups/{group_id}

GET  /api/v1/groups/{group_id}/nodes
POST /api/v1/groups/{group_id}/members   Body: { "node_id": "uuid" }
DELETE /api/v1/groups/{group_id}/members/{node_id}
```

### Execution History

```
GET /api/v1/executions?node_id=uuid&type=highstate&status=failed&page=1&per_page=25
GET /api/v1/executions/{job_id}
GET /api/v1/executions/{job_id}/results          # per-node results
GET /api/v1/executions/{job_id}/results/{node_id}
```

### Ingest (node-authenticated)

```
POST /api/v1/ingest/grains
  Header: X-Node-Token: {token}
  Body: { "minion_id": "mac-mini-01.local", "grains": {...}, "timestamp": "..." }

POST /api/v1/ingest/sbom/{minion_id}
  Header: X-Node-Token: {token}
  Body: {CycloneDX JSON document}

POST /api/v1/ingest/executions
  Header: X-Node-Token: {token}
  Body: { "jid": "20260509102800123456", "return_data": {...}, "retcode": 0 }

POST /api/v1/ingest/baseline-update
  Header: X-CI-Token: {ci_token}   # separate token for CI pipeline
  Body: { "baseline_name": "builder", "git_commit_sha": "abc1234", "target_group": "uuid" }
```

---

## 13. Security Architecture

### Authentication

JWT-based authentication with 15-minute access tokens and 7-day refresh tokens.

```python
# core/auth.py

def create_access_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(minutes=15),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")

def require_role(*roles: str):
    async def dependency(token: str = Depends(oauth2_scheme), db = Depends(get_db)):
        claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        if claims["role"] not in roles:
            raise HTTPException(403, "Insufficient permissions")
        return claims
    return dependency

# Usage in routes:
@router.post("/drift/{node_id}/compute")
async def trigger_drift(
    node_id: UUID,
    _: dict = Depends(require_role("operator", "admin")),
):
    ...
```

### RBAC Model

| Action | viewer | operator | admin |
|---|---|---|---|
| Read fleet/nodes/drift/sbom | ✓ | ✓ | ✓ |
| Add/remove node tags | ✗ | ✓ | ✓ |
| Trigger SBOM scan | ✗ | ✓ | ✓ |
| Trigger drift recompute | ✗ | ✓ | ✓ |
| Create/edit groups | ✗ | ✓ | ✓ |
| Manage baselines | ✗ | ✗ | ✓ |
| Manage users | ✗ | ✗ | ✓ |
| Register/deregister nodes | ✗ | ✗ | ✓ |
| Read audit log | ✗ | ✗ | ✓ |
| Rotate node tokens | ✗ | ✗ | ✓ |

### Node Trust Model

Nodes authenticate to the ingest API using per-node tokens, not shared secrets.

```
Registration flow:
  1. Admin: POST /api/v1/nodes/register { minion_id, hostname }
  2. API: generate secure random token (32 bytes, URL-safe base64)
  3. API: bcrypt hash → store in nodes.node_token_hash
  4. API: return plaintext token ONCE to admin
  5. Admin: store token in Salt pillar (encrypted)
  6. Salt pillar: supplies token to minion via {{ pillar['fleet_platform']['node_token'] }}
  7. Minion: includes X-Node-Token header in all returner calls

Token rotation:
  POST /api/v1/nodes/{node_id}/rotate-token (admin only)
  → generates new token, returns it, old token immediately invalid
  → admin updates pillar, re-keys minion
```

The token is bcrypt-hashed in the DB. Even if the database is compromised, tokens cannot be reused without cracking each bcrypt hash.

### Secrets Handling

| Secret | Storage | Access |
|---|---|---|
| Node ingest tokens | DB (bcrypt hash) + Salt pillar (GPG-encrypted) | Salt master reads pillar; DB stores hash only |
| JWT signing secret | Environment variable | FastAPI process only |
| DB password | Environment variable / k8s Secret | FastAPI + workers only |
| Redis password | Environment variable | FastAPI + workers only |
| CI baseline update token | Environment variable | CI pipeline only |

**Never** store secrets in:
- Git repository (even encrypted unless using git-crypt or Vault)
- Application logs
- API response bodies
- Browser localStorage (tokens stored in httpOnly cookies in production)

### Audit Logging

Every mutation writes an audit event in the same DB transaction:

```python
# core/audit.py

async def audit(
    db: AsyncSession,
    actor: str,
    action: str,
    resource_type: str,
    resource_id: UUID,
    old_value: dict | None = None,
    new_value: dict | None = None,
    ip_address: str | None = None,
):
    event = AuditEvent(
        actor=actor,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        old_value=old_value,
        new_value=new_value,
        ip_address=ip_address,
    )
    db.add(event)
    # No separate flush — written in same transaction as the mutation
```

Audit actions follow the pattern `{resource}.{verb}`:
- `node.tag.create`, `node.tag.delete`
- `group.create`, `group.update`, `group.delete`
- `group.member.add`, `group.member.remove`
- `baseline.update`
- `user.create`, `user.role.change`
- `node.token.rotate`

The `audit_events` table has no DELETE or UPDATE grants for the application user. Only a superuser can modify audit records — enforced at the DB level.

### Transport Security

- Nginx terminates TLS (certificate via Let's Encrypt or internal CA)
- All API traffic: HTTPS only; HTTP → HTTPS redirect
- Salt ZeroMQ: encrypted (AES-256 between master and minions by default)
- DB connections: TLS if remote; Unix socket if co-located
- Redis: password + TLS if remote; Unix socket if co-located
- CORS: whitelist only the known frontend origin — no wildcard

### Rate Limiting

```python
# Redis-backed rate limiting per IP
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address, storage_uri=settings.redis_url)

@router.post("/auth/login")
@limiter.limit("10/minute")  # aggressive limit on auth endpoint
async def login(...): ...

@router.get("/api/v1/nodes")
@limiter.limit("100/minute")  # standard API rate
async def list_nodes(...): ...

@router.post("/api/v1/ingest/grains")
@limiter.limit("200/minute")  # ingest gets higher limit
async def ingest_grains(...): ...
```

---

## 14. Scalability Strategy

### Phase 1: 40 Nodes (Current)

Single-server Docker Compose deployment:

```
1x Linux server (or Mac Mini):
  ├── nginx (static files + reverse proxy)
  ├── fastapi (uvicorn, 4 workers)
  ├── celery-worker (concurrency=4, queues: drift,sbom,default)
  ├── celery-beat (singleton)
  ├── postgres + timescaledb
  └── redis

Salt master: same server or dedicated server on the same LAN
```

Resource estimates at 40 nodes:
- Grain syncs: 40 nodes × 1/5min = 8 req/min to ingest API (trivial)
- Drift tasks: 8/min Celery tasks (trivial)
- SBOM scans: 40 nodes/day (background, off-peak)
- DB size: ~500MB after 90 days (small)

### Phase 2: 200–500 Nodes

Same architecture, scaled out:

```
nginx (1x, static files)
  ├── fastapi (3 replicas, upstream load balanced)
  ├── celery-drift (4 workers × concurrency=8)
  ├── celery-sbom (2 workers × concurrency=2)
  ├── celery-beat (1 singleton)
  ├── postgres primary + 1 read replica (API reads hit replica)
  └── redis (single instance, sentinel for HA)
```

PostgreSQL read replica:
```python
# db/session.py
engine_write = create_async_engine(settings.db_primary_url)
engine_read = create_async_engine(settings.db_replica_url)

# Fleet dashboard and node listing use read replica
# Ingest and mutations use primary
```

### Phase 3: 1000+ Nodes

```
Ingest throughput at 1000 nodes:
  - Grain syncs: 1000 nodes × 1/5min = 200 req/min to ingest
  - Drift tasks: 200 Celery tasks/min (manageable with 8 workers)
  - SBOM scans: 1000 per day = ~42/hour (background, trivial)
```

Architectural changes for 1000+ nodes:

**1. Salt Syndic (if geographically distributed)**
```
Salt Master (HQ)
  └── Salt Syndic (remote site)
        └── Minions (remote fleet)
```
Syndic relays job results upstream. Single returner still calls central ingest API.

**2. FastAPI horizontal scaling (k8s)**
```yaml
# helm/values.yaml
api:
  replicas: 5
  autoscaling:
    enabled: true
    minReplicas: 3
    maxReplicas: 10
    targetCPUUtilizationPercentage: 70

worker-drift:
  replicas: 4
  autoscaling:
    enabled: true
    minReplicas: 2
    maxReplicas: 12
    targetMetrics:
      - type: External
        external:
          metric:
            name: celery_queue_length
            selector:
              matchLabels:
                queue: drift
          target:
            type: AverageValue
            averageValue: "50"
```

**3. TimescaleDB continuous aggregates prevent full-table scans**

Fleet overview at 1000 nodes across 180 days = ~32M drift_records rows. Without aggregates, every dashboard load is a slow aggregation. With continuous aggregates:

```sql
-- Dashboard query: O(hours_in_range) instead of O(records_in_range)
SELECT bucket, avg_drift_score, nodes_high_drift
FROM fleet_drift_hourly
WHERE bucket >= NOW() - INTERVAL '7 days'
ORDER BY bucket DESC;
```

**4. Redis caching for expensive API responses**

```python
@router.get("/api/v1/fleet/overview")
async def fleet_overview(redis: Redis = Depends(get_redis)):
    cache_key = "fleet:overview"
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)

    data = await compute_fleet_overview(db)
    await redis.setex(cache_key, 15, json.dumps(data))  # 15s TTL
    return data
```

Cache invalidation: `REDIS DEL fleet:overview` is called from the ingest handler after writing a node_fact row. This means the cache is always within one ingest cycle of being fresh.

**5. Partitioned SBOM storage**

At 1000 nodes × 3 scans retained × ~50k components/scan = 150M sbom_component rows. Add a partition by node_id hash:

```sql
CREATE TABLE sbom_components (
    ...
) PARTITION BY HASH (node_id);

CREATE TABLE sbom_components_p0 PARTITION OF sbom_components
    FOR VALUES WITH (MODULUS 4, REMAINDER 0);
-- ... p1, p2, p3
```

### Query Optimization Checklist

- [ ] All foreign key columns have indexes
- [ ] `(node_id, computed_at DESC)` composite index on drift_records
- [ ] Partial index: `WHERE status != 'offline'` on nodes for active-fleet queries
- [ ] GIN index on sbom_components.search_vector
- [ ] TimescaleDB chunk exclusion enabled (automatic with proper WHERE clauses on time columns)
- [ ] `pg_stat_statements` enabled to identify slow queries in production
- [ ] EXPLAIN ANALYZE run on all dashboard queries before launch

---

## 15. Operational Considerations

### Deployment: Docker Compose (Phase 1)

```yaml
# deploy/docker-compose.yml
version: "3.9"

services:
  postgres:
    image: timescale/timescaledb:latest-pg16
    environment:
      POSTGRES_DB: fleet_platform
      POSTGRES_USER: fleet
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U fleet -d fleet_platform"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD} --appendonly yes
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "--no-auth-warning", "-a", "${REDIS_PASSWORD}", "ping"]

  api:
    image: fleet-platform:${VERSION:-latest}
    command: uvicorn platform.api.main:app --host 0.0.0.0 --port 8000 --workers 4
    environment:
      DATABASE_URL: postgresql+asyncpg://fleet:${POSTGRES_PASSWORD}@postgres/fleet_platform
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379/0
      JWT_SECRET: ${JWT_SECRET}
      FRONTEND_ORIGIN: ${FRONTEND_ORIGIN}
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]

  worker-drift:
    image: fleet-platform:${VERSION:-latest}
    command: celery -A platform.workers.celery_app worker -Q drift,default -c 4 --loglevel=info
    environment:
      DATABASE_URL: postgresql+psycopg2://fleet:${POSTGRES_PASSWORD}@postgres/fleet_platform
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379/0
    depends_on: [postgres, redis]

  worker-sbom:
    image: fleet-platform:${VERSION:-latest}
    command: celery -A platform.workers.celery_app worker -Q sbom -c 2 --loglevel=info
    environment:
      DATABASE_URL: postgresql+psycopg2://fleet:${POSTGRES_PASSWORD}@postgres/fleet_platform
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379/0
    depends_on: [postgres, redis]

  beat:
    image: fleet-platform:${VERSION:-latest}
    command: celery -A platform.workers.celery_app beat --loglevel=info
    depends_on: [redis]

  nginx:
    image: nginx:alpine
    volumes:
      - ./deploy/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./frontend/dist:/usr/share/nginx/html:ro
      - ./certs:/etc/nginx/certs:ro
    ports:
      - "443:443"
      - "80:80"
    depends_on: [api]

volumes:
  pgdata:
  redisdata:
```

### Nginx Configuration

```nginx
# deploy/nginx/nginx.conf
server {
    listen 443 ssl http2;
    server_name fleet.internal;

    ssl_certificate     /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    # Serve React SPA
    root /usr/share/nginx/html;
    try_files $uri $uri/ /index.html;

    # Proxy API to FastAPI
    location /api/ {
        proxy_pass http://api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 30s;
    }

    location /auth/ {
        proxy_pass http://api:8000;
    }

    # Ingest endpoint: higher body size limit for SBOM payloads
    location /api/v1/ingest/sbom/ {
        client_max_body_size 50M;
        proxy_pass http://api:8000;
        proxy_read_timeout 120s;
    }
}

server {
    listen 80;
    return 301 https://$host$request_uri;
}
```

### Observability Stack

```
Logs:  structlog JSON → stdout → collected by Docker/systemd journald
       or forwarded to centralized logging (Loki, ELK, CloudWatch)

Metrics:
  FastAPI → prometheus_fastapi_instrumentator → /metrics endpoint
  Celery  → celery-exporter → /metrics endpoint
  Postgres → postgres_exporter → /metrics endpoint
  Redis   → redis_exporter → /metrics endpoint

Alerts (Alertmanager rules):
  - node_offline_duration > 1h
  - avg_drift_score > 50 (fleet-wide)
  - celery_queue_length{queue="drift"} > 100 (worker backlog)
  - api_request_latency_p99 > 2s
  - disk_usage > 80% (on the control plane server)
```

### Backup Strategy

```bash
# Daily PostgreSQL backup
pg_dump -Fc fleet_platform | gzip > backups/fleet_$(date +%Y%m%d).pgdump.gz

# WAL archiving for point-in-time recovery
# archive_command = 'cp %p /backups/wal/%f'

# Git repository (desired state): already version controlled
# Redis: AOF persistence enabled — recovers Celery task state on restart
```

### Minion Bootstrap Script

```bash
#!/bin/bash
# scripts/bootstrap_node.sh
# Run on each new Mac Mini to register it with the platform

MINION_ID="${1:-$(hostname -f)}"
SALT_MASTER="${2:-salt-master.internal}"
PLATFORM_URL="${3:-https://fleet.internal}"

# Install Salt minion
brew install salt

# Configure minion
cat > /etc/salt/minion <<EOF
master: ${SALT_MASTER}
id: ${MINION_ID}
grains:
  fleet_managed: true
EOF

# Accept key on master (run on salt master):
# salt-key -a ${MINION_ID}

# Register node with platform (admin provides token)
echo "Node ${MINION_ID} ready. Register via:"
echo "  POST ${PLATFORM_URL}/api/v1/nodes/register"
echo "  Body: {\"minion_id\": \"${MINION_ID}\", \"hostname\": \"$(hostname)\"}"
```

---

## 16. Failure Handling

### Node Goes Offline

```
t=0   Mac Mini powers off / network loss
t=5m  Salt master: minion heartbeat expires (ZeroMQ keepalive)
t=10m Celery beat: mark_stale_nodes() runs
       nodes WHERE last_seen_at < NOW() - INTERVAL '15 minutes'
         SET status = 'stale'
t=60m Celery beat: mark_stale_nodes() runs again
       nodes WHERE last_seen_at < NOW() - INTERVAL '1 hour'
         SET status = 'offline'

Frontend behavior:
  - Node row: red "Offline" badge, "Last seen 1h ago"
  - Drift score: preserved from last known state (not reset to 0)
  - Drift timeline: gap in chart where data is missing
  - No error state — this is expected behavior, not a bug
```

### Salt Master Goes Down

```
Impact:
  - No new grain syncs → node_facts table stops updating
  - No highstate execution possible
  - Minions buffer their events (configurable: loop_interval)

Platform behavior:
  - Ingest API still runs — no grain data arriving is not an error
  - mark_stale_nodes() will eventually mark nodes as stale
  - Alert: node_offline_count increases → Alertmanager fires

Recovery:
  - Salt master restarts → minions reconnect automatically
  - Grain sync runs immediately on reconnect
  - Backlog of buffered events flushed
  - Platform catches up within one grain sync interval
```

### Ingest API Down

```
Impact:
  - Salt returner cannot POST grain data
  - Returner retry: 3 attempts, exponential backoff (1s, 2s, 4s)
  - After 3 failures: logged to salt master event bus, grain data lost for this cycle
  - Next grain sync (5 min) will succeed when API recovers

Mitigation:
  - Nginx upstream: multiple FastAPI replicas → automatic failover
  - Health check: /health returns 200 only when DB connection is live
  - If all replicas unhealthy: Nginx returns 503; Salt returner logs and retries next sync
```

### Celery Worker Crash

```
Impact:
  - In-flight tasks: lost if worker crashes mid-execution
  - Queued tasks: remain in Redis, picked up by surviving workers

Mitigation:
  - Task idempotency: drift computation for same (node_id, timestamp) is safe to rerun
  - SBOM indexing: wrapped in DB transaction, rolled back on failure
  - max_retries=3 with countdown=60 for all tasks
  - Dead letter: tasks exhausting retries moved to failed_tasks queue
  - Monitor failed_tasks queue via Flower: http://localhost:5555

Recovery:
  - Worker container restarts automatically (Docker restart: unless-stopped)
  - Tasks retry from Redis queue
```

### Database Connection Pool Exhaustion

```python
# db/session.py
engine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,       # wait up to 30s for a connection
    pool_pre_ping=True,    # validate connections before use
)
```

If pool is exhausted:
- FastAPI returns `503 Service Unavailable` with `Retry-After: 5`
- Celery tasks: SQLAlchemy raises `TimeoutError` → task retried after 30s
- Alert: `pool_checkedin` metric from SQLAlchemy → Prometheus

### SBOM Upload Too Large

```python
# api/routes/ingest.py
@router.post("/sbom/{minion_id}")
async def ingest_sbom(request: Request, ...):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 50 * 1024 * 1024:  # 50MB limit
        raise HTTPException(413, "SBOM payload too large")

    # Stream body to temp file instead of loading into memory
    tmp_path = f"/tmp/sbom_{minion_id}_{uuid4()}.json"
    async with aiofiles.open(tmp_path, 'wb') as f:
        async for chunk in request.stream():
            await f.write(chunk)

    # Queue file path, not content
    index_sbom.delay(node_id=str(node.id), file_path=tmp_path)
    return {"status": "queued"}
```

### Partial Grain Data

If a minion sends incomplete grains (network interruption mid-POST):

```python
# api/routes/ingest.py
@router.post("/grains")
async def ingest_grains(payload: GrainIngestPayload, ...):
    # Validate required grain fields present
    required_fields = ['id', 'os', 'osrelease', 'ip_interfaces']
    missing = [f for f in required_fields if f not in payload.grains]
    if missing:
        # Accept partial data but flag it
        await audit(db, actor='system', action='ingest.grains.partial',
                    resource_type='node', resource_id=node.id,
                    new_value={'missing_fields': missing})
        # Still write what we have — partial data is better than no data
```

---

## 17. GitOps Workflow

### Repository Layout

The Git repository is the source of truth for:
1. Salt states (what to apply to nodes)
2. Salt pillar (node-specific configuration, encrypted secrets)
3. Desired state baselines (what drift is computed against)

```
Changes to Salt states  → Salt applies them to nodes
Changes to baselines    → Platform recomputes drift for affected groups
```

### Salt State GitOps

Salt master uses `gitfs` to serve states directly from Git:

```yaml
# /etc/salt/master.d/gitfs.conf
fileserver_backend:
  - gitfs
  - roots

gitfs_remotes:
  - https://git.internal/fleet-platform.git:
      - root: salt/states
      - base: main

gitfs_update_interval: 60   # poll Git every 60 seconds
```

Workflow:

```
Engineer branch:
  1. git checkout -b feat/builder-update-node-version
  2. Edit salt/states/roles/builder.sls
  3. git push origin feat/builder-update-node-version
  4. Open PR for review

Review:
  5. Peer reviews state changes
  6. CI validates YAML syntax (salt-lint)
  7. Merge to main

Deployment:
  8. Salt master polls gitfs: detects new commit within 60s
  9. salt -G 'role:builder' state.apply roles.builder
     (manual trigger OR Salt reactor on gitfs update event)
 10. Returner: POST /api/v1/ingest/executions with results
 11. Drift recomputed for builder group
```

### Baseline GitOps

```
Engineer branch:
  1. Edit baselines/roles/builder.yaml (add forbidden package, change version pin)
  2. CI: validate baseline schema (JSON Schema check)
  3. CI: POST /api/v1/ingest/baseline-update with git SHA (on merge to main)
  4. Platform: loads new baseline, triggers batch drift recompute for builder group
  5. Engineers see updated drift scores on fleet dashboard
```

### CI Pipeline Integration

```yaml
# .github/workflows/deploy.yml (example)
on:
  push:
    branches: [main]

jobs:
  validate-salt-states:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install salt-lint
      - run: salt-lint salt/states/**/*.sls

  validate-baselines:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python scripts/validate_baselines.py baselines/

  notify-platform:
    needs: [validate-salt-states, validate-baselines]
    runs-on: ubuntu-latest
    steps:
      - name: Notify baseline update
        run: |
          curl -X POST https://fleet.internal/api/v1/ingest/baseline-update \
            -H "X-CI-Token: ${{ secrets.CI_TOKEN }}" \
            -H "Content-Type: application/json" \
            -d "{
              \"git_commit_sha\": \"${{ github.sha }}\",
              \"changed_files\": $(git diff --name-only HEAD~1 HEAD | jq -R . | jq -s .)
            }"
```

---

## 18. Repository Structure

```
macos-fleet-platform/
│
├── salt/                              # SaltStack configuration
│   ├── master.conf                    # Salt master config
│   ├── minion.conf.template           # Minion config template
│   ├── states/
│   │   ├── top.sls                    # State targeting
│   │   ├── base/
│   │   │   ├── init.sls               # Common state (applied to all)
│   │   │   ├── common.sls             # SSH hardening, baseline tools
│   │   │   └── sbom_scan.sls          # Syft execution + upload
│   │   └── roles/
│   │       ├── builder.sls            # CI builder state
│   │       ├── ci_runner.sls          # CI runner state
│   │       └── workstation.sls        # Developer workstation state
│   ├── pillar/
│   │   ├── top.sls
│   │   └── nodes/
│   │       └── {minion_id}.sls        # Per-node secrets (GPG encrypted)
│   ├── reactors/
│   │   └── grain_sync.sls             # Reactor for grain sync events
│   └── returners/
│       └── fleet_platform_return.py   # Custom returner (POST to ingest API)
│
├── platform/                          # FastAPI backend
│   ├── api/
│   │   ├── main.py
│   │   ├── deps.py
│   │   └── routes/
│   │       ├── nodes.py
│   │       ├── groups.py
│   │       ├── drift.py
│   │       ├── sbom.py
│   │       ├── executions.py
│   │       ├── ingest.py
│   │       ├── auth.py
│   │       ├── audit.py
│   │       └── health.py
│   ├── core/
│   │   ├── config.py                  # pydantic-settings
│   │   ├── auth.py                    # JWT + RBAC
│   │   ├── audit.py                   # audit_event() writer
│   │   ├── logging.py                 # structlog JSON
│   │   └── exceptions.py
│   ├── models/                        # SQLAlchemy ORM
│   │   ├── node.py
│   │   ├── group.py
│   │   ├── drift.py
│   │   ├── sbom.py
│   │   ├── execution.py
│   │   └── audit.py
│   ├── schemas/                       # Pydantic v2
│   │   ├── node.py
│   │   ├── group.py
│   │   ├── drift.py
│   │   ├── sbom.py
│   │   └── ingest.py
│   ├── services/
│   │   ├── drift_engine.py
│   │   ├── baseline_loader.py
│   │   ├── sbom_parser.py
│   │   ├── group_resolver.py
│   │   └── node_status.py
│   ├── workers/
│   │   ├── celery_app.py
│   │   ├── drift_tasks.py
│   │   ├── sbom_tasks.py
│   │   └── maintenance.py
│   └── db/
│       ├── session.py
│       └── migrations/
│           ├── env.py
│           └── versions/
│               └── 001_initial_schema.py
│
├── frontend/                          # React application
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── pages/
│   │   │   ├── FleetDashboard/
│   │   │   │   ├── index.tsx
│   │   │   │   ├── FleetStatsBar.tsx
│   │   │   │   └── NodeTable.tsx
│   │   │   ├── NodeDetail/
│   │   │   │   ├── index.tsx
│   │   │   │   ├── OverviewTab.tsx
│   │   │   │   ├── PackagesTab.tsx
│   │   │   │   ├── DriftTab.tsx
│   │   │   │   ├── SBOMTab.tsx
│   │   │   │   └── ExecutionsTab.tsx
│   │   │   ├── DriftExplorer/
│   │   │   ├── SBOMExplorer/
│   │   │   ├── GroupExplorer/
│   │   │   └── ExecutionHistory/
│   │   ├── components/
│   │   │   ├── DataTable/
│   │   │   ├── DriftBadge/
│   │   │   ├── DriftDiffViewer/
│   │   │   ├── Timeline/
│   │   │   └── NodeStatusBadge/
│   │   ├── api/                       # React Query hooks
│   │   │   ├── nodes.ts
│   │   │   ├── drift.ts
│   │   │   ├── sbom.ts
│   │   │   └── groups.ts
│   │   ├── store/                     # Zustand
│   │   │   ├── filterStore.ts
│   │   │   └── uiStore.ts
│   │   └── utils/
│   │       ├── formatters.ts
│   │       └── driftColors.ts
│   ├── package.json
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   └── vite.config.ts
│
├── baselines/                         # Desired state definitions
│   ├── global.yaml                    # Applied to all nodes
│   ├── roles/
│   │   ├── builder.yaml
│   │   ├── ci_runner.yaml
│   │   └── workstation.yaml
│   └── environments/
│       ├── prod.yaml
│       └── staging.yaml
│
├── deploy/
│   ├── docker-compose.yml
│   ├── docker-compose.override.yml    # Local dev overrides
│   ├── nginx/
│   │   └── nginx.conf
│   └── helm/
│       └── fleet-platform/
│           ├── Chart.yaml
│           ├── values.yaml
│           ├── values.production.yaml
│           └── templates/
│               ├── api-deployment.yaml
│               ├── worker-drift-deployment.yaml
│               ├── worker-sbom-deployment.yaml
│               ├── beat-deployment.yaml
│               ├── postgres-statefulset.yaml
│               ├── redis-statefulset.yaml
│               └── nginx-deployment.yaml
│
├── scripts/
│   ├── bootstrap_node.sh              # Register new minion
│   ├── rotate_token.sh                # Rotate node ingest token
│   ├── seed_baselines.py              # Import baseline YAMLs to DB
│   └── validate_baselines.py          # CI baseline schema check
│
├── tests/
│   ├── unit/
│   │   ├── test_drift_engine.py
│   │   ├── test_sbom_parser.py
│   │   └── test_group_resolver.py
│   ├── integration/
│   │   ├── test_ingest_api.py
│   │   ├── test_drift_pipeline.py
│   │   └── test_sbom_pipeline.py
│   └── fixtures/
│       ├── sample_grains.json
│       ├── sample_cyclonedx.json
│       └── sample_baseline.yaml
│
└── docs/
    ├── architecture/
    │   └── rfc-001-platform-architecture.md
    ├── runbooks/
    │   ├── salt-key-rotation.md
    │   ├── node-registration.md
    │   └── incident-drift-spike.md
    └── api/
        └── openapi.yaml               # auto-generated by FastAPI
```

---

## 19. Future Enhancements

These are deliberately out of scope for v1. Listed in priority order.

**1. CVE Correlation (High Value)**
Cross-reference SBOM components against OSV.dev or NVD via purl matching. CycloneDX purls map directly to OSV ecosystem identifiers. This can be added as a Celery task that runs after each SBOM index: `query_osv(purl) → write cve_findings(component_id, cve_id, severity)`. Fleet-wide CVE exposure becomes searchable in the SBOM Explorer.

**2. Alerting Integration**
Webhook-based alert dispatch when drift score crosses a threshold or a node goes offline. Initial targets: Slack (webhook), PagerDuty (Events API v2). Configurable per-group thresholds stored in DB. Alert deduplication via a `last_alerted_at` timestamp per node.

**3. Automated Remediation Workflow**
Operator-approved remediation: drift engine identifies the specific Salt state to apply, surfaces it as a "Fix" button in the UI. Operator approves → platform queues `state.apply` via Salt API for only the drifted resources. Requires Salt API service running alongside Salt master.

**4. CIS Benchmark Compliance Scoring**
Parse CIS macOS Benchmark controls into baseline assertions. Map each control to a baseline check. Per-node compliance report: pass/fail per control, overall compliance score. Requires extending the baseline format and scoring model — architecture already supports it.

**5. SSO / SAML Integration**
Replace local password auth with SAML 2.0 (Okta, Azure AD, Google Workspace). JWT generation remains the same — only the identity verification step changes. python3-saml library handles SAML assertion parsing.

**6. OpenTelemetry Distributed Tracing**
Add OTEL instrumentation to FastAPI (opentelemetry-instrumentation-fastapi) and Celery (opentelemetry-instrumentation-celery). Export traces to Tempo or Jaeger. Enables tracing a grain sync event from Salt returner → ingest API → drift task → DB write.

**7. Dynamic Baseline Editor (UI)**
Web UI for editing baseline YAML without touching Git directly. Stores baselines in DB only. Git-backed baselines remain the canonical source for GitOps purists; DB-only baselines serve teams that prefer UI-driven workflows. Conflict resolution: Git push overwrites DB version.

**8. Network Topology View**
Visualize Mac Mini locations using the `location` tag. D3.js force-directed graph showing node clusters by group, color-coded by drift severity. Useful for identifying location-correlated drift patterns (e.g., all nodes in `location=blr` are drifted).

---

## 20. Risks and Tradeoffs

### Risk 1: Salt Master as Single Point of Failure

**Risk:** If the Salt master goes down, all push-based execution stops. Grain syncs stop. Node facts grow stale. The platform has no visibility into live state until the master recovers.

**Mitigation:**
- Salt master runs on a reliable server with systemd restart policy
- Master configuration is version-controlled and reproducible in under 10 minutes
- Platform handles stale state gracefully (shows "last seen X ago", preserves last known drift score)
- Future: Salt multi-master for HA (significant operational complexity — defer to Phase 3)

**Accepted tradeoff:** Single master is the right choice for 40–200 nodes. The operational complexity of multi-master isn't justified yet.

---

### Risk 2: Salt Key Management at Scale

**Risk:** Every new Mac Mini requires an explicit `salt-key -a {minion_id}` on the master. At 40 nodes, a manual step. At 1000 nodes, an operational bottleneck.

**Mitigation:**
- Auto-accept with network-scoped trust: `auto_accept: True` in master config, combined with `autosign_grains` matching an internal hostname pattern
- Better: `autosign_file` with a grains-based fingerprint check
- Platform's `bootstrap_node.sh` triggers key acceptance via Salt API after node registration

**Accepted tradeoff:** Auto-accept on a LAN with physical Mac Mini access is a reasonable trust boundary. Document and enforce the pattern.

---

### Risk 3: TimescaleDB Extension Dependency

**Risk:** TimescaleDB is a Postgres extension. If it causes instability, removing it requires schema changes (dropping hypertables, creating plain tables, migrating data). It also requires TimescaleDB-specific Docker image, not plain postgres.

**Mitigation:**
- TimescaleDB is mature (Timescale Inc., production-hardened)
- Application code uses standard SQL for all queries — no TimescaleDB-specific query syntax in the ORM layer (except for retention policy setup in migrations)
- Continuous aggregates are the only hard dependency; if removed, dashboard queries fall back to standard SQL aggregates (slower but functional)

**Accepted tradeoff:** The time-series storage and retention benefits far outweigh the migration risk at this scale.

---

### Risk 4: Celery Beat Singleton Constraint

**Risk:** Only one `celery beat` instance can run at a time. If you accidentally run two, scheduled tasks fire twice. In k8s, HPA cannot be applied to the beat Deployment.

**Mitigation:**
- Beat Deployment: `replicas: 1`, no HPA
- Pod disruption budget: `maxUnavailable: 0` (don't evict beat pod during node drain)
- Alternative: `django-celery-beat` with DB-backed lock; overkill for this use case

**Accepted tradeoff:** Singleton beat is the standard Celery pattern. Document it clearly.

---

### Risk 5: Dynamic Group Performance at Scale

**Risk:** Dynamic groups re-evaluate their predicate against all nodes on every grain sync. At 1000 nodes × 50 dynamic groups, that's 50,000 tag predicate evaluations per 5-minute cycle.

**Reality check:** Each evaluation is a single indexed SQL query:
```sql
SELECT n.id FROM nodes n
JOIN tags t ON n.id = t.node_id
WHERE t.key = 'env' AND t.value = 'prod';
```
With the `(key, value)` index on tags, this is fast even at 1000 nodes. 50 such queries in a Celery task is ~100ms. Not a problem.

**Future risk:** At 10,000 nodes × 500 groups, revisit. Solution: lazy evaluation (re-evaluate only when node tags change, not on every grain sync).

---

### Risk 6: SBOM Storage Growth

**Risk:** CycloneDX JSON for a full macOS system is 5–20MB. 40 nodes × 3 scans retained = 120 scans × 50k components average = 6M component rows. At 1000 nodes, 150M rows.

**Mitigation:**
- Raw CycloneDX JSON NOT stored — only normalized component rows
- Each component row is ~300 bytes → 150M rows ≈ 45GB (manageable with table partitioning)
- Retention: keep last 3 scans per node; archive older scans to cold storage
- GIN index on search_vector adds ~20% storage overhead

**Accepted tradeoff:** Component-level normalization (not blob storage) is the right architectural choice. Query performance on normalized rows is far superior to JSONB blob search.

---

### Risk 7: Frontend Bundle Size

**Risk:** TanStack Table, TanStack Virtual, Recharts, react-diff-viewer-continued, and Tailwind JIT together produce a large initial bundle.

**Mitigation:**
```typescript
// Lazy load heavy pages
const DriftExplorer = lazy(() => import('./pages/DriftExplorer'));
const SBOMExplorer = lazy(() => import('./pages/SBOMExplorer'));

// Code split per route
// Initial bundle: Layout + FleetDashboard only (~150KB gzipped)
// Heavy pages: loaded on demand (~50KB each)
```
Tailwind purges unused classes in production build. Vite handles tree-shaking.

---

### Risk 8: Grain Sync Thundering Herd at Scale

**Risk:** At 1000 nodes with 5-minute intervals, grain syncs are distributed over time (not synchronized). But if all nodes restart simultaneously (power outage + recovery), they all sync at once: 1000 ingest requests in ~30 seconds.

**Mitigation:**
- Ingest API: async FastAPI with async DB writes — handles bursts efficiently
- Celery: drift tasks queued but not blocked — processes backlog at worker rate
- PostgreSQL: bulk insert in ingest handler (not row-by-row)
- Redis rate limiter: per-node limit of 2 req/min on ingest endpoint (prevents any single node from flooding)

**Accepted tradeoff:** A simultaneous reconnect storm at 1000 nodes is a rare scenario. The async stack handles it without architectural changes.

---

*RFC-001 — macOS Fleet Management Platform Architecture*
*Prepared for internal engineering review*
*Date: 2026-05-09*
