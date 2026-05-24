# Audit Fix Plan 7 — Critical Bugs & Quick Wins

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all correctness bugs and quick security wins identified in the external audit: JWT production guard, status enum mismatch, per-node execution filter, pagination caps, storage_gb grain, IP validation, group predicate validation, and seed script.

**Architecture:** All fixes are surgical edits to existing files — no new tables, no new services. Each task is fully independent and can be merged individually. Tests are added or updated for each fix.

**Tech Stack:** Python 3.13, FastAPI 0.115, SQLAlchemy 2.0 async, pytest-asyncio, React 18, TypeScript.

---

## Task 1: JWT Production Guard (C1)

**Files:**
- Modify: `fleet_platform/core/config.py`
- Test: `tests/unit/test_config.py`

The default `jwt_secret = "insecure-dev-secret"` has no guard. If deployed to production with the default, all tokens can be forged by anyone who reads the repo.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_config.py
import pytest
from pydantic import ValidationError


def test_insecure_jwt_secret_rejected_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", "insecure-dev-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:x@localhost/x")
    from importlib import reload
    import fleet_platform.core.config as cfg_module
    with pytest.raises(ValueError, match="JWT_SECRET"):
        reload(cfg_module)
    reload(cfg_module)  # restore


def test_short_jwt_secret_rejected_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", "tooshort")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:x@localhost/x")
    from importlib import reload
    import fleet_platform.core.config as cfg_module
    with pytest.raises(ValueError, match="JWT_SECRET"):
        reload(cfg_module)
    reload(cfg_module)  # restore


def test_good_jwt_secret_accepted_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET", "a" * 32)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:x@localhost/x")
    from importlib import reload
    import fleet_platform.core.config as cfg_module
    reload(cfg_module)
    assert cfg_module.settings.environment == "production"
    reload(cfg_module)  # restore to dev defaults
```

- [ ] **Step 2: Run to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/unit/test_config.py -v
```

Expected: all 3 FAIL (no validation logic yet).

- [ ] **Step 3: Add production validation to config.py**

```python
# fleet_platform/core/config.py
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_SECRETS = {"insecure-dev-secret", "change-me-generate-with-openssl-rand-hex-32", ""}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://fleet:fleet@localhost:5432/fleet_platform"
    test_database_url: str = "postgresql+psycopg://fleet:fleet@localhost:5432/fleet_test"
    redis_url: str = "redis://:redispass@localhost:6379/0"

    jwt_secret: str = "insecure-dev-secret"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7

    frontend_origin: str = "http://localhost:5173"
    environment: str = "development"

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.environment == "production":
            if self.jwt_secret in _INSECURE_SECRETS or len(self.jwt_secret) < 32:
                raise ValueError(
                    "JWT_SECRET must be at least 32 characters and not a default/example value "
                    "when ENVIRONMENT=production. Generate with: openssl rand -hex 32"
                )
        return self

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


settings = Settings()

VERSION = "0.1.0"
```

- [ ] **Step 4: Run tests**

```bash
source .venv/bin/activate && pytest tests/unit/test_config.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add fleet_platform/core/config.py tests/unit/test_config.py
git commit -m "fix(C1): reject insecure JWT_SECRET when ENVIRONMENT=production"
```

---

## Task 2: Fix status "complete" → "completed" (C10)

**Files:**
- Modify: `fleet_platform/api/routes/ingest.py:134`
- Test: `tests/integration/test_ingest_executions.py`

