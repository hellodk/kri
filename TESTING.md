# Testing Guide

Living reference for engineers working on kri. This document covers how to run tests, when to write which type, and what quality gates block a merge.

---

## Quick start

```bash
# Activate the venv first — always
source .venv/bin/activate

# Run unit tests (fast, run before every commit)
pytest tests/unit/ -v

# Run integration tests (need DB)
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.override.yml up -d db
pytest tests/integration/ -v

# Run E2E tests (need full stack)
./scripts/kri.sh start
./scripts/kri.sh test

# Run a specific E2E spec file
./scripts/kri.sh test bootstrap

# Run all with coverage report
pytest tests/unit/ tests/integration/ --cov=fleet_platform --cov-report=term-missing
```

---

## Test types and when to write them

| Type | Location | When to write | Speed |
|---|---|---|---|
| Unit | `tests/unit/test_{module}.py` | For every new function or class | < 1s each |
| Integration | `tests/integration/test_{feature}.py` | For every new endpoint or DB query | < 30s each |
| Contract | `scripts/schema_drift_check.py` (planned) | After adding/changing any API field | < 5s |
| E2E | `tests/e2e/{feature}.spec.ts` | For every new user journey | < 30s each |

### Unit tests

Test isolated functions with no network, no DB, no filesystem. Use mocks only at the outermost boundary (HTTP client, filesystem path). The database in unit tests uses a real in-memory SQLite engine — mock the DB session only when testing logic above the DB layer.

**Pattern:** one `pytest_asyncio.fixture(scope="module")` for the engine, one for the app with dependency overrides, one for auth headers. Tests are pure assertions with no setup logic.

### Integration tests

Use a real PostgreSQL instance (via Docker). Each test session rolls back with `await session.rollback()`. No mocking of the DB or FastAPI layers. Integration tests prove that the SQL queries, schema migrations, and business logic work together.

**Pattern:** `conftest.py` at `tests/integration/` provides `db`, `client`, and `admin_headers` fixtures shared across all integration test files.

### E2E tests

Full browser + real server + real DB. Written in TypeScript with Playwright. Always use `loginViaApi()` from `helpers.ts` — never fill in the login form in a test. Each test has an ID (e.g. `BOOT-04`) traceable to `TEST_CASES.md`.

**Assert behaviour, not implementation.** Assert that an input is readonly, that text is visible, that an API returns a status code. Never assert on CSS classes or internal React state.

### Contract tests (planned — next sprint)

A Python script that exports Pydantic JSON schemas and diffs them against the TypeScript interfaces. Run in CI after `tsc --noEmit`. Exits non-zero on any field name or type drift — blocks merge.

---

## Running tests locally

### Unit tests only (fastest — run before every commit)

```bash
source .venv/bin/activate
pytest tests/unit/ -v --tb=short
```

### Unit + integration (run before opening a PR)

```bash
# Start DB
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.override.yml up -d db

source .venv/bin/activate
pytest tests/unit/ tests/integration/ -v --cov=fleet_platform --cov-fail-under=60
```

### E2E tests

```bash
# Start the full stack
./scripts/kri.sh start

# Run all E2E tests (line reporter — compact output)
./scripts/kri.sh test

# Run one spec file
./scripts/kri.sh test bootstrap

# Run with full HTML report (open in browser after)
npx playwright test --reporter=html

# Run only API-level E2E tests (no browser, faster)
npx playwright test --grep "@api" --reporter=line
```

### TypeScript build check

```bash
cd frontend
npx tsc --noEmit
```

This must pass with zero errors before any PR. It is the consumer-side contract check.

---

## Coverage requirements — what blocks merge

All of the following must be true before a PR can merge:

- [ ] `tsc --noEmit` exits zero (TypeScript build clean)
- [ ] All unit tests pass (zero failures, zero skips unless marked xfail)
- [ ] All integration tests pass
- [ ] E2E test count does not decrease from the previous run
- [ ] `pytest --cov-fail-under=60` passes (line coverage ≥ 60%)
- [ ] No secrets in the diff (pre-push hook checks with gitleaks)
- [ ] PR links to an issue and includes a test plan in the description

There are no exceptions. Removing a gate "just this once" is how technical debt accumulates.

---

## Journey coverage matrix

Current state as of May 2026. Update this table when you add or remove tests.

| User Journey | Unit | Integration | E2E | Overall |
|---|---|---|---|---|
| Add / check node | ✓ test_check_minion_id | ✓ test_node_registration | ✓ fleet.spec.ts | Good |
| Bootstrap node | — | ✓ test_ansible_api | ✓ BOOT-01..22 | Partial |
| Salt key approval | — | — | — | **None** |
| Grain collection | — | ✓ test_ingest_grains | — | Partial |
| Drift detection | ✓ test_drift_engine | ✓ test_drift_api | ✓ DRIFT-* | Good |
| SBOM scan | ✓ test_sbom_parser | ✓ test_sbom_api | ✓ partial | Partial |
| Security dashboard | — | — | ✓ SEC-01..06 | Partial |
| Node secrets → pillar | — | — | — | **None** |
| Group secrets | — | ✓ test_groups_api | ✓ partial | Partial |
| Minion key lifecycle | — | — | — | **None** |
| Playbook execution | ✓ test_playbook_tasks | ✓ test_playbook_api | ✓ PLAY-01..21 | Good |
| Auth & sessions | ✓ test_auth_core | ✓ test_auth_endpoints | ✓ AUTH-01..07 | Good |

