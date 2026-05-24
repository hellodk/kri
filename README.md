# kri — Mac Mini Fleet Platform

[![CI](https://github.com/hellodk/kri/actions/workflows/ci.yml/badge.svg)](https://github.com/hellodk/kri/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/release/hellodk/kri?label=release)](https://github.com/hellodk/kri/releases)
[![Issues](https://img.shields.io/github/issues/hellodk/kri)](https://github.com/hellodk/kri/issues)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Kri ("Create" in Sanskrit) — an enterprise-grade fleet management platform for Apple Mac Mini hardware. Manages bootstrapping, drift detection, configuration, Ansible playbook execution, and SaltStack integration across a fleet of Mac Minis.

## Features

| Feature | Status |
|---------|--------|
| Node bootstrapping (SaltStack + SSH) | ✅ |
| Real-time drift detection | ✅ |
| Ansible playbook & role runner | ✅ |
| Bulk group operations | ✅ |
| SBOM pipeline | ✅ |
| Celery task queue + Redis | ✅ |
| JWT authentication | ✅ |
| WebSSH terminal in browser | ✅ |
| Security dashboard (Trivy, SonarQube) | ✅ |
| E2E Playwright test suite | 🚧 |

## Tech Stack

- **Backend:** FastAPI · SQLAlchemy 2.0 async · Celery · PostgreSQL (TimescaleDB) · Redis
- **Frontend:** React 18 · TanStack Query 5 · Tailwind CSS · Vite
- **Automation:** SaltStack · Ansible · ansible-runner
- **Infrastructure:** Docker Compose · Nginx

## Quick Start

```bash
git clone https://github.com/hellodk/kri.git && cd kri
cp deploy/.env.example deploy/.env   # fill in secrets
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.override.yml up -d
```

App: http://localhost:3000 · API docs: http://localhost:8000/docs

## Development

```bash
uv sync --extra dev          # Python deps (into project venv)
cd frontend && npm ci        # JS deps
source .venv/bin/activate
pytest tests/unit/ -q        # unit tests — must pass before every commit
pytest tests/integration/ -q # integration tests — needs running Docker stack
cd frontend && npm run build  # TypeScript check
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for branching, TDD workflow, and PR requirements.

## Testing

| Layer | Count | Command |
|-------|-------|---------|
| Unit | 118 tests | `pytest tests/unit/ -q` |
| Integration | 95 tests | `pytest tests/integration/ -q` |
| E2E | 16 spec files | `npx playwright test` |

## Project Board

[kri Fleet Platform — GitHub Projects](https://github.com/users/hellodk/projects/2)

## License

MIT
