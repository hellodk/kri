# kri Backend — Optimisation Analysis

## Architecture Context

```
FastAPI (async) ──── PostgreSQL 17 (TimescaleDB) + pgvector
       │
Celery workers ──── Redis 7 (queues: default, maintenance, drift, sbom)
       │
salt-master ──── Fleet nodes (salt-minion on each)
```

- **39 route modules** under `api/routes/`
- **60 service modules** under `services/`
- **36 SQLAlchemy ORM models** under `models/`
- **20 Celery task modules** under `workers/`
- **24 Pydantic schema modules** under `schemas/`

---

## Critical: N+1 Query Patterns

### 1. `_resolve_label()` in executions.py

**File:** `fleet_platform/api/routes/executions.py:60-63`

```python
for j in jobs:
    label = await _resolve_label(db, j.target_type, j.target_id)  # 1 query per job
    items.append(_to_response(j, label))
```

A page of 25 execution jobs fires **25 separate queries** to resolve target labels (node hostname or group name), plus the main query and count query = 27 total.

**Fix:** Batch-resolve all target labels in 2 queries:

```python
# Collect all target IDs by type
node_ids = [j.target_id for j in jobs if j.target_type == "node"]
group_ids = [j.target_id for j in jobs if j.target_type == "group"]

# 2 batch queries instead of N
node_map = {}
if node_ids:
    rows = await db.execute(select(Node.id, Node.hostname, Node.minion_id).where(Node.id.in_(node_ids)))
    node_map = {r.id: r.hostname or r.minion_id for r in rows}

group_map = {}
if group_ids:
    rows = await db.execute(select(Group.id, Group.name).where(Group.id.in_(group_ids)))
    group_map = {r.id: r.name for r in rows}

# Resolve labels from maps
for j in jobs:
    if j.target_type == "node":
        label = node_map.get(j.target_id, str(j.target_id))
    else:
        label = group_map.get(j.target_id, str(j.target_id))
    items.append(_to_response(j, label))
```

**Impact:** 25 queries → 2 queries per page. ~92% reduction for this endpoint.

---

### 2. `nodes_using_credential()` in credential_resolver.py

**File:** `fleet_platform/services/credential_resolver.py:331-343`

```python
for n in candidates:
    for _cred, _gname in (await db.execute(_credential_group_stmt(n.id))).all():  # 1 query per node
```

For each candidate node, a separate query resolves which credential it actually uses. 50 candidate nodes = 50 queries on top of the initial candidate query.

**Fix:** Pre-fetch all credential-group mappings for candidate node IDs in a single query, then resolve in-memory:

```python
candidate_ids = [n.id for n in candidates]
cred_map = await db.execute(
    select(GroupMember.node_id, GroupMember.group_id, CredentialGroup.credential_id)
    .join(CredentialGroup, CredentialGroup.group_id == GroupMember.group_id)
    .where(GroupMember.node_id.in_(candidate_ids))
)
# Build dict: node_id -> [(cred_id, group_name), ...]
# Then resolve per-node from the dict
```

**Impact:** O(N) queries → 2 queries (one for candidates, one for credential mappings).

---

### 3. Fleet overview double-scan

**File:** `fleet_platform/api/routes/fleet.py:94-127`

Two full table scans of `nodes`:

1. Lines 94-108: Aggregation query with `func.count()`, `func.sum(case(...))` for status and drift distribution.
2. Lines 116: `select(Node.status, Node.ssh_state, Node.maintenance_mode)` to re-scan every node for health counts.

The code comment at line 112-115 acknowledges this but the optimisation was not applied.

**Fix:** Fold health CASE expressions into the first aggregation query:

```python
stmt = select(
    func.count(Node.id).label("total"),
    func.sum(case((Node.status == "online", 1), else_=0)).label("online_count"),
    # ... existing status/drift aggregates ...
    # Add health CASE expressions here:
    func.sum(case((and_(Node.status == "online", Node.ssh_state == "ok", ~Node.maintenance_mode), 1), else_=0)).label("healthy"),
    func.sum(case((and_(Node.status == "online", Node.ssh_state != "ok"), 1), else_=0)).label("degraded"),
    func.sum(case((Node.status.in_(["offline", "unreachable"]), 1), else_=0)).label("down"),
)
```

**Impact:** 2 full table scans → 1. ~50% reduction in I/O for the fleet overview endpoint.

---

## High Priority: Duplicated Code

### 4. Async/sync credential resolution duplication

**File:** `fleet_platform/services/credential_resolver.py:169-234`

Two nearly identical implementations:

- `resolve_node_credentials()` (lines 169-200) — async, for FastAPI
- `resolve_node_credentials_sync()` (lines 203-234) — sync, for Celery workers