Salt-ingested jobs are written with `status="complete"` (no trailing `d`). The frontend filter and all UI tests use `"completed"`. Every Salt execution appears broken in the UI.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_ingest_executions.py`:

```python
async def test_execution_status_is_completed_not_complete(client: AsyncClient, node_with_token):
    """Ingested executions must use 'completed', not 'complete'."""
    node, token = node_with_token
    payload = {
        "jid": "20260517999999.111",
        "fun": "state.apply",
        "success": True,
        "retcode": 0,
        "return": {},
    }
    r = await client.post(
        f"/api/v1/ingest/executions",
        json=payload,
        headers={"X-Node-Token": token, "X-Minion-ID": node.minion_id},
    )
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    # Fetch via public API — must appear in "completed" filter
    token_resp = await client.post("/auth/login", json={"email": "admin-test@fleet.local", "password": "admin123"})
    headers = {"Authorization": f"Bearer {token_resp.json()['access_token']}"}
    jobs = await client.get("/api/v1/executions?status=completed", headers=headers)
    ids = [j["id"] for j in jobs.json()["items"]]
    assert job_id in ids
```

- [ ] **Step 2: Run to confirm it fails**

```bash
source .venv/bin/activate && pytest tests/integration/test_ingest_executions.py::test_execution_status_is_completed_not_complete -v
```

Expected: FAIL — `job_id not in ids` (because status is stored as `"complete"`).

- [ ] **Step 3: Fix ingest.py line 134**

In `fleet_platform/api/routes/ingest.py`, change:
```python
        status="complete",
```
to:
```python
        status="completed",
```

- [ ] **Step 4: Run the test**

```bash
source .venv/bin/activate && pytest tests/integration/test_ingest_executions.py -v
```

Expected: all existing tests + new test pass.

- [ ] **Step 5: Commit**

```bash
git add fleet_platform/api/routes/ingest.py tests/integration/test_ingest_executions.py
git commit -m "fix(C10): status='complete' → 'completed' in execution ingest (Salt jobs invisible to UI filter)"
```

---

## Task 3: Per-node execution filter in NodeDetail (L13)

**Files:**
- Modify: `frontend/src/pages/NodeDetail.tsx`

The Executions tab calls `executionsApi.list({page, per_page})` with no `node_id` — it shows all fleet executions. Fix: pass `node_id`.

- [ ] **Step 1: Fix NodeDetail.tsx**

Find the executions query (around line 55) in `frontend/src/pages/NodeDetail.tsx`:

```tsx
  const { data: executions } = useQuery({
    queryKey: ['executions-node', nodeId, execPage],
    queryFn: () => executionsApi.list({ page: execPage, per_page: 25 }),
    staleTime: 10_000,
    enabled: !!nodeId && tab === 'executions',
  })
```

Change to:

```tsx
  const { data: executions } = useQuery({
    queryKey: ['executions-node', nodeId, execPage],
    queryFn: () => executionsApi.list({ node_id: nodeId!, page: execPage, per_page: 25 }),
    staleTime: 10_000,
    enabled: !!nodeId && tab === 'executions',
  })
```

- [ ] **Step 2: Fix executionsApi to accept node_id as string**

In `frontend/src/api/executions.ts`, the `list` params currently type `node_id` as `uuid.UUID | None` on the backend but we pass a string from the frontend. Update:

```typescript
// frontend/src/api/executions.ts
export const executionsApi = {
  list: (params?: { status?: string; node_id?: string; page?: number; per_page?: number }) => {
    const q = new URLSearchParams()
    if (params?.status) q.set('status', params.status)
    if (params?.node_id) q.set('node_id', params.node_id)
    if (params?.page) q.set('page', String(params.page))
    if (params?.per_page) q.set('per_page', String(params.per_page))
    return api.get<Paginated<ExecutionJob>>(`/api/v1/executions?${q}`)
  },
  get: (id: string) => api.get<ExecutionJob>(`/api/v1/executions/${id}`),
  results: (id: string, params?: { page?: number; per_page?: number }) => {
    const q = new URLSearchParams()
    if (params?.page) q.set('page', String(params.page))
    if (params?.per_page) q.set('per_page', String(params.per_page))
    return api.get<Paginated<ExecutionResult>>(`/api/v1/executions/${id}/results?${q}`)
  },
}
```

- [ ] **Step 3: TypeScript check**

```bash
cd /home/dk/Documents/git/kri/frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 4: Commit**

