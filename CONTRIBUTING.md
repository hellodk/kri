# Contributing to kri

kri is a build fleet management platform. This guide covers everything you need to get a development environment running, follow the project's branching and testing conventions, and get your changes merged.

---

## Table of Contents

1. [Development Setup](#development-setup)
2. [Branching Strategy](#branching-strategy)
3. [TDD Workflow](#tdd-workflow)
4. [Running Tests](#running-tests)
5. [Submitting a Pull Request](#submitting-a-pull-request)
6. [Breaking Changes](#breaking-changes)

---

## Development Setup

### Prerequisites

- Python 3.13+ with [uv](https://docs.astral.sh/uv/)
- Node.js 20+ and [pnpm](https://pnpm.io/) 10+
- Docker + Docker Compose
- Git

### Steps

```bash
# 1. Clone the repository
git clone git@github.com:hellodk/kri.git
cd kri

# 2. Install Python dependencies (including dev extras)
uv sync --extra dev

# 3. Install frontend dependencies
cd frontend && pnpm install --frozen-lockfile && cd ..

# 4. Configure environment
cp .env.example .env
# Edit .env — set POSTGRES_PASSWORD, SECRET_KEY, etc.

# 5. Start backing services (PostgreSQL, Redis, etc.)
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.override.yml up -d

# 6. Activate the virtual environment
source .venv/bin/activate

# 7. Apply database migrations
alembic upgrade head
```

### Running the full stack locally

```bash
# Start all services (API, Celery worker, frontend dev server)
./scripts/kri start

# Verify everything is healthy
./scripts/kri status

# Tail logs for a specific service
./scripts/kri logs worker

# Stop everything cleanly
./scripts/kri stop
```

The API will be available at `http://localhost:8000` and the frontend dev server at `http://localhost:5173`.

---

## Branching Strategy

| Rule | Detail |
|------|--------|
| `master` is protected | Never commit directly to `master` |
| Branch naming | `feat/<slug>` · `fix/<slug>` · `chore/<slug>` |
| One issue → one branch → one PR | Keep scope tight |
| Merge strategy | Squash merge on PR approval |

### Examples

```
feat/playbook-runner        # new feature
fix/bootstrap-stuck-cancel  # bug fix
chore/update-dependencies   # housekeeping
```

Always branch from the latest `master`:

```bash
git checkout master
git pull origin master
git checkout -b feat/my-feature
```

---

## TDD Workflow

kri follows strict test-driven development. The cycle is:

1. **Write a failing test** that captures the intended behaviour.
2. **Run the test** to confirm it fails for the right reason (not a missing import or syntax error).
3. **Write the minimal implementation** to make the test pass.
4. **Run the full suite** — no regressions allowed.
5. **Commit** with a descriptive message.

The test file should exist (and fail) in the same commit that introduces the feature, or as a preparatory commit immediately before.

### Commit message conventions

```
feat: add playbook run endpoint with target resolution
fix: cancel bootstrap resets status to failed
chore: bump ansible-runner to 2.4.0
docs: document breaking schema change for BootstrapResponse
test: add integration tests for bulk bootstrap edge cases
```

---

## Running Tests

Always activate the virtual environment first:

```bash
source .venv/bin/activate
```

### Unit tests — fast, no database required

```bash
pytest tests/unit/ -q
```

### Integration tests — requires Docker DB running

```bash
# Ensure Docker services are up before running
docker compose -f deploy/docker-compose.yml up -d postgres redis

pytest tests/integration/ -q
```

### E2E tests — requires full stack on localhost:5173

```bash
# Start the full stack first
./scripts/kri start

cd frontend && npx playwright test
```

### Coverage check

```bash
pytest tests/unit/ --cov=fleet_platform/services --cov-report=term-missing
```

The CI gate requires 80% line coverage on `fleet_platform/services/`. Confirm you meet this floor before pushing.

### Pre-commit hooks

Install once after cloning:

```bash
uv sync --extra dev
source .venv/bin/activate
pre-commit install
```

Hooks run automatically on every `git commit`. To run manually:

```bash
pre-commit run --all-files
```

| Hook | What it catches |
|------|-----------------|
| ruff | Lint errors, unused imports — auto-fixed |
| ruff-format | Formatting drift — auto-fixed |
| check-yaml/toml/json | Config file syntax errors |
| mypy | Type errors in `fleet_platform/` |
| vulture | Dead code — unused functions/variables |
| bandit | Security smells (hardcoded secrets, SQL injection risk) |
| check-unit-test-presence | Warns if `services/*.py` has no matching unit test |
| check-contract-drift | Warns if Pydantic schema changed without TS interface update |

### TypeScript type check and production build

```bash
cd frontend && npx tsc --noEmit
cd frontend && pnpm run build
```

Both must succeed before a PR can merge.

---

## Submitting a Pull Request

### PR checklist

- [ ] Tests written before implementation (TDD)
- [ ] `pytest tests/unit/ tests/integration/ -q` passes locally with no failures
- [ ] `cd frontend && pnpm run build` succeeds without errors
- [ ] PR title is concise and references the change type (`feat:`, `fix:`, `chore:`)
- [ ] PR body references the issue with `Closes #N`
- [ ] All acceptance criteria from the linked issue are covered by tests
- [ ] Coverage floor (80% on `fleet_platform/services/`) is maintained

### What reviewers look for

- Tests exist and exercise the real code path (no trivial assertions)
- No mocks in integration tests — real database only
- TypeScript interfaces updated when Pydantic schemas change (same commit)
- No secrets, credentials, or `.env` files committed

---

## Breaking Changes

A breaking change is any modification that:

- Removes or renames a Pydantic response field
- Changes a field's type in a Pydantic schema
- Alters an API route path or HTTP method
- Removes a TypeScript interface property that the frontend depends on

### Process

1. Label the issue `breaking-change` before starting work.
2. Document the before/after in the PR body:

   ```
   ## Breaking change
   Before: `BootstrapResponse.salt_key_accepted: bool`
   After:  `BootstrapResponse.salt_key_deleted: bool` (field renamed)
   ```

3. Update the TypeScript interface **in the same commit** as the Pydantic schema change.
4. Note any migration steps operators must take in the PR description.

---

*Questions? Open a GitHub Discussion or mention `@hellodk` in the issue.*
