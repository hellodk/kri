# kri — Mac Mini Fleet Platform

[![CI](https://github.com/hellodk/kri/actions/workflows/ci.yml/badge.svg)](https://github.com/hellodk/kri/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/release/hellodk/kri?include_prereleases)](https://github.com/hellodk/kri/releases)
[![Issues](https://img.shields.io/github/issues/hellodk/kri)](https://github.com/hellodk/kri/issues)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Kri ("Create" in Sanskrit) — an enterprise-grade fleet management platform for Apple Mac Mini hardware. Manages bootstrapping, drift detection, configuration, Ansible playbook execution, and SaltStack integration across a fleet of Mac Minis.

---

## Features

| Feature | Description | Status |
|---------|-------------|--------|
| 🚀 Node bootstrapping | SSH-based onboarding — registers new Mac Minis, installs the Salt minion, and adds the node to the fleet | ✅ |
| 📊 Real-time drift detection | Scores each node against a stored baseline; surfaces configuration drift with per-key breakdowns | ✅ |
| 🧂 SaltStack state management | Applies Salt states across individual nodes or groups; tracks accepted and pending minion keys | ✅ |
| 📓 Ansible playbook execution | Discovers, runs, and tracks Ansible playbooks and roles; full job history with stdout streaming | ✅ |
| 💻 SSH multi-session terminal | Tabbed in-browser SSH terminal powered by asyncssh and xterm.js | ✅ |
| 🖥️ VNC remote desktop | Browser-based VNC access to any fleet node via noVNC | ✅ |
| 📈 Prometheus metrics + Grafana | Per-node and fleet-wide metrics exported to Prometheus; ready-made Grafana dashboards | ✅ |
| 📦 SBOM pipeline | Generates and tracks software bills of materials for each node | ✅ |
| 👥 Group management | Logical grouping of nodes for bulk operations, secrets scoping, and targeted playbook runs | ✅ |
| 🔐 Secrets management | Per-node and per-group encrypted secret storage with role-scoped access | ✅ |
| 🛡️ Role-based access control | Three-tier RBAC: viewer / operator / admin with JWT-authenticated sessions | ✅ |
| 📱 iOS device tracking | Tracks iOS devices associated with fleet Mac Minis | ✅ |
| 📋 Audit log | Immutable audit trail of every action across the platform | ✅ |
| 🔔 Alerts | Configurable alerting rules surfaced in the Security and Alerts dashboards | ✅ |
| 🤖 AI assistant | LLM-powered fleet assistant for natural-language queries and diagnostics | 🚧 In progress |

---

## Tech Stack

| Layer | Technologies |
|-------|-------------|
| **Backend** | FastAPI, SQLAlchemy 2.0 async, PostgreSQL 17 (TimescaleDB), Redis 7, Celery, asyncssh |
| **Automation** | SaltStack (salt-master + minions), Ansible, ansible-runner |
| **Frontend** | React 18, TanStack Query 5, Tailwind CSS, Vite, xterm.js, noVNC |
| **Infrastructure** | Docker Compose, Nginx, Alembic migrations |
| **Observability** | Prometheus metrics, Grafana dashboards, Trivy security scanning |
| **Testing** | pytest, pytest-asyncio, Playwright E2E |

---

## Quick Start

```bash
# Clone the repository
git clone https://github.com/hellodk/kri.git
cd kri

# Copy and fill in environment secrets
cp .env.docker.example .env.docker

# Start the full stack (API, worker, beat, salt-master, frontend, db, redis)
docker compose -f deploy/docker-compose.yml up -d
```

The stack exposes:

| Service | URL |
|---------|-----|
| Frontend | http://localhost:80 |
| API | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| Salt ZeroMQ publisher | :4505 |
| Salt ZeroMQ request/reply | :4506 |

---

## Architecture

Kri is built around a **Salt master agent model**. Each Mac Mini runs a Salt minion that connects to the central salt-master container over ZeroMQ. The FastAPI backend drives all operations — bootstrapping new nodes, applying states, triggering drift scans, and running Ansible playbooks — by issuing commands to the Salt master and tracking results in PostgreSQL (TimescaleDB).

Drift detection is **event-sourced**: the drift engine snapshots node state at configurable intervals using Salt grains and custom returners, diffs it against a stored baseline, and computes a per-key drift score. Results are time-series records in TimescaleDB, queryable over any window.

Celery workers handle all long-running tasks (drift scans, playbook runs, SBOM generation, key management) across four queues: `default`, `maintenance`, `drift`, and `sbom`. Celery Beat drives scheduled drift checks and maintenance windows.

The React frontend communicates exclusively through the FastAPI REST API. All real-time updates use TanStack Query polling — no WebSocket complexity.

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

Kri follows a strict test pyramid. All layers must be green before a PR can merge.

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
│   ├── services/          # Business logic (drift engine, playbook runner, SBOM, etc.)
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

## Project Board

Track sprint progress on the [kri Fleet Platform — GitHub Projects board](https://github.com/users/hellodk/projects/2).

---

## License

MIT — see [LICENSE](LICENSE) for details.