Rows marked **None** are the highest-risk areas. A regression there produces zero signal from CI.

---

## TDD workflow step-by-step

1. **Read the issue.** Acceptance criteria must be written in the issue before you start. If they are not there, write them and get agreement. Code without AC is untestable.

2. **Write the failing test first.** For a backend feature: write a unit test that calls the function or endpoint with the expected input and asserts the expected output. Run it — it must fail. If it passes, the test is wrong.

3. **Write the minimal implementation.** Write just enough code to make the test pass. Resist the urge to gold-plate. The test defines done.

4. **Run the test.** It must turn green. If it does not, fix the implementation, not the test.

5. **Refactor.** Clean up the implementation. Add docstrings. Extract helper functions. Run the test again — it must stay green.

6. **Add edge case tests.** Auth failure test, invalid input test (422), not-found test (404). These are not optional — they are part of the definition of done for any endpoint.

7. **Write the E2E test.** Once the backend is complete, write a Playwright test for the user-visible behaviour. Use `loginViaApi()`. Give the test an ID. Add the ID to `TEST_CASES.md`.

8. **Open the PR.** Include: link to the issue, list of new tests added, summary of what the tests verify.

---

## Writing good tests — conventions

### Test IDs

E2E tests use IDs matching `TEST_CASES.md`:
- `BOOT-01` through `BOOT-22` — bootstrap flows
- `DRIFT-01` through `DRIFT-*` — drift detection
- `SEC-01` through `SEC-06` — security dashboard
- `AUTH-01` through `AUTH-07` — authentication
- `PLAY-01` through `PLAY-21` — playbook execution
- New features: pick the next available prefix (e.g. `KEY-01` for key lifecycle)

### Naming

```python
# Unit tests: test_{thing_being_tested}_{expected_outcome}
async def test_taken_minion_id_returns_available_false(): ...
async def test_invalid_minion_id_format_rejected_with_422(): ...
async def test_unauthenticated_request_returns_401(): ...
```

```typescript
// E2E tests: 'TEST-ID description of user behaviour'
test('BOOT-04 IP field locked for existing node', async ({ page }) => { ... })
```

### Minimum coverage per endpoint

Every new backend endpoint needs at minimum:
- 1 unit or integration test for the happy path (correct input → correct output)
- 1 test for authentication failure (no token → 401)
- 1 test for invalid input (bad body → 422)

Every new UI feature needs at minimum:
- 1 E2E test for the happy path
- 1 E2E test or component test for the error state

### What to mock vs. what to keep real

| Keep real | Mock / fake |
|---|---|
| Database (use test engine) | Redis (use `AsyncMock`) |
| FastAPI routing | External HTTP services (Ansible, Salt API) |
| Pydantic validation | Rate limiter (use `memory://` storage) |
| Business logic | Celery tasks (use `.delay()` mock or `CELERY_TASK_ALWAYS_EAGER`) |
| File system operations in unit scope | External PKI directory (use `tmp_path`) |

### Async fixtures

All fixtures that touch the DB or app must be `pytest_asyncio.fixture` with matching `loop_scope`. Do not mix sync and async fixtures in the same module scope.

```python
@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def admin_client(app_with_test_db, auth_headers):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_test_db),
        base_url="http://testserver",
        headers=auth_headers,
    ) as ac:
        yield ac
```

---

## Known gaps

These are the current coverage holes ranked by risk. They are tracked as issues.

**High risk (no coverage at all):**
- Salt key lifecycle (approve, reject, delete) — no tests at any layer
- Node secrets → pillar write path — no tests at any layer
- Minion key rotation — no tests at any layer

**Medium risk (partial coverage):**
- Bootstrap node: no unit-level test for the salt key deletion logic specifically
- Contract drift between Pydantic schemas and TypeScript interfaces — no automated check; `salt_key_deleted` field is already drifted
- Grain collection: integration test exists but no E2E coverage

**Low risk (covered but not deeply):**
- Security dashboard: E2E covers page load and API shape, not the full scan → result cycle
- SBOM scan: E2E is partial; the Trivy integration path is not end-to-end tested

---

## Planned improvements

Listed in priority order:

1. **Contract drift detection script** — extract Pydantic JSON schemas, diff against TypeScript interfaces, run in CI. Fixes the `salt_key_deleted` drift immediately. Estimated: 1 sprint.

2. **Salt key lifecycle E2E** — `KEY-01` through `KEY-05` covering: pending key appears, approve key, reject key, delete accepted key, re-bootstrap clears old key. Estimated: 1 sprint.

3. **Node secrets → pillar integration test** — verify that saving a node secret creates the correct pillar file at the correct path with encrypted content. Estimated: 0.5 sprints.

4. **Component tests (Vitest + Testing Library)** — start with `BootstrapModal`, `FleetDashboard`, and `NodeDetail`. Run in jsdom, no browser required. Estimated: 1–2 sprints.

5. **Mutation score baseline** — run `mutmut` against the unit test suite, establish a baseline score, add it to CI with a `--min-score=70` gate. Estimated: 1 sprint.

6. **Hypothesis property-based tests** — start with `is_valid_minion_id`, grain extraction parsing, and drift score calculation. Estimated: 0.5 sprints.

7. **Visual regression baseline** — once the dashboard layout is stable, add Playwright screenshot comparisons with a 1% pixel tolerance. Not before UI is stable.