The same 3-tier priority chain (group credential → controller key → none) is duplicated line-for-line. Similarly, `_get_global_setting()` (lines 280-295) and `_get_global_setting_sync()` (lines 267-277) are duplicated.

**Fix:** Extract the resolution logic into a pure data function that takes pre-fetched rows, then wrap in thin async/sync shells:

```python
def _resolve_credentials_from_rows(
    node_id: str,
    group_creds: list,  # pre-fetched group credential rows
    controller_key: str | None,
    node_secrets: dict,
) -> dict:
    """Pure function — no DB access, no async."""
    # 3-tier priority chain (single implementation)
    ...

async def resolve_node_credentials(db, node_id, ...):
    group_creds = await db.execute(...)
    return _resolve_credentials_from_rows(node_id, group_creds.all(), ...)

def resolve_node_credentials_sync(db, node_id, ...):
    group_creds = db.execute(...)
    return _resolve_credentials_from_rows(node_id, group_creds.all(), ...)
```

**Impact:** ~120 lines of duplicated logic → 1 implementation + 2 thin wrappers. Eliminates maintenance hazard of keeping two copies in sync.

---

### 5. No shared CRUD helpers

**Affects:** All 39 route files under `api/routes/`

Every route independently implements:

**Pattern A: Fetch-or-404** — appears in `nodes.py` (6x), `groups.py` (1x, extracted), `credentials.py` (2x), `executions.py` (1x), and others:
```python
result = await db.execute(select(Model).where(Model.id == some_id))
obj = result.scalar_one_or_none()
if not obj:
    raise HTTPException(status_code=404, detail="... not found")
```

**Pattern B: Flush-commit-refresh with IntegrityError** — appears in `nodes.py` (2x), `credentials.py` (2x), `groups.py` (2x):
```python
db.add(obj)
try:
    await db.flush()
    await audit(db, ...)
    await db.commit()
    await db.refresh(obj)
except IntegrityError:
    await db.rollback()
    raise HTTPException(status_code=409, detail="...")
```

**Fix:** Create `fleet_platform/api/helpers.py`:

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

async def get_or_404(db: AsyncSession, model, id: str, detail: str | None = None):
    result = await db.execute(select(model).where(model.id == id))
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(
            status_code=404,
            detail=detail or f"{model.__name__} {id} not found"
        )
    return obj

async def create_with_audit(db, obj, claims, action, *, extra: dict | None = None):
    db.add(obj)
    try:
        await db.flush()
        await audit(db, claims, action, obj, extra=extra)
        await db.commit()
        await db.refresh(obj)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Resource already exists")
    return obj
```

**Impact:** ~15-20 lines saved per CRUD endpoint. Across 40+ route files with multiple endpoints each, this removes ~500-700 lines of duplicated boilerplate.

---

### 6. `_get_default_master()` double-query

**File:** `fleet_platform/workers/salt_tasks.py:33-54`

```python
row = db.execute(select(SaltMaster).where(SaltMaster.is_default.is_(True)).where(SaltMaster.enabled.is_(True)).limit(1)).scalar_one_or_none()
if row is not None:
    return _extract_master_creds(row)
row = db.execute(select(SaltMaster).where(SaltMaster.enabled.is_(True)).limit(1)).scalar_one_or_none()
```

Two sequential queries when a single query with `OR` / priority ordering suffices.

**Fix:**

```python
from sqlalchemy import case

stmt = (
    select(SaltMaster)
    .where(SaltMaster.enabled.is_(True))
    .order_by(case((SaltMaster.is_default.is_(True), 0), else_=1))
    .limit(1)
)
row = db.execute(stmt).scalar_one_or_none()
```

**Impact:** 2 queries → 1. Minor but removes a pattern that repeats across worker files.

---

### 7. Embedding task `asyncio.run()` pattern x3

**File:** `fleet_platform/workers/embedding_tasks.py:41,119,165`

Three separate tasks each define `async def _run()` and call `return asyncio.run(_run())`, importing `asyncio` and `AsyncSessionLocal` independently.

**Fix:** Extract a shared helper:

```python
import asyncio
from fleet_platform.db.session import AsyncSessionLocal

def run_async_task(coro_factory):
    """Run an async coroutine from a sync Celery task."""
    async def wrapper():
        async with AsyncSessionLocal() as db:
            return await coro_factory(db)
    return asyncio.run(wrapper())
```

Then each task becomes:

```python
@celery_app.task(name="embedding.reindex_nodes")
def reindex_nodes():
    return run_async_task(_reindex_nodes_impl)

async def _reindex_nodes_impl(db):
    # actual logic
    ...