```bash
cd /home/dk/Documents/git/kri
git add frontend/src/pages/NodeDetail.tsx frontend/src/api/executions.ts
git commit -m "fix(L13): NodeDetail executions tab filters by node_id instead of showing all fleet jobs"
```

---

## Task 4: Pagination caps (M1)

**Files:**
- Modify: `fleet_platform/api/routes/nodes.py`, `drift.py`, `executions.py`, `sbom.py`, `groups.py`, `baselines.py`, `fleet.py`

Every list endpoint accepts `?per_page=999999` with no upper bound — can materialise hundreds of MB. Add `ge=1, le=200` via FastAPI `Query`.

- [ ] **Step 1: Fix all list routes**

Replace bare `per_page: int = 25` with `per_page: int = Query(default=25, ge=1, le=200)` and `page: int = Query(default=1, ge=1)` in every list endpoint.

Also add `from fastapi import Query` to each file's imports where missing.

**nodes.py** (`list_nodes` around line 87):
```python
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
# ...
async def list_nodes(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=200),
    status_filter: str | None = Query(default=None, alias="status"),
    sort: str | None = None,
    ...
```

**drift.py** (`list_drift`, `get_node_drift_history`):
```python
from fastapi import APIRouter, Depends, HTTPException, Query, status
# ...
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=200),
```

**executions.py** (`list_executions`, `get_execution_results`):
```python
from fastapi import APIRouter, Depends, HTTPException, Query, status
# ...
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=200),
```

**sbom.py** (`list_scans`, `list_scan_components`, `search_sbom` limit):
```python
from fastapi import APIRouter, Depends, HTTPException, Query, status
# ...
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=200),
    # For search:
    limit: int = Query(default=50, ge=1, le=200),
```

**groups.py** (`list_groups`, `list_group_nodes`):
```python
from fastapi import APIRouter, Depends, HTTPException, Query, status
# ...
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=200),
```

**baselines.py** (`list_baselines`):
```python
from fastapi import APIRouter, Depends, HTTPException, Query, status
# ...
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=200),
```

**fleet.py** (`list_nodes` in fleet overview — if it has pagination):
Check if `fleet.py` has paginated endpoints and add caps if so.

- [ ] **Step 2: Write a regression test**

Add to `tests/integration/test_nodes_api.py`:
```python
async def test_per_page_capped_at_200(admin_client: AsyncClient):
    r = await admin_client.get("/api/v1/nodes?per_page=9999")
    assert r.status_code == 422  # FastAPI validation error


async def test_per_page_zero_rejected(admin_client: AsyncClient):
    r = await admin_client.get("/api/v1/nodes?per_page=0")
    assert r.status_code == 422
```

- [ ] **Step 3: Run tests**

```bash
source .venv/bin/activate && pytest tests/ -q
```

Expected: all pass (existing + 2 new).

- [ ] **Step 4: Commit**

```bash
git add fleet_platform/api/routes/
git commit -m "fix(M1): cap per_page at 200 and page at ge=1 on all list endpoints"
```

---

## Task 5: IP address validation in grain ingest (C7)

**Files:**
- Modify: `fleet_platform/api/routes/ingest.py`
- Test: `tests/integration/test_ingest_grains.py`

