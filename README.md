# kri — Self-Hosted Fleet Operations Platform

Kri (Sanskrit: "Create") — a self-hosted control plane for teams running physical build infrastructure.

[![CI](https://github.com/hellodk/kri/actions/workflows/ci.yml/badge.svg)](https://github.com/hellodk/kri/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/release/hellodk/kri?include_prereleases)](https://github.com/hellodk/kri/releases)
[![Issues](https://img.shields.io/github/issues/hellodk/kri)](https://github.com/hellodk/kri/issues)
[![License: Proprietary](https://img.shields.io/badge/License-Proprietary-red.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/Python-3.13-blue)](https://www.python.org/)
[![React 18](https://img.shields.io/badge/React-18-61DAFB)](https://react.dev/)

**kri is a self-hosted control plane for teams running physical build infrastructure — Apple Silicon build agents, edge servers, on-prem Mac Minis, and mixed hardware labs.** It bootstraps any SSH-reachable Linux or macOS node, runs Salt states and Ansible playbooks from one interface, scores every node against a declared baseline, and answers natural-language questions about fleet state. Unlike AWX/Ansible Tower (Ansible only, no drift model) or Jamf/MDM tools (Apple-only, no Salt/Ansible), kri unifies configuration, drift, processes, and AI over heterogeneous hardware you actually own.

---

## Features

### 🖥️ Fleet Operations
| | |
|---|---|
| **One-click bootstrap** | Onboard any SSH-reachable host from the web UI — node picker discovers the target, installs the Salt minion, and joins it to the fleet. macOS or Linux. |
| **Process & service manager** | Per-node CPU / memory / disk / IO. Kill, stop, and continue processes. Full `launchctl` (macOS) and `systemd` (Linux) service control. |
| **SSH multi-session terminal** | Tabbed in-browser SSH powered by asyncssh and xterm.js. |
| **VNC remote desktop** | Browser-based VNC access to any fleet node via noVNC. |
| **Group management** | Logical node grouping for bulk operations, secrets scoping, and targeted runs. |

### ⚙️ Configuration Management
| | |
|---|---|
| **SaltStack + Ansible, one interface** | Write Salt states or Ansible playbooks, run them across nodes or groups, stream logs live. Tracks accepted and pending minion keys. |
| **Drift detection** | Every node is scored against a stored baseline. Drift is surfaced immediately with per-key attribution and stored as TimescaleDB time-series, queryable over any window. |
| **macOS config profiles** | Upload `.mobileconfig` profiles, deploy via Ansible, enforce via Salt, and track compliance per node. |
| **Playbook & state discovery** | Auto-discovers playbooks, roles, and states; full job history with stdout streaming. |

### 📊 Observability & Security
| | |
|---|---|
| **Prometheus + Grafana** | Per-node and fleet-wide metrics with ready-made dashboards. OTEL instrumentation throughout. |
| **Role-based access control** | Three tiers — viewer / operator / admin — with JWT-authenticated sessions. |
| **Encrypted secrets** | Per-node and per-group secret storage with role-scoped access. |
| **Audit trail** | Immutable record of every action across the platform. |
| **URL health monitoring** | Auto-ping configured endpoints and surface availability. |
| **SBOM pipeline** | Generates and tracks software bills of materials per node. |
| **Alerts** | Configurable rules surfaced in the Security and Alerts dashboards. |

### 🤖 AI & Automation
| | |
|---|---|
| **AI Fleet Assistant** | Ask in plain language about fleet state. Auto-classifies intent — fleet query vs. Salt state generation vs. Ansible playbook generation — and responds accordingly. |
| **RAG over your fleet** | pgvector-backed retrieval over your playbooks, states, and events grounds every answer in your actual configuration, not generic knowledge. |
| **Bring your own LLM** | Local-first — Ollama, vLLM, and exo — or Anthropic. No data leaves your network unless you choose it to. |

---

## Architecture

kri runs three planes over a single Docker Compose stack:

```
    Browser (React)
         │
    nginx reverse proxy
         │
    FastAPI API ──── PostgreSQL (TimescaleDB)
         │                    │
    Celery workers ──── Redis  │
         │                    │
    salt-master ─── pgvector (RAG embeddings)
         │
    Fleet nodes (macOS / Linux)
    ┌──────────┐  ┌──────────┐  ┌──────────┐
    │ salt-min │  │ salt-min │  │ salt-min │
    └──────────┘  └──────────┘  └──────────┘
```

- **Control plane** — the FastAPI backend drives every operation: bootstrapping nodes, applying Salt states, running Ansible playbooks, and triggering drift scans. It issues commands to the salt-master over ZeroMQ and tracks results in PostgreSQL. Each fleet node runs a Salt minion; long-running work (drift scans, playbook runs, SBOM generation, key management) is offloaded to Celery workers across the `default`, `maintenance`, `drift`, and `sbom` queues, with Celery Beat driving scheduled checks.
- **Data plane** — node state is event-sourced. The drift engine snapshots Salt grains and custom returner output at configurable intervals, diffs against the baseline, and writes per-key drift scores as TimescaleDB hypertable records. Metrics, audit events, and job history all land in PostgreSQL.
- **AI plane** — playbooks, states, and fleet events are embedded into pgvector. The assistant retrieves relevant context, classifies the query intent, and routes to a fleet-query, state-generation, or playbook-generation path against your configured LLM.

The React frontend talks exclusively to the REST API; real-time updates use TanStack Query polling — no WebSocket layer.

---

## Sprint & Roadmap

### Current Sprint

**Sprint 2026-W23** (Mon 2 Jun – Sun 8 Jun)

```
Sprint 2026-W23  █████████░ 89% complete
████████████████████ 8 / 9 issues closed
```

[![Open P0/P1](https://img.shields.io/github/issues/hellodk/kri/p1-high?label=P1%20open&color=red)](https://github.com/hellodk/kri/issues?q=is%3Aopen+label%3Ap1-high)
[All open issues for this sprint](https://github.com/hellodk/kri/issues?q=is%3Aopen+milestone%3A%22Sprint+2026-W23%22)

### Roadmap

| Now | Next | Later |
|-----|------|-------|
| RAG pipeline live | Salt master on mm1 (native) | LLM fine-tuning on fleet telemetry |
| macOS config profiles | System health service management | Multi-tenant RBAC |
| Bootstrap UX overhaul | Token budget unified across LLM paths | Kubernetes node support |
| AI recommendations on NodeDetail | Per-key decrypt isolation | Cost tracking per node |

---

## Development Velocity

Sprints run weekly, Monday–Sunday. Story points: 1 (trivial) → 8 (split it — if a task is an 8, decompose it first).

The [project board](https://github.com/hellodk/kri/issues) tracks work through five columns: **Backlog → This Sprint → In Progress → In Review → Done**. Issues cannot enter "This Sprint" without written acceptance criteria. PRs must reference an issue (`Closes #N`). No orphan PRs, no retroactive tickets.

CI gates on every PR to master:
- `pytest tests/unit/ -v` — zero failures
- `npm run build` — zero TypeScript errors
- `mypy`, `ruff`, `bandit` — zero violations
- 80% line coverage floor on `fleet_platform/services/`

Red CI blocks merge. No exceptions, no `--no-verify`.

---

## Quick Start

kri runs on a laptop, a NUC, or a rack server — anything that runs Docker Compose. It manages **macOS and Linux nodes alike**, not just Mac Minis.

```bash
# Clone the repository
git clone https://github.com/hellodk/kri.git
cd kri

# Copy and fill in environment secrets
cp .env.docker.example .env.docker
# Edit .env.docker — set POSTGRES_PASSWORD, REDIS_PASSWORD, JWT_SECRET,
# SEED_LOCAL_ADMIN_EMAIL, SEED_LOCAL_ADMIN_PASSWORD (first admin account), etc.

# Start the full stack (API, worker, beat, salt-master, frontend, db, redis)
docker compose -f deploy/docker-compose.yml up -d
```

Then open **http://localhost** and log in with the `SEED_LOCAL_ADMIN_EMAIL` / `SEED_LOCAL_ADMIN_PASSWORD` you set in `.env.docker`.

> The salt-master can run inside Docker (convenient for development) or natively on a dedicated fleet node (recommended for production). Point the API at the master via `.env.docker`.

The stack exposes:

| Service | URL |
|---------|-----|
| Frontend | http://localhost:80 |
| API | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| Salt ZeroMQ publisher | :4505 |
| Salt ZeroMQ request/reply | :4506 |

---

## Managed Node Requirements

A node joins the fleet when it meets these requirements:

- **OS** — macOS 12+ or Linux (Ubuntu / Debian / RHEL / Arch).
- **Reachability** — SSH-reachable from the kri host for the initial bootstrap.
- **Salt minion** — installed automatically by kri during bootstrap; no manual setup needed.
- **macOS config profiles (optional)** — macOS 13+ with the standard `profiles` binary available.

---

## Tech Stack

| Layer | Technologies |
|-------|-------------|
| **Backend** | FastAPI, SQLAlchemy 2.0 async, PostgreSQL 17 (TimescaleDB), Redis 7, Celery, asyncssh |
| **Automation** | SaltStack (salt-master + minions), Ansible, ansible-runner |
| **AI** | pgvector (RAG embeddings), local LLM support (Ollama, vLLM, exo) and Anthropic |
| **Frontend** | React 18, TanStack Query 5, Tailwind CSS, Vite, xterm.js, noVNC |
| **Infrastructure** | Docker Compose, Nginx, Alembic migrations |
| **Observability** | Prometheus, Grafana, OpenTelemetry, Trivy security scanning |
| **Testing** | pytest, pytest-asyncio, Playwright E2E |

---

## Development

```bash
# Install Python dependencies into the project venv
uv sync --extra dev

# Activate the venv (required before any Python/pytest/alembic command)
source .venv/bin/activate

# Install frontend dependencies
cd frontend && npm ci && cd ..

# Apply database migrations
alembic upgrade head

# Run the API locally (needs a running DB and Redis)
uvicorn fleet_platform.api.main:app --reload --host 0.0.0.0 --port 8000

# Run the Celery worker locally
celery -A fleet_platform.workers.celery_app worker --queues default,maintenance,drift,sbom --concurrency 4 --loglevel info
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full branching, TDD, and PR workflow.

---

## Testing

kri follows a strict test pyramid. All layers must be green before a PR can merge.

| Layer | Location | Command | Notes |
|-------|----------|---------|-------|
| **Unit** | `tests/unit/` | `pytest tests/unit/ -q` | Pure logic, no I/O — runs in under 5 s |
| **Integration** | `tests/integration/` | `pytest tests/integration/ -q` | Real PostgreSQL instance, no mocks |
| **E2E** | `tests/e2e/` | `npx playwright test` | Full user journeys against a running stack |

Run before every commit:

```bash
source .venv/bin/activate
pytest tests/unit/ -q
pytest tests/integration/ -q
cd frontend && npm run build   # TypeScript type check
```

E2E tests run on staging via CI. See [TESTING.md](TESTING.md) for the full test strategy.

---

## Project Structure

```
kri/
├── fleet_platform/        # Backend Python package
│   ├── api/               # FastAPI routers and app entrypoint
│   ├── models/            # SQLAlchemy ORM models
│   ├── schemas/           # Pydantic request/response schemas
│   ├── services/          # Business logic (drift engine, playbook runner, SBOM, AI, etc.)
│   └── workers/           # Celery app, tasks, and beat schedule
├── frontend/              # React 18 SPA
│   └── src/
│       ├── pages/         # One file per route (Dashboard, Nodes, Playbooks, etc.)
│       ├── components/    # Shared UI components
│       ├── api/           # Typed fetch wrappers (mirrors Pydantic schemas)
│       └── stores/        # Zustand global state
├── tests/
│   ├── unit/              # Fast, pure-logic tests
│   ├── integration/       # API endpoint tests with real DB
│   └── e2e/               # Playwright specs mapped to acceptance criteria
├── deploy/                # Docker Compose files, Dockerfiles, Nginx config
├── salt/                  # Salt states applied to fleet nodes
├── playbooks/             # Ansible playbooks and roles
├── alembic/               # Database migration scripts
└── docs/                  # Architecture diagrams and design documents
```

---

## Contributing

Work starts with a GitHub issue carrying acceptance criteria and a tests checklist, then a branch off `master`, then a PR that closes the issue. Tests come before implementation (TDD), and the full suite must be green before merge. See [CONTRIBUTING.md](CONTRIBUTING.md) for the complete workflow and [TESTING.md](TESTING.md) for the test strategy.

Track sprint progress on the [kri Fleet Platform — GitHub Projects board](https://github.com/users/hellodk/projects/2).

---

## License

Proprietary — see [LICENSE](LICENSE) for details.