```

**Impact:** Removes ~30 lines of duplicated boilerplate across 3 tasks.

---

## Medium Priority

### 8. Re-read after commit

**File:** `fleet_platform/api/routes/nodes.py:182-183, 676-677`

```python
result2 = await db.execute(select(Node).options(selectinload(Node.tags)).where(Node.id == node_id))
node = result2.scalar_one()
```

Full re-query of Node+tags after `db.commit()` when `expire_on_commit=False` is already set on the session.

**Fix:** Use `await db.refresh(node, ["tags"])` instead of a full re-query, or rely on the already-loaded state from `expire_on_commit=False`.

---

### 9. Inline Pydantic models in route files

**Files:**
- `fleet_platform/api/routes/groups.py:311-317` — `GroupCredentialsUpdate`
- `fleet_platform/api/routes/nodes.py:379-383` — `MaintenanceModeRequest`
- `fleet_platform/api/routes/nodes.py:647-648` — `SshTestResponse`

Request/response models defined inline in route files instead of `schemas/`.

**Fix:** Move to the corresponding schema module (`schemas/group.py`, `schemas/node.py`).

---

### 10. Inline model imports inside functions

**Files:**
- `fleet_platform/api/routes/fleet.py:278,291,338` — `GroupMember` imported 3 times in one function
- `fleet_platform/api/routes/nodes.py:246,288,313,359,449-450` — multiple inline imports
- `fleet_platform/api/routes/baselines.py:36,56,81` — same model imported 3 times

These lazy imports are likely to avoid circular imports, but the same model is imported inside a function body multiple times in the same function.

**Fix:** Consolidate to a single lazy import at the top of the function, or resolve the circular import that necessitates the lazy pattern.

---

## Low Priority

### 11. Missing `TimestampMixin` on some models

**File:** `fleet_platform/models/credential.py:23`

`Credential` has `created_at` but no `updated_at`. No way to track when a credential was last modified. Same for `AlertRule`, `WebhookConfig`.

**Fix:** Apply `TimestampMixin` to all models that track creation time.

---

### 12. Worker session fragmentation

**File:** `fleet_platform/workers/ansible_tasks.py` — 18 separate `get_sync_db()` calls

Many Celery tasks open and close multiple sessions within a single task invocation, with intermediate Salt/SSH calls between them. Each session open/close acquires and releases a connection pool slot.

This is deliberate for long-running tasks (to avoid holding connections during SSH calls), but the pattern is scattered rather than managed via a task-level context manager.

**Fix:** Consider a task-scoped session factory that yields sessions on demand without closing the connection pool slot:

```python
@celery_app.task
def long_running_task(node_id):
    with sync_db_session() as db:  # single pool slot for the entire task
        creds = resolve_creds(db, node_id)
        # ... SSH work (no DB needed) ...
        update_status(db, node_id, "done")
```

---

## Summary: Impact Matrix

| # | Issue | Location | Queries Saved | Lines Saved | Priority |
|---|-------|----------|---------------|-------------|----------|
| 1 | N+1 `_resolve_label()` | `executions.py:60-63` | 25 → 2 per page | — | Critical |
| 2 | N+1 `nodes_using_credential()` | `credential_resolver.py:331-343` | N → 2 | — | Critical |
| 3 | Fleet overview double-scan | `fleet.py:94-127` | 2 → 1 full scans | — | Critical |
| 4 | Async/sync credential duplication | `credential_resolver.py:169-234` | — | ~120 | High |
| 5 | No shared CRUD helpers | All 39 route files | — | ~500-700 | High |
| 6 | `_get_default_master()` double-query | `salt_tasks.py:33-54` | 2 → 1 | — | High |
| 7 | Embedding `asyncio.run()` x3 | `embedding_tasks.py:41,119,165` | — | ~30 | Medium |
| 8 | Re-read after commit | `nodes.py:182,676` | 1 → 0 | — | Medium |
| 9 | Inline Pydantic models | `groups.py`, `nodes.py` | — | ~20 | Low |
| 10 | Inline model imports | `fleet.py`, `nodes.py`, `baselines.py` | — | ~15 | Low |
| 11 | Missing `TimestampMixin` | `credential.py`, `alert_rule.py` | — | — | Low |
| 12 | Worker session fragmentation | `ansible_tasks.py` | — | — | Low |

---

## Implementation Order

**Phase 1 — N+1 fixes (highest ROI, zero behaviour change):**
1. Batch-resolve labels in `executions.py`
2. Batch-resolve credential mappings in `credential_resolver.py`
3. Fold health aggregates into fleet overview query

**Phase 2 — Shared helpers (structural, wide impact):**
4. Create `api/helpers.py` with `get_or_404`, `create_with_audit`, `update_with_audit`
5. Extract credential resolution into pure data function
6. Extract `run_async_task()` for Celery workers
7. Consolidate `_get_default_master()` to single query

**Phase 3 — Cleanup (consistency, maintainability):**
8. Move inline Pydantic models to `schemas/`
9. Consolidate inline model imports
10. Add `TimestampMixin` to remaining models
11. Evaluate task-scoped session pattern for long-running workers