A grain reporting a bad IP like `"not-an-ip"` causes a psycopg INET cast error, rolling back the entire ingest (node fact not saved, drift not queued). Fix: validate the IP string before using it; skip silently if invalid.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_ingest_grains.py`:
```python
async def test_grain_ingest_bad_ip_does_not_crash(client: AsyncClient, registered_node):
    """A malformed IP in grains should not crash the ingest — it should be ignored."""
    node, token = registered_node
    grains = {
        "id": node.minion_id,
        "fqdn": node.hostname,
        "ip4_interfaces": {"en0": ["not-an-ip-address"]},
        "os": "MacOS",
    }
    r = await client.post(
        "/api/v1/ingest/grains",
        json={"minion_id": node.minion_id, "grains": grains},
        headers={"X-Node-Token": token},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"
```

- [ ] **Step 2: Run to confirm it fails**

```bash
source .venv/bin/activate && pytest tests/integration/test_ingest_grains.py::test_grain_ingest_bad_ip_does_not_crash -v
```

Expected: FAIL with 500 or a SQLAlchemy error.

- [ ] **Step 3: Add IP validation in ingest.py**

In `fleet_platform/api/routes/ingest.py`, update `_extract_node_updates`:

```python
import ipaddress

def _extract_node_updates(grains: dict) -> dict:
    ip: str | None = None

    def _is_valid_ip(addr: str) -> bool:
        try:
            ipaddress.ip_address(addr)
            return True
        except ValueError:
            return False

    _skip_prefixes = ("127.", "169.254.", "::1", "fe80")
    ip4 = grains.get("ip4_interfaces", {})
    for iface, addrs in ip4.items():
        if iface in ("lo", "lo0"):
            continue
        for addr in addrs:
            if not _is_valid_ip(addr):
                continue
            if not any(addr.startswith(p) for p in _skip_prefixes):
                ip = addr
                break
        if ip:
            break

    if ip is None:
        fqdn_ips = grains.get("fqdn_ip4", [])
        ip = next(
            (a for a in fqdn_ips if _is_valid_ip(a) and not any(a.startswith(p) for p in _skip_prefixes)),
            None,
        )

    return {
        "hostname": grains.get("fqdn") or grains.get("id"),
        "ip_address": ip,
        "os_version": grains.get("osrelease"),
        "os_build": grains.get("osbuild"),
        "hardware_model": grains.get("productname"),
        "cpu_cores": grains.get("num_cpus"),
        "ram_gb": grains.get("mem_total", 0) / 1024 if grains.get("mem_total") else None,
        "storage_gb": _extract_storage_gb(grains),
        "status": "online",
    }


def _extract_storage_gb(grains: dict) -> float | None:
    """Extract total storage from grains. Salt uses disk_total_size (MB) or disk_info."""
    # Try common Salt grain keys for disk size
    for key in ("disk_total", "disks_total_size"):
        val = grains.get(key)
        if val is not None:
            try:
                return float(val) / 1024  # MB → GB
            except (TypeError, ValueError):
                pass
    # disk_info: list of dicts with 'size' key in bytes
    disk_info = grains.get("disk_info", [])
    if isinstance(disk_info, list) and disk_info:
        try:
            total_bytes = sum(d.get("size", 0) for d in disk_info if isinstance(d, dict))
            if total_bytes:
                return round(total_bytes / (1024 ** 3), 1)
        except (TypeError, ValueError):
            pass
    return None
```

- [ ] **Step 4: Run tests**

```bash
source .venv/bin/activate && pytest tests/integration/test_ingest_grains.py -v
```

Expected: all pass including new test.

- [ ] **Step 5: Commit**

```bash
git add fleet_platform/api/routes/ingest.py tests/integration/test_ingest_grains.py
git commit -m "fix(C7/L12): validate IP before INET write; extract storage_gb from grains"
```

---

## Task 6: Validate predicate on group create (M12)

**Files:**
- Modify: `fleet_platform/api/routes/groups.py`
- Test: `tests/integration/test_groups_api.py`

`create_group` does not call `validate_predicate`. A dynamic group with `{"foo":"bar"}` gets created, matches nothing, and no error is surfaced.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_groups_api.py`:
```python
async def test_create_dynamic_group_invalid_predicate_returns_422(admin_client: AsyncClient):
    """Invalid predicate structure should be rejected at create time."""
    r = await admin_client.post("/api/v1/groups", json={
        "name": "bad-predicate-group",
        "type": "dynamic",
        "predicate": {"foo": "bar"},  # not and/or
    })
    assert r.status_code == 422
```

- [ ] **Step 2: Run to confirm it fails**

```bash
source .venv/bin/activate && pytest tests/integration/test_groups_api.py::test_create_dynamic_group_invalid_predicate_returns_422 -v
```

Expected: FAIL — currently returns 201.

- [ ] **Step 3: Add validate_predicate call in groups.py**

In `fleet_platform/api/routes/groups.py`, update `create_group`:

```python
from fleet_platform.services.group_resolver import validate_predicate

async def create_group(
    payload: GroupCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    if payload.type == "dynamic":
        if not payload.predicate:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Dynamic groups require a predicate",
            )
        if not validate_predicate(payload.predicate):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid predicate structure. Must be {\"and\": [...]} or {\"or\": [...]} "
                       "with {\"key\": \"...\", \"value\": \"...\"} conditions.",
            )
    group = Group(
        name=payload.name,
        description=payload.description,
        type=payload.type,
        predicate=payload.predicate,
        created_by=uuid.UUID(claims["sub"]),
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return _to_response(group, 0)
```

- [ ] **Step 4: Run all group tests**

```bash
source .venv/bin/activate && pytest tests/integration/test_groups_api.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add fleet_platform/api/routes/groups.py tests/integration/test_groups_api.py
git commit -m "fix(M12): validate predicate structure on dynamic group create"
```

---

## Task 7: Fix demo seed script (C12)

**Files:**
- Modify: `scripts/seed_demo_data.py`

Two bugs: `NodeFact(reported_at=...)` should be `collected_at=`, and `metadata=` collides with SQLAlchemy's reserved attribute (should be `metadata_=` or use the correct model field).

- [ ] **Step 1: Fix the seed script**

Read `fleet_platform/models/facts.py` and `fleet_platform/models/execution.py` to confirm correct field names, then update `scripts/seed_demo_data.py`:

```bash
source .venv/bin/activate && grep -n "collected_at\|reported_at\|metadata" \
  fleet_platform/models/facts.py fleet_platform/models/execution.py
```

Expected output shows `collected_at` in `NodeFact` and `metadata_` in `ExecutionJob`.

Fix in `scripts/seed_demo_data.py`:
1. Line ~207: `NodeFact(..., reported_at=node.last_seen_at)` → `NodeFact(..., collected_at=node.last_seen_at)`
2. Line ~289: `ExecutionJob(..., metadata={"args": []})` → `ExecutionJob(..., metadata_={"args": []})`

- [ ] **Step 2: Verify the script runs**

```bash
source .venv/bin/activate && PYTHONPATH=/home/dk/Documents/git/kri python scripts/seed_demo_data.py 2>&1 | tail -10
```

Expected: prints `✓ Demo data seeded successfully!` with counts.

- [ ] **Step 3: Commit**

```bash
git add scripts/seed_demo_data.py
git commit -m "fix(C12): correct field names in seed script (collected_at, metadata_)"
```

---

## Task 8: Full test suite verification

- [ ] **Step 1: Run the full suite**

```bash
source .venv/bin/activate && python -m pytest tests/ -q --no-header 2>&1 | tail -5
```

Expected: `160+ passed, 0 failed`

- [ ] **Step 2: TypeScript build check**

```bash
cd /home/dk/Documents/git/kri/frontend && npx tsc --noEmit && npm run build 2>&1 | tail -5
```

Expected: zero errors, `✓ built in Xs`

---

## Self-Review

**Spec coverage:**
- [x] C1: JWT production guard — Task 1
- [x] C7: IP validation — Task 5
- [x] C10: status "complete"→"completed" — Task 2
- [x] L12: storage_gb grain extraction — Task 5
- [x] L13: per-node execution filter — Task 3
- [x] M1: pagination caps — Task 4
- [x] M12: validate_predicate on group create — Task 6
- [x] C12: seed script fix — Task 7

**Not in this plan (covered in Plans 8-10):**
- C3: refresh token revocation
- C5: rate limiting
- C6: SBOM size limit
- C8: audit coverage
- H1: compute_drift retry
- H2: SBOM retry fix
- H3: health/readiness endpoint
- M3: alerting
- M4: node decommission
- M5: user management
