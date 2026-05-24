# Testing Reference — kri

This is the living test reference for the kri fleet management platform. It describes the test inventory, philosophy, coverage requirements, contract testing rules, known gaps, and CI gates.

For the full manual and API test case catalogue, see [`docs/TEST_CASES.md`](docs/TEST_CASES.md).

---

## Test Inventory

| Suite | Location | Approximate Count | Command |
|-------|----------|-------------------|---------|
| Unit | `tests/unit/` | ~112 | `pytest tests/unit/ -q` |
| Integration | `tests/integration/` | ~95 | `pytest tests/integration/ -q` |
| E2E | `tests/e2e/` | growing | `npx playwright test` |

Run everything at once (requires Docker DB):

```bash
source .venv/bin/activate
pytest tests/unit/ tests/integration/ -q
```

---

## Test Pyramid Philosophy

### Unit tests (base of the pyramid)

Unit tests cover individual functions and service methods in isolation. They must not touch the database, filesystem, or network — any dependency is mocked. Because they need no infrastructure, they run in seconds and are the first feedback loop during development. Every new service method, validator, and utility function gets a unit test before the implementation is written.

### Integration tests (middle layer)

Integration tests exercise full request/response cycles against a real PostgreSQL database (running in Docker). No mocks — the goal is to catch ORM issues, constraint violations, and schema mismatches that unit tests cannot surface. An integration test that passes with mocks but fails against the real DB is a false positive; kri avoids this by design.

### E2E tests (top of the pyramid)

E2E tests use Playwright to drive a real browser against the full running stack (frontend + API + Celery + PostgreSQL + Redis). They are the most expensive to run and the slowest to fail, so they focus on critical user journeys (bootstrap, playbook run, group management) rather than exhaustive UI coverage. They run manually against a staging environment; CI inclusion is a known gap (see below).

---

## Coverage Requirements

| Scope | Requirement | Enforcement |
|-------|-------------|-------------|
| `fleet_platform/services/` | 75% line coverage minimum | Enforced in CI — PR blocked if floor not met |
| `fleet_platform/workers/` | Best effort | Not enforced; aim for 60%+ |
| `fleet_platform/api/routes/` | Covered by integration tests | Not separately enforced |
| Integration tests | No mocks — real DB only | Code review policy |

Check coverage locally before pushing:

```bash
source .venv/bin/activate
pytest tests/unit/ --cov=fleet_platform/services --cov-report=term-missing
```

---

## Contract Testing

Every Pydantic response schema in `fleet_platform/schemas/` must have a matching TypeScript interface in `frontend/src/api/` (or `frontend/src/types/`). This is the contract between the backend API and the frontend consumer.

### Rules

1. When a Pydantic schema field is added, renamed, or removed, the corresponding TypeScript interface must be updated in the same commit.
2. Optional fields (`field: Optional[str] = None`) map to TypeScript optional properties (`field?: string`).
3. Never let a Python schema and its TypeScript counterpart diverge across commits — reviewers will catch this and request changes.

### Key schema/interface pairs

| Python schema | TypeScript interface |
|---------------|----------------------|
| `fleet_platform/schemas/ansible.py` → `BootstrapResponse` | `frontend/src/api/` → `BootstrapResponse` |
| `fleet_platform/schemas/nodes.py` → `NodeResponse` | `frontend/src/api/` → `NodeResponse` |
| `fleet_platform/schemas/groups.py` → `GroupResponse` | `frontend/src/api/` → `GroupResponse` |
| `fleet_platform/schemas/baselines.py` → `BaselineResponse` | `frontend/src/api/` → `BaselineResponse` |

When in doubt, run the TypeScript compiler to catch interface mismatches:

```bash
cd frontend && npx tsc --noEmit
```

---

## Known Gaps

| Gap | Status | Notes |
|-----|--------|-------|
| E2E tests not in CI | Open | Needs full Docker stack (API + frontend + DB + Redis + Celery) in CI runner. Tracked as a future enhancement. |
| Mutation testing | Not started | [Mutmut](https://mutmut.readthedocs.io/) is the planned tool. Not yet wired. |
| Property-based testing | Not started | [Hypothesis](https://hypothesis.readthedocs.io/) would benefit service-layer validators. Not yet added. |
| Load / performance tests | Not started | No benchmarks or k6/Locust scenarios yet. |

---

## CI Gates

CI runs on every pull request targeting `master` via `.github/workflows/ci.yml`.

| Gate | Trigger | Command | Blocking? |
|------|---------|---------|-----------|
| TypeScript build | Every PR | `cd frontend && npm run build` | Yes |
| Unit tests | Every PR | `pytest tests/unit/ -q` | Yes |
| Integration tests | After unit tests pass | `pytest tests/integration/ -q` | Yes |
| Coverage floor | After unit tests | 75% on `fleet_platform/services/` | Yes |
| E2E tests | Manual / staging only | `npx playwright test` | No (not in CI yet) |

A PR cannot merge until all blocking gates are green.

---

## Writing a New Test

### Unit test skeleton

```python
# tests/unit/test_my_service.py
from fleet_platform.services.my_service import do_thing

def test_do_thing_returns_expected_value():
    result = do_thing(input="valid")
    assert result == "expected"

def test_do_thing_raises_on_invalid_input():
    with pytest.raises(ValueError, match="invalid"):
        do_thing(input=None)
```

### Integration test skeleton

```python
# tests/integration/test_my_route.py
def test_create_resource(client, db_session):
    response = client.post("/api/v1/my-resource", json={"name": "test"}, headers=auth_headers)
    assert response.status_code == 201
    assert response.json()["name"] == "test"
```

Integration tests receive a real `db_session` from the pytest fixtures defined in `tests/conftest.py`. Do not mock the session.

---

*Last updated: 2026-05-24*
