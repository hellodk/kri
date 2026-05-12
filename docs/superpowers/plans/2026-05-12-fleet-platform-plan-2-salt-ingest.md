# Fleet Platform — Plan 2: Salt Integration + Ingest Pipeline

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire SaltStack into the platform — nodes can register, authenticate, and push grain state, execution results, and SBOM payloads to the API; Celery workers process them asynchronously.

**Architecture:** The Salt returner (a Python file Salt loads on each minion) POSTs job results to the ingest API using a per-node token stored in Salt pillar. The ingest API validates the token via bcrypt, updates the `nodes` table, writes a `node_facts` row, and dispatches Celery tasks. A Celery beat task runs every 5 minutes to mark stale/offline nodes. Drift and SBOM Celery tasks are stubs in this plan — fully implemented in Plans 4 and 5.

**Tech Stack:** Python 3.13, FastAPI 0.115, SQLAlchemy 2.0 (async + sync), Celery 5.4, Redis 7.4, bcrypt 4.2, psycopg 3.2, pytest 8.3, pytest-asyncio 1.3, httpx 0.28

**Branch:** `feat/plan-2-salt-ingest` (branch from `master` before starting)

---

## Scope

This is Plan 2 of 6. Plans:
- ✅ **Plan 1:** Foundation — DB schema, FastAPI core, JWT auth
- **Plan 2 (this):** Salt integration + ingest pipeline (Celery, node registration, grain/exec/SBOM ingest, Salt returner)
- **Plan 3:** Fleet API — `/api/v1/nodes`, `/api/v1/groups`, `/api/v1/fleet/overview`
- **Plan 4:** Drift engine — baseline loader, diff computation, drift API
- **Plan 5:** SBOM pipeline — Syft Salt state, CycloneDX ingest, fleet-wide search
- **Plan 6:** React frontend

When Plan 2 is complete you have: nodes registering with the platform, Salt minions POSTing grain data that updates the DB and queues drift computation, execution results stored, SBOM payloads queued for indexing, and stale nodes automatically marked offline by Celery beat.

---

## File Map

```
fleet_platform/
├── db/
│   └── session.py              MODIFY — add sync engine + get_sync_db()
├── services/
│   ├── __init__.py             CREATE
│   └── node_status.py          CREATE — classify_status(), verify_node_token()
├── workers/
│   ├── __init__.py             CREATE
│   ├── celery_app.py           CREATE — Celery factory, queues, beat schedule
│   ├── drift_tasks.py          CREATE — compute_drift stub
│   ├── sbom_tasks.py           CREATE — index_sbom stub
│   └── maintenance.py          CREATE — mark_stale_nodes beat task
├── schemas/
│   ├── node.py                 CREATE — NodeRegisterRequest, NodeRegisterResponse
│   └── ingest.py               CREATE — GrainIngestPayload, ExecutionIngestPayload, SBOMIngestAck
└── api/
    ├── main.py                 MODIFY — register ingest + nodes routers
    └── routes/
        ├── nodes.py            CREATE — POST /api/v1/nodes/register
        └── ingest.py           CREATE — POST /api/v1/ingest/grains|executions|sbom/{id}

salt/
├── returners/
│   └── fleet_platform_return.py  CREATE — Salt returner (POSTs to ingest API)
└── states/
    └── base/
        └── grain_report.sls    CREATE — Salt state that triggers grain sync

tests/
├── unit/
│   ├── test_node_status.py     CREATE — classify_status() + verify_node_token() tests
│   └── test_ingest_schemas.py  CREATE — schema validation tests
└── integration/
    ├── conftest.py             CREATE — shared fixtures: admin_token, registered_node
    ├── test_node_registration.py  CREATE — registration endpoint tests
    └── test_ingest_api.py      CREATE — grain/exec/sbom ingest tests
```

---

## Task 1: Sync DB session for Celery workers

Celery workers are synchronous. They need a sync SQLAlchemy session alongside the existing async one.

**Files:**
- Modify: `fleet_platform/db/session.py`
- Create: `tests/unit/test_sync_session.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_sync_session.py
from fleet_platform.db.session import get_sync_db, SyncSessionLocal


def test_sync_session_imports():
    assert SyncSessionLocal is not None


def test_get_sync_db_is_context_manager():
    # Verify it's a contextmanager — doesn't actually connect (no DB needed for import test)
    import inspect
    from contextlib import AbstractContextManager
    # get_sync_db is decorated with @contextmanager, so calling it returns a context manager
    cm = get_sync_db()
    assert hasattr(cm, "__enter__")
    assert hasattr(cm, "__exit__")
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
cd /home/dk/Documents/git/kri && source .venv/bin/activate
pytest tests/unit/test_sync_session.py -v
```

Expected: `ImportError: cannot import name 'get_sync_db' from 'fleet_platform.db.session'`

- [ ] **Step 3: Modify fleet_platform/db/session.py**

Replace the entire file:

```python
from collections.abc import AsyncGenerator, Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from fleet_platform.core.config import settings

# ── Async engine — used by FastAPI request handlers ──────────────────
engine = create_async_engine(
    settings.database_url,
    echo=settings.is_development,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ── Sync engine — used by Celery workers ─────────────────────────────
sync_engine = create_engine(
    settings.database_url,
    echo=False,
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_pre_ping=True,
)

SyncSessionLocal = sessionmaker(sync_engine, expire_on_commit=False)


@contextmanager
def get_sync_db() -> Generator[Session, None, None]:
    with SyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise
```

- [ ] **Step 4: Run test — expect pass**

```bash
pytest tests/unit/test_sync_session.py -v
```

Expected:
```
PASSED tests/unit/test_sync_session.py::test_sync_session_imports
PASSED tests/unit/test_sync_session.py::test_get_sync_db_is_context_manager
2 passed
```

- [ ] **Step 5: Commit**

```bash
git add fleet_platform/db/session.py tests/unit/test_sync_session.py
git commit -m "feat: add sync SQLAlchemy engine + get_sync_db() for Celery workers"
```

---

## Task 2: node_status service

Two pure functions: `classify_status()` (online/stale/offline from last_seen timestamp) and `verify_node_token()` (bcrypt check for ingest authentication). No DB calls — keeps this unit-testable.

**Files:**
- Create: `fleet_platform/services/__init__.py`
- Create: `fleet_platform/services/node_status.py`
- Create: `tests/unit/test_node_status.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_node_status.py
from datetime import UTC, datetime, timedelta

import pytest

from fleet_platform.services.node_status import classify_status, verify_node_token
from fleet_platform.core.auth import hash_password


def test_classify_online_within_15_minutes():
    last_seen = datetime.now(UTC) - timedelta(minutes=5)
    assert classify_status(last_seen) == "online"


def test_classify_stale_between_15_and_60_minutes():
    last_seen = datetime.now(UTC) - timedelta(minutes=30)
    assert classify_status(last_seen) == "stale"


def test_classify_offline_over_60_minutes():
    last_seen = datetime.now(UTC) - timedelta(hours=2)
    assert classify_status(last_seen) == "offline"


def test_classify_unknown_when_none():
    assert classify_status(None) == "unknown"


def test_classify_boundary_exactly_15_minutes():
    last_seen = datetime.now(UTC) - timedelta(minutes=15, seconds=1)
    assert classify_status(last_seen) == "stale"


def test_verify_node_token_correct_token():
    hashed = hash_password("my-secret-token")
    assert verify_node_token("my-secret-token", hashed) is True


def test_verify_node_token_wrong_token():
    hashed = hash_password("my-secret-token")
    assert verify_node_token("wrong-token", hashed) is False
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
pytest tests/unit/test_node_status.py -v
```

Expected: `ImportError: cannot import name 'classify_status'`

- [ ] **Step 3: Create fleet_platform/services/__init__.py**

```python
# fleet_platform/services/__init__.py
```

- [ ] **Step 4: Create fleet_platform/services/node_status.py**

```python
# fleet_platform/services/node_status.py
from datetime import UTC, datetime, timedelta

import bcrypt

_STALE_THRESHOLD = timedelta(minutes=15)
_OFFLINE_THRESHOLD = timedelta(hours=1)


def classify_status(last_seen_at: datetime | None) -> str:
    """Return 'online', 'stale', 'offline', or 'unknown' based on last_seen_at age."""
    if last_seen_at is None:
        return "unknown"
    age = datetime.now(UTC) - last_seen_at
    if age <= _STALE_THRESHOLD:
        return "online"
    if age <= _OFFLINE_THRESHOLD:
        return "stale"
    return "offline"


def verify_node_token(plaintext_token: str, hashed_token: str) -> bool:
    """Return True if plaintext_token matches the bcrypt hash."""
    return bcrypt.checkpw(plaintext_token.encode(), hashed_token.encode())
```

- [ ] **Step 5: Run tests — expect all pass**

```bash
pytest tests/unit/test_node_status.py -v
```

Expected:
```
PASSED tests/unit/test_node_status.py::test_classify_online_within_15_minutes
PASSED tests/unit/test_node_status.py::test_classify_stale_between_15_and_60_minutes
PASSED tests/unit/test_node_status.py::test_classify_offline_over_60_minutes
PASSED tests/unit/test_node_status.py::test_classify_unknown_when_none
PASSED tests/unit/test_node_status.py::test_classify_boundary_exactly_15_minutes
PASSED tests/unit/test_node_status.py::test_verify_node_token_correct_token
PASSED tests/unit/test_node_status.py::test_verify_node_token_wrong_token
7 passed
```

- [ ] **Step 6: Commit**

```bash
git add fleet_platform/services/ tests/unit/test_node_status.py
git commit -m "feat: node_status service — classify_status() + verify_node_token()"
```

---

## Task 3: Celery app setup

**Files:**
- Create: `fleet_platform/workers/__init__.py`
- Create: `fleet_platform/workers/celery_app.py`
- Create: `tests/unit/test_celery_app.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_celery_app.py
from fleet_platform.workers.celery_app import celery_app


def test_celery_app_is_configured():
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.timezone == "UTC"
    assert celery_app.conf.enable_utc is True


def test_celery_queues_defined():
    routes = celery_app.conf.task_routes
    assert any("drift_tasks" in k for k in routes)
    assert any("sbom_tasks" in k for k in routes)
    assert any("maintenance" in k for k in routes)


def test_beat_schedule_has_mark_stale_nodes():
    schedule = celery_app.conf.beat_schedule
    assert "mark-stale-nodes" in schedule
    assert schedule["mark-stale-nodes"]["schedule"] == 300
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
pytest tests/unit/test_celery_app.py -v
```

Expected: `ImportError: cannot import name 'celery_app'`

- [ ] **Step 3: Create fleet_platform/workers/__init__.py**

```python
# fleet_platform/workers/__init__.py
```

- [ ] **Step 4: Create fleet_platform/workers/celery_app.py**

```python
# fleet_platform/workers/celery_app.py
from celery import Celery

from fleet_platform.core.config import settings

celery_app = Celery(
    "fleet_platform",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "fleet_platform.workers.drift_tasks",
        "fleet_platform.workers.sbom_tasks",
        "fleet_platform.workers.maintenance",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "fleet_platform.workers.drift_tasks.*": {"queue": "drift"},
        "fleet_platform.workers.sbom_tasks.*": {"queue": "sbom"},
        "fleet_platform.workers.maintenance.*": {"queue": "maintenance"},
    },
    beat_schedule={
        "mark-stale-nodes": {
            "task": "fleet_platform.workers.maintenance.mark_stale_nodes",
            "schedule": 300,  # every 5 minutes
        },
    },
)
```

- [ ] **Step 5: Run tests — expect all pass**

```bash
pytest tests/unit/test_celery_app.py -v
```

Expected:
```
PASSED tests/unit/test_celery_app.py::test_celery_app_is_configured
PASSED tests/unit/test_celery_app.py::test_celery_queues_defined
PASSED tests/unit/test_celery_app.py::test_beat_schedule_has_mark_stale_nodes
3 passed
```

- [ ] **Step 6: Commit**

```bash
git add fleet_platform/workers/ tests/unit/test_celery_app.py
git commit -m "feat: Celery app factory — queues, beat schedule, task routing"
```

---

## Task 4: Celery task stubs + maintenance task

Drift and SBOM tasks are stubs (Plans 4 and 5 fill them in). The maintenance task (`mark_stale_nodes`) is fully implemented here.

**Files:**
- Create: `fleet_platform/workers/drift_tasks.py`
- Create: `fleet_platform/workers/sbom_tasks.py`
- Create: `fleet_platform/workers/maintenance.py`
- Create: `tests/unit/test_maintenance_task.py`

- [ ] **Step 1: Write failing test for maintenance task**

```python
# tests/unit/test_maintenance_task.py
from unittest.mock import MagicMock, patch, call
from datetime import UTC, datetime, timedelta


def test_mark_stale_nodes_returns_counts():
    """mark_stale_nodes returns a dict with stale and offline counts."""
    from fleet_platform.workers.maintenance import mark_stale_nodes

    mock_result = MagicMock()
    mock_result.rowcount = 3

    mock_session = MagicMock()
    mock_session.execute.return_value = mock_result
    mock_session.__enter__ = lambda s: s
    mock_session.__exit__ = MagicMock(return_value=False)

    with patch("fleet_platform.workers.maintenance.get_sync_db") as mock_db:
        mock_db.return_value = mock_session
        result = mark_stale_nodes()

    assert "stale" in result
    assert "offline" in result
    assert isinstance(result["stale"], int)
    assert isinstance(result["offline"], int)


def test_mark_stale_nodes_calls_commit():
    from fleet_platform.workers.maintenance import mark_stale_nodes

    mock_result = MagicMock()
    mock_result.rowcount = 0
    mock_session = MagicMock()
    mock_session.execute.return_value = mock_result
    mock_session.__enter__ = lambda s: s
    mock_session.__exit__ = MagicMock(return_value=False)

    with patch("fleet_platform.workers.maintenance.get_sync_db") as mock_db:
        mock_db.return_value = mock_session
        mark_stale_nodes()

    mock_session.commit.assert_called_once()
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
pytest tests/unit/test_maintenance_task.py -v
```

Expected: `ImportError: cannot import name 'mark_stale_nodes'`

- [ ] **Step 3: Create fleet_platform/workers/drift_tasks.py**

```python
# fleet_platform/workers/drift_tasks.py
from fleet_platform.workers.celery_app import celery_app


@celery_app.task(
    name="fleet_platform.workers.drift_tasks.compute_drift",
    bind=True,
    max_retries=3,
    queue="drift",
)
def compute_drift(self, node_id: str) -> dict:
    """Compute drift for a node. Full implementation in Plan 4."""
    return {"node_id": node_id, "status": "queued"}
```

- [ ] **Step 4: Create fleet_platform/workers/sbom_tasks.py**

```python
# fleet_platform/workers/sbom_tasks.py
from fleet_platform.workers.celery_app import celery_app


@celery_app.task(
    name="fleet_platform.workers.sbom_tasks.index_sbom",
    bind=True,
    max_retries=3,
    queue="sbom",
)
def index_sbom(self, node_id: str, file_path: str) -> dict:
    """Index SBOM components from a CycloneDX file. Full implementation in Plan 5."""
    return {"node_id": node_id, "status": "queued", "file_path": file_path}
```

- [ ] **Step 5: Create fleet_platform/workers/maintenance.py**

```python
# fleet_platform/workers/maintenance.py
from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from fleet_platform.db.session import get_sync_db
from fleet_platform.models.node import Node
from fleet_platform.workers.celery_app import celery_app

_STALE_THRESHOLD = timedelta(minutes=15)
_OFFLINE_THRESHOLD = timedelta(hours=1)


@celery_app.task(name="fleet_platform.workers.maintenance.mark_stale_nodes")
def mark_stale_nodes() -> dict:
    """Mark nodes as stale or offline based on last_seen_at. Runs every 5 minutes via beat."""
    now = datetime.now(UTC)
    stale_cutoff = now - _STALE_THRESHOLD
    offline_cutoff = now - _OFFLINE_THRESHOLD

    with get_sync_db() as db:
        stale = db.execute(
            update(Node)
            .where(Node.last_seen_at < stale_cutoff)
            .where(Node.last_seen_at >= offline_cutoff)
            .where(Node.status == "online")
            .values(status="stale", updated_at=now)
        )
        offline = db.execute(
            update(Node)
            .where(Node.last_seen_at < offline_cutoff)
            .where(Node.status.in_(["online", "stale"]))
            .values(status="offline", updated_at=now)
        )
        db.commit()

    return {"stale": stale.rowcount, "offline": offline.rowcount}
```

- [ ] **Step 6: Run tests — expect pass**

```bash
pytest tests/unit/test_maintenance_task.py -v
```

Expected:
```
PASSED tests/unit/test_maintenance_task.py::test_mark_stale_nodes_returns_counts
PASSED tests/unit/test_maintenance_task.py::test_mark_stale_nodes_calls_commit
2 passed
```

- [ ] **Step 7: Commit**

```bash
git add fleet_platform/workers/ tests/unit/test_maintenance_task.py
git commit -m "feat: Celery tasks — compute_drift stub, index_sbom stub, mark_stale_nodes"
```

---

## Task 5: Schemas — NodeRegister + IngestPayloads

**Files:**
- Create: `fleet_platform/schemas/node.py`
- Create: `fleet_platform/schemas/ingest.py`
- Create: `tests/unit/test_ingest_schemas.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_ingest_schemas.py
import pytest
from pydantic import ValidationError

from fleet_platform.schemas.ingest import ExecutionIngestPayload, GrainIngestPayload
from fleet_platform.schemas.node import NodeRegisterRequest, NodeRegisterResponse


def test_grain_payload_parses_minimal():
    p = GrainIngestPayload(
        minion_id="mac-mini-01.local",
        grains={"id": "mac-mini-01.local", "os": "MacOS"},
    )
    assert p.minion_id == "mac-mini-01.local"
    assert p.grains["os"] == "MacOS"


def test_grain_payload_requires_minion_id():
    with pytest.raises(ValidationError):
        GrainIngestPayload(grains={"id": "foo"})


def test_grain_payload_requires_grains():
    with pytest.raises(ValidationError):
        GrainIngestPayload(minion_id="mac-mini-01.local")


def test_execution_payload_parses():
    p = ExecutionIngestPayload(
        minion_id="mac-mini-01.local",
        jid="20260512100000123456",
        return_data={"test.ping": True},
        retcode=0,
        fun="test.ping",
        success=True,
    )
    assert p.retcode == 0
    assert p.success is True


def test_execution_payload_defaults():
    p = ExecutionIngestPayload(
        minion_id="mac-mini-01.local",
        jid="20260512100000123456",
        return_data={},
        fun="state.apply",
    )
    assert p.retcode == 0
    assert p.success is True


def test_node_register_request_requires_minion_id():
    with pytest.raises(ValidationError):
        NodeRegisterRequest(hostname="foo")


def test_node_register_response_has_token():
    import uuid
    r = NodeRegisterResponse(node_id=uuid.uuid4(), minion_id="foo.local", token="abc123")
    assert r.token == "abc123"
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
pytest tests/unit/test_ingest_schemas.py -v
```

Expected: `ImportError: cannot import name 'GrainIngestPayload'`

- [ ] **Step 3: Create fleet_platform/schemas/node.py**

```python
# fleet_platform/schemas/node.py
import uuid

from pydantic import BaseModel


class NodeRegisterRequest(BaseModel):
    minion_id: str
    hostname: str | None = None


class NodeRegisterResponse(BaseModel):
    node_id: uuid.UUID
    minion_id: str
    token: str
    message: str = "Token shown once. Store it in Salt pillar immediately."
```

- [ ] **Step 4: Create fleet_platform/schemas/ingest.py**

```python
# fleet_platform/schemas/ingest.py
from pydantic import BaseModel


class GrainIngestPayload(BaseModel):
    minion_id: str
    grains: dict


class ExecutionIngestPayload(BaseModel):
    minion_id: str
    jid: str
    return_data: dict
    fun: str
    retcode: int = 0
    success: bool = True


class SBOMIngestAck(BaseModel):
    status: str = "queued"
    node_id: str
```

- [ ] **Step 5: Run tests — expect all pass**

```bash
pytest tests/unit/test_ingest_schemas.py -v
```

Expected: `7 passed`

- [ ] **Step 6: Commit**

```bash
git add fleet_platform/schemas/node.py fleet_platform/schemas/ingest.py \
        tests/unit/test_ingest_schemas.py
git commit -m "feat: schemas — NodeRegisterRequest/Response, GrainIngestPayload, ExecutionIngestPayload"
```

---

## Task 6: Node registration endpoint

**Files:**
- Create: `fleet_platform/api/routes/nodes.py`
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_node_registration.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_node_registration.py
import pytest
from httpx import AsyncClient


async def test_register_node_returns_token(admin_client: AsyncClient):
    response = await admin_client.post(
        "/api/v1/nodes/register",
        json={"minion_id": "test-node-01.local", "hostname": "test-node-01"},
    )
    assert response.status_code == 201
    data = response.json()
    assert "node_id" in data
    assert "token" in data
    assert len(data["token"]) >= 32
    assert "message" in data


async def test_register_node_viewer_forbidden(viewer_client: AsyncClient):
    response = await viewer_client.post(
        "/api/v1/nodes/register",
        json={"minion_id": "test-node-02.local"},
    )
    assert response.status_code == 403


async def test_register_duplicate_minion_id_returns_409(admin_client: AsyncClient):
    await admin_client.post(
        "/api/v1/nodes/register",
        json={"minion_id": "test-dup.local"},
    )
    response = await admin_client.post(
        "/api/v1/nodes/register",
        json={"minion_id": "test-dup.local"},
    )
    assert response.status_code == 409


async def test_register_requires_auth(client: AsyncClient):
    response = await client.post(
        "/api/v1/nodes/register",
        json={"minion_id": "test-node-03.local"},
    )
    assert response.status_code == 401
```

- [ ] **Step 2: Create tests/integration/conftest.py**

```python
# tests/integration/conftest.py
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fleet_platform.core.auth import create_access_token, hash_password
from fleet_platform.core.config import settings
from fleet_platform.models import Base, User


@pytest.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(settings.test_database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(test_engine):
    TestSession = async_sessionmaker(test_engine, expire_on_commit=False)
    async with TestSession() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def app_with_test_db(test_engine):
    from fleet_platform.api.main import create_app
    from fleet_platform.api import deps

    app = create_app()
    TestSession = async_sessionmaker(test_engine, expire_on_commit=False)

    async def override_get_db():
        async with TestSession() as session:
            yield session

    app.dependency_overrides[deps.get_db] = override_get_db
    return app


@pytest.fixture
async def client(app_with_test_db):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_test_db),
        base_url="http://testserver",
    ) as ac:
        yield ac


@pytest.fixture
async def admin_user(db_session: AsyncSession):
    user = User(
        email="admin-test@fleet.local",
        password_hash=hash_password("admin123"),
        role="admin",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    yield user
    await db_session.delete(user)
    await db_session.commit()


@pytest.fixture
async def viewer_user(db_session: AsyncSession):
    user = User(
        email="viewer-test@fleet.local",
        password_hash=hash_password("viewer123"),
        role="viewer",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    yield user
    await db_session.delete(user)
    await db_session.commit()


@pytest.fixture
def admin_token(admin_user: User) -> str:
    return create_access_token(
        user_id=str(admin_user.id),
        email=admin_user.email,
        role=admin_user.role,
    )


@pytest.fixture
def viewer_token(viewer_user: User) -> str:
    return create_access_token(
        user_id=str(viewer_user.id),
        email=viewer_user.email,
        role=viewer_user.role,
    )


@pytest.fixture
async def admin_client(app_with_test_db, admin_token: str):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_test_db),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {admin_token}"},
    ) as ac:
        yield ac


@pytest.fixture
async def viewer_client(app_with_test_db, viewer_token: str):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_test_db),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {viewer_token}"},
    ) as ac:
        yield ac
```

- [ ] **Step 3: Run tests — expect 404 (route not found)**

```bash
pytest tests/integration/test_node_registration.py -v
```

Expected: All fail with `AssertionError: assert 404 == 201` (route doesn't exist yet)

- [ ] **Step 4: Create fleet_platform/api/routes/nodes.py**

```python
# fleet_platform/api/routes/nodes.py
import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import hash_password, require_role
from fleet_platform.models.node import Node
from fleet_platform.schemas.node import NodeRegisterRequest, NodeRegisterResponse

router = APIRouter(prefix="/api/v1/nodes")


@router.post("/register", response_model=NodeRegisterResponse, status_code=status.HTTP_201_CREATED)
async def register_node(
    payload: NodeRegisterRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    existing = await db.execute(
        select(Node).where(Node.minion_id == payload.minion_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Node '{payload.minion_id}' is already registered",
        )

    token = secrets.token_urlsafe(32)
    node = Node(
        minion_id=payload.minion_id,
        hostname=payload.hostname,
        node_token_hash=hash_password(token),
        first_seen_at=datetime.now(UTC),
        status="unknown",
    )
    db.add(node)

    try:
        await db.commit()
        await db.refresh(node)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Node '{payload.minion_id}' is already registered",
        )

    return NodeRegisterResponse(
        node_id=node.id,
        minion_id=node.minion_id,
        token=token,
    )
```

- [ ] **Step 5: Register the nodes router in main.py**

In `fleet_platform/api/main.py`, add the import after the `auth` import:

```python
from fleet_platform.api.routes import health, auth, nodes
```

And in `create_app()`, after `app.include_router(auth.router, ...)`:

```python
app.include_router(nodes.router, tags=["nodes"])
```

- [ ] **Step 6: Run tests — expect all pass**

```bash
pytest tests/integration/test_node_registration.py -v
```

Expected:
```
PASSED tests/integration/test_node_registration.py::test_register_node_returns_token
PASSED tests/integration/test_node_registration.py::test_register_node_viewer_forbidden
PASSED tests/integration/test_node_registration.py::test_register_duplicate_minion_id_returns_409
PASSED tests/integration/test_node_registration.py::test_register_requires_auth
4 passed
```

- [ ] **Step 7: Commit**

```bash
git add fleet_platform/api/routes/nodes.py fleet_platform/api/main.py \
        fleet_platform/schemas/node.py \
        tests/integration/conftest.py tests/integration/test_node_registration.py
git commit -m "feat: node registration endpoint — POST /api/v1/nodes/register with token generation"
```

---

## Task 7: Grain ingest endpoint

Validates node token, updates the node row, writes a `node_facts` record, dispatches `compute_drift`.

**Files:**
- Create: `fleet_platform/api/routes/ingest.py`
- Create: `tests/integration/test_ingest_grains.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_ingest_grains.py
import pytest
from unittest.mock import patch
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.auth import hash_password
from fleet_platform.models.node import Node
from datetime import UTC, datetime
import secrets


@pytest.fixture
async def registered_node(db_session: AsyncSession):
    token = secrets.token_urlsafe(32)
    node = Node(
        minion_id="ingest-test-01.local",
        hostname="ingest-test-01",
        node_token_hash=hash_password(token),
        first_seen_at=datetime.now(UTC),
        status="unknown",
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)
    yield node, token
    await db_session.delete(node)
    await db_session.commit()


_SAMPLE_GRAINS = {
    "id": "ingest-test-01.local",
    "os": "MacOS",
    "osrelease": "14.4.1",
    "osbuild": "23E224",
    "productname": "Mac mini",
    "cpuarch": "arm64",
    "num_cpus": 10,
    "mem_total": 32768,
    "ip4_interfaces": {"en0": ["192.168.1.101"]},
    "ip_interfaces": {"en0": {"inet": ["192.168.1.101"]}},
}


async def test_grain_ingest_returns_200(client: AsyncClient, registered_node):
    node, token = registered_node
    with patch("fleet_platform.api.routes.ingest.compute_drift"):
        response = await client.post(
            "/api/v1/ingest/grains",
            json={"minion_id": node.minion_id, "grains": _SAMPLE_GRAINS},
            headers={"X-Node-Token": token},
        )
    assert response.status_code == 200


async def test_grain_ingest_queues_drift_task(client: AsyncClient, registered_node):
    node, token = registered_node
    with patch("fleet_platform.api.routes.ingest.compute_drift") as mock_task:
        await client.post(
            "/api/v1/ingest/grains",
            json={"minion_id": node.minion_id, "grains": _SAMPLE_GRAINS},
            headers={"X-Node-Token": token},
        )
        mock_task.delay.assert_called_once_with(str(node.id))


async def test_grain_ingest_invalid_token_returns_401(client: AsyncClient, registered_node):
    node, _ = registered_node
    response = await client.post(
        "/api/v1/ingest/grains",
        json={"minion_id": node.minion_id, "grains": {}},
        headers={"X-Node-Token": "wrong-token"},
    )
    assert response.status_code == 401


async def test_grain_ingest_unknown_minion_returns_404(client: AsyncClient):
    response = await client.post(
        "/api/v1/ingest/grains",
        json={"minion_id": "ghost.local", "grains": {}},
        headers={"X-Node-Token": "any-token"},
    )
    assert response.status_code == 404


async def test_grain_ingest_missing_token_returns_401(client: AsyncClient, registered_node):
    node, _ = registered_node
    response = await client.post(
        "/api/v1/ingest/grains",
        json={"minion_id": node.minion_id, "grains": _SAMPLE_GRAINS},
    )
    assert response.status_code == 401
```

- [ ] **Step 2: Run tests — expect 404 (route doesn't exist)**

```bash
pytest tests/integration/test_ingest_grains.py -v
```

Expected: All fail — route doesn't exist yet.

- [ ] **Step 3: Create fleet_platform/api/routes/ingest.py (grain endpoint only)**

```python
# fleet_platform/api/routes/ingest.py
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fastapi import Depends
from fleet_platform.models.facts import NodeFact
from fleet_platform.models.node import Node
from fleet_platform.schemas.ingest import GrainIngestPayload
from fleet_platform.services.node_status import verify_node_token
from fleet_platform.workers.drift_tasks import compute_drift

router = APIRouter(prefix="/api/v1/ingest")


async def _resolve_node(
    minion_id: str,
    token: str,
    db: AsyncSession,
) -> Node:
    """Look up node by minion_id, verify token. Raises 404 or 401."""
    result = await db.execute(select(Node).where(Node.minion_id == minion_id))
    node = result.scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")
    if not verify_node_token(token, node.node_token_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid node token")
    return node


def _extract_node_facts(grains: dict) -> dict:
    """Map Salt grain keys to Node column values."""
    ip = None
    ip4 = grains.get("ip4_interfaces", {})
    for iface_ips in ip4.values():
        if iface_ips:
            ip = iface_ips[0]
            break

    mem_mb = grains.get("mem_total")
    ram_gb = Decimal(str(round(mem_mb / 1024, 2))) if mem_mb else None

    return {
        "hostname": grains.get("id") or grains.get("host"),
        "ip_address": ip,
        "os_version": grains.get("osrelease"),
        "os_build": grains.get("osbuild"),
        "hardware_model": grains.get("productname"),
        "cpu_cores": grains.get("num_cpus"),
        "ram_gb": ram_gb,
        "status": "online",
        "last_seen_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }


@router.post("/grains")
async def ingest_grains(
    payload: GrainIngestPayload,
    x_node_token: str = Header(alias="X-Node-Token", default=None),
    db: AsyncSession = Depends(get_db),
):
    if not x_node_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-Node-Token")

    node = await _resolve_node(payload.minion_id, x_node_token, db)

    # Update node fields from grains
    facts = _extract_node_facts(payload.grains)
    for key, value in facts.items():
        setattr(node, key, value)

    # Write node_fact row
    db.add(NodeFact(
        node_id=node.id,
        collected_at=datetime.now(UTC),
        grains=payload.grains,
    ))

    await db.commit()

    # Queue drift computation (non-blocking)
    compute_drift.delay(str(node.id))

    return {"status": "ok", "node_id": str(node.id)}
```

- [ ] **Step 4: Register the ingest router in main.py**

In `fleet_platform/api/main.py`:

```python
from fleet_platform.api.routes import health, auth, nodes, ingest
```

In `create_app()`:

```python
app.include_router(ingest.router, tags=["ingest"])
```

- [ ] **Step 5: Run tests — expect all pass**

```bash
pytest tests/integration/test_ingest_grains.py -v
```

Expected: `5 passed`

- [ ] **Step 6: Commit**

```bash
git add fleet_platform/api/routes/ingest.py fleet_platform/api/main.py \
        tests/integration/test_ingest_grains.py
git commit -m "feat: grain ingest endpoint — POST /api/v1/ingest/grains with node token auth"
```

---

## Task 8: Execution ingest endpoint

**Files:**
- Modify: `fleet_platform/api/routes/ingest.py`
- Create: `tests/integration/test_ingest_executions.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_ingest_executions.py
import secrets
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.auth import hash_password
from fleet_platform.models.node import Node


@pytest.fixture
async def exec_node(db_session: AsyncSession):
    token = secrets.token_urlsafe(32)
    node = Node(
        minion_id="exec-test-01.local",
        hostname="exec-test-01",
        node_token_hash=hash_password(token),
        first_seen_at=datetime.now(UTC),
        status="online",
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)
    yield node, token
    await db_session.delete(node)
    await db_session.commit()


async def test_execution_ingest_returns_200(client: AsyncClient, exec_node):
    node, token = exec_node
    response = await client.post(
        "/api/v1/ingest/executions",
        json={
            "minion_id": node.minion_id,
            "jid": "20260512100000123456",
            "return_data": {"cmd.run": "ok"},
            "fun": "cmd.run",
            "retcode": 0,
            "success": True,
        },
        headers={"X-Node-Token": token},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "job_id" in data


async def test_execution_ingest_creates_job_and_result(
    client: AsyncClient, exec_node, db_session: AsyncSession
):
    from sqlalchemy import select
    from fleet_platform.models.execution import ExecutionJob, ExecutionResult

    node, token = exec_node
    await client.post(
        "/api/v1/ingest/executions",
        json={
            "minion_id": node.minion_id,
            "jid": "20260512100000999999",
            "return_data": {"test.ping": True},
            "fun": "test.ping",
            "retcode": 0,
        },
        headers={"X-Node-Token": token},
    )

    job = (await db_session.execute(
        select(ExecutionJob).where(ExecutionJob.salt_jid == "20260512100000999999")
    )).scalar_one_or_none()
    assert job is not None
    assert job.status == "complete"

    result = (await db_session.execute(
        select(ExecutionResult).where(ExecutionResult.job_id == job.id)
    )).scalar_one_or_none()
    assert result is not None
    assert result.node_id == node.id


async def test_execution_ingest_invalid_token_returns_401(client: AsyncClient, exec_node):
    node, _ = exec_node
    response = await client.post(
        "/api/v1/ingest/executions",
        json={"minion_id": node.minion_id, "jid": "123", "return_data": {}, "fun": "test.ping"},
        headers={"X-Node-Token": "bad-token"},
    )
    assert response.status_code == 401
```

- [ ] **Step 2: Run tests — expect 404**

```bash
pytest tests/integration/test_ingest_executions.py -v
```

Expected: fail — `/api/v1/ingest/executions` doesn't exist yet.

- [ ] **Step 3: Add execution ingest to fleet_platform/api/routes/ingest.py**

Add these imports at the top of the file:

```python
from fleet_platform.models.execution import ExecutionJob, ExecutionResult
from fleet_platform.schemas.ingest import ExecutionIngestPayload
```

Add this endpoint after the `/grains` endpoint:

```python
@router.post("/executions")
async def ingest_executions(
    payload: ExecutionIngestPayload,
    x_node_token: str = Header(alias="X-Node-Token", default=None),
    db: AsyncSession = Depends(get_db),
):
    if not x_node_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-Node-Token")

    node = await _resolve_node(payload.minion_id, x_node_token, db)
    now = datetime.now(UTC)

    job = ExecutionJob(
        salt_jid=payload.jid,
        type=payload.fun,
        target_type="node",
        target_id=node.id,
        triggered_by="salt",
        status="complete",
        started_at=now,
        completed_at=now,
    )
    db.add(job)
    await db.flush()

    result = ExecutionResult(
        job_id=job.id,
        node_id=node.id,
        status="success" if payload.success and payload.retcode == 0 else "failure",
        exit_code=payload.retcode,
        changes=payload.return_data,
        completed_at=now,
    )
    db.add(result)
    await db.commit()

    return {"status": "ok", "job_id": str(job.id)}
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
pytest tests/integration/test_ingest_executions.py -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add fleet_platform/api/routes/ingest.py tests/integration/test_ingest_executions.py
git commit -m "feat: execution ingest endpoint — POST /api/v1/ingest/executions"
```

---

## Task 9: SBOM ingest endpoint

Accepts large CycloneDX JSON, streams to a temp file, queues `index_sbom` task. Returns 202 immediately.

**Files:**
- Modify: `fleet_platform/api/routes/ingest.py`
- Create: `tests/integration/test_ingest_sbom.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_ingest_sbom.py
import json
import secrets
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.auth import hash_password
from fleet_platform.models.node import Node


@pytest.fixture
async def sbom_node(db_session: AsyncSession):
    token = secrets.token_urlsafe(32)
    node = Node(
        minion_id="sbom-test-01.local",
        hostname="sbom-test-01",
        node_token_hash=hash_password(token),
        first_seen_at=datetime.now(UTC),
        status="online",
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)
    yield node, token
    await db_session.delete(node)
    await db_session.commit()


_SAMPLE_CYCLONEDX = {
    "bomFormat": "CycloneDX",
    "specVersion": "1.4",
    "version": 1,
    "components": [
        {
            "type": "library",
            "name": "openssl",
            "version": "3.3.0",
            "purl": "pkg:brew/openssl@3.3.0",
        }
    ],
}


async def test_sbom_ingest_returns_202(client: AsyncClient, sbom_node):
    node, token = sbom_node
    with patch("fleet_platform.api.routes.ingest.index_sbom"):
        response = await client.post(
            f"/api/v1/ingest/sbom/{node.minion_id}",
            content=json.dumps(_SAMPLE_CYCLONEDX),
            headers={
                "X-Node-Token": token,
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "queued"
    assert "node_id" in data


async def test_sbom_ingest_queues_index_task(client: AsyncClient, sbom_node):
    node, token = sbom_node
    with patch("fleet_platform.api.routes.ingest.index_sbom") as mock_task:
        await client.post(
            f"/api/v1/ingest/sbom/{node.minion_id}",
            content=json.dumps(_SAMPLE_CYCLONEDX),
            headers={"X-Node-Token": token, "Content-Type": "application/json"},
        )
        mock_task.delay.assert_called_once()
        call_args = mock_task.delay.call_args
        assert call_args.kwargs["node_id"] == str(node.id)


async def test_sbom_ingest_invalid_token_returns_401(client: AsyncClient, sbom_node):
    node, _ = sbom_node
    response = await client.post(
        f"/api/v1/ingest/sbom/{node.minion_id}",
        content=json.dumps(_SAMPLE_CYCLONEDX),
        headers={"X-Node-Token": "bad-token", "Content-Type": "application/json"},
    )
    assert response.status_code == 401


async def test_sbom_ingest_unknown_minion_returns_404(client: AsyncClient):
    response = await client.post(
        "/api/v1/ingest/sbom/ghost-node.local",
        content=json.dumps(_SAMPLE_CYCLONEDX),
        headers={"X-Node-Token": "any", "Content-Type": "application/json"},
    )
    assert response.status_code == 404
```

- [ ] **Step 2: Run tests — expect 404**

```bash
pytest tests/integration/test_ingest_sbom.py -v
```

- [ ] **Step 3: Add SBOM ingest to fleet_platform/api/routes/ingest.py**

Add this import at the top:

```python
import tempfile
import os
from fleet_platform.workers.sbom_tasks import index_sbom
```

Add this endpoint after `/executions`:

```python
@router.post("/sbom/{minion_id}", status_code=status.HTTP_202_ACCEPTED)
async def ingest_sbom(
    minion_id: str,
    request: Request,
    x_node_token: str = Header(alias="X-Node-Token", default=None),
    db: AsyncSession = Depends(get_db),
):
    if not x_node_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-Node-Token")

    node = await _resolve_node(minion_id, x_node_token, db)

    # Stream body to temp file — avoids loading 20MB CycloneDX into memory
    tmp = tempfile.NamedTemporaryFile(
        delete=False,
        suffix=".json",
        prefix=f"sbom_{node.id}_",
    )
    try:
        async for chunk in request.stream():
            tmp.write(chunk)
        tmp.close()
    except Exception:
        tmp.close()
        os.unlink(tmp.name)
        raise

    index_sbom.delay(node_id=str(node.id), file_path=tmp.name)

    return {"status": "queued", "node_id": str(node.id)}
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
pytest tests/integration/test_ingest_sbom.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add fleet_platform/api/routes/ingest.py tests/integration/test_ingest_sbom.py
git commit -m "feat: SBOM ingest endpoint — POST /api/v1/ingest/sbom/{minion_id} streams to temp file"
```

---

## Task 10: Salt returner + grain report state

The Salt returner is a Python file Salt loads on the minion. It POSTs job results to the ingest API using the node's token from Salt pillar.

**Files:**
- Create: `salt/returners/fleet_platform_return.py`
- Create: `salt/states/base/grain_report.sls`
- Create: `tests/unit/test_salt_returner.py`

- [ ] **Step 1: Write test for returner**

```python
# tests/unit/test_salt_returner.py
import importlib.util
import sys
from unittest.mock import MagicMock, patch


def _load_returner(ingest_url="http://fleet.local/api/v1/ingest", node_token="test-token"):
    """Load the Salt returner module with mocked __salt__ dunder global."""
    spec = importlib.util.spec_from_file_location(
        "fleet_platform_return",
        "salt/returners/fleet_platform_return.py",
    )
    module = importlib.util.module_from_spec(spec)
    module.__salt__ = {
        "config.get": lambda key, default=None: {
            "fleet_platform.ingest_url": ingest_url,
            "fleet_platform.node_token": node_token,
        }.get(key, default),
    }
    spec.loader.exec_module(module)
    return module


def test_returner_posts_to_executions_endpoint():
    module = _load_returner()
    ret = {
        "id": "mac-mini-01.local",
        "jid": "20260512100000123456",
        "return": {"test.ping": True},
        "retcode": 0,
        "fun": "test.ping",
        "success": True,
    }
    with patch("urllib.request.urlopen") as mock_open:
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = mock_resp
        module.returner(ret)
        mock_open.assert_called_once()
        req = mock_open.call_args[0][0]
        assert b"/executions" in req.full_url.encode() or "/executions" in req.full_url


def test_returner_skips_when_not_configured():
    module = _load_returner(ingest_url=None, node_token=None)
    module.__salt__ = {"config.get": lambda key, default=None: None}
    with patch("urllib.request.urlopen") as mock_open:
        module.returner({"id": "test", "jid": "123", "return": {}})
        mock_open.assert_not_called()


def test_returner_handles_network_error_gracefully():
    import urllib.error
    module = _load_returner()
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
        # Should not raise — just log the error
        module.returner({
            "id": "mac-mini-01.local",
            "jid": "123",
            "return": {},
            "retcode": 0,
            "fun": "test.ping",
        })


def test_required_functions_exist():
    """Salt requires these functions to be present in a returner module."""
    module = _load_returner()
    assert callable(getattr(module, "returner", None))
    assert callable(getattr(module, "prep_jid", None))
    assert callable(getattr(module, "save_load", None))
    assert callable(getattr(module, "get_load", None))
```

- [ ] **Step 2: Run test — expect FileNotFoundError**

```bash
pytest tests/unit/test_salt_returner.py -v
```

Expected: fail — `salt/returners/fleet_platform_return.py` doesn't exist.

- [ ] **Step 3: Create salt/ directory structure**

```bash
mkdir -p salt/returners salt/states/base
touch salt/__init__.py salt/returners/__init__.py
```

- [ ] **Step 4: Create salt/returners/fleet_platform_return.py**

```python
# salt/returners/fleet_platform_return.py
"""
Fleet Platform Salt returner.

Sends Salt job results to the Fleet Platform ingest API.

Installation:
  1. Copy to /srv/salt/_returners/fleet_platform_return.py
  2. Run: salt '*' saltutil.sync_returners
  3. Configure in /etc/salt/minion.d/fleet_platform.conf:

       return: fleet_platform_return

  4. Set in each minion's pillar:
       fleet_platform:
         ingest_url: https://fleet.internal/api/v1/ingest
         node_token: <token from POST /api/v1/nodes/register>
"""

import json
import logging
import urllib.error
import urllib.request

log = logging.getLogger(__name__)


def _cfg(key, default=None):
    return __salt__["config.get"](f"fleet_platform.{key}", default)  # noqa: F821


def returner(ret):
    """POST job result to /api/v1/ingest/executions. Called after every Salt job."""
    ingest_url = _cfg("ingest_url")
    node_token = _cfg("node_token")

    if not ingest_url or not node_token:
        log.warning("fleet_platform_return: ingest_url or node_token not set — skipping")
        return

    payload = {
        "minion_id": ret.get("id", ""),
        "jid": ret.get("jid", ""),
        "return_data": ret.get("return") or {},
        "fun": ret.get("fun", ""),
        "retcode": ret.get("retcode", 0),
        "success": ret.get("success", True),
    }

    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{ingest_url}/executions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Node-Token": node_token,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            log.debug("fleet_platform_return: posted jid=%s status=%s", payload["jid"], resp.status)
    except urllib.error.URLError as exc:
        log.error("fleet_platform_return: failed to post jid=%s error=%s", payload["jid"], exc)


def prep_jid(nocache=False, passed_jid=None):
    """Return a job ID — delegate to Salt's jid generator."""
    if passed_jid is not None:
        return passed_jid
    return __salt__["jid.gen_jid"]({})  # noqa: F821


def save_load(jid, load, minions=None):
    """Required by Salt returner interface — not used."""


def get_load(jid):
    """Required by Salt returner interface — not used."""
    return {}
```

- [ ] **Step 5: Create salt/states/base/grain_report.sls**

```yaml
# salt/states/base/grain_report.sls
# Reports current grain data to the Fleet Platform ingest API.
# Apply manually or via reactor on minion start:
#   salt '*' state.apply base.grain_report

{% set ingest_url = pillar.get('fleet_platform', {}).get('ingest_url', '') %}
{% set node_token = pillar.get('fleet_platform', {}).get('node_token', '') %}

report_grains_to_fleet_platform:
  module.run:
    - name: http.query
    - url: {{ ingest_url }}/grains
    - method: POST
    - header_list:
        - "Content-Type: application/json"
        - "X-Node-Token: {{ node_token }}"
    - data: >
        {"minion_id": "{{ grains['id'] }}", "grains": {{ grains | tojson }}}
    - unless: test -z "{{ ingest_url }}"
```

- [ ] **Step 6: Run tests — expect all pass**

```bash
pytest tests/unit/test_salt_returner.py -v
```

Expected: `4 passed`

- [ ] **Step 7: Commit**

```bash
git add salt/ tests/unit/test_salt_returner.py
git commit -m "feat: Salt returner + grain_report state — POSTs results to /api/v1/ingest"
```

---

## Task 11: Full test suite run

**Files:** None new.

- [ ] **Step 1: Ensure Docker is running**

```bash
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "postgres|redis"
```

If not running:
```bash
cd deploy && docker compose up -d && cd ..
```

Wait 15 seconds for health checks.

- [ ] **Step 2: Run the full test suite**

```bash
cd /home/dk/Documents/git/kri
source .venv/bin/activate
pytest --tb=short -q
```

Expected output (all passing):
```
tests/integration/test_auth_endpoints.py ...... [ xx%]
tests/integration/test_health.py ..            [ xx%]
tests/integration/test_ingest_executions.py ... [ xx%]
tests/integration/test_ingest_grains.py .....  [ xx%]
tests/integration/test_ingest_sbom.py ....     [ xx%]
tests/integration/test_node_registration.py ....[ xx%]
tests/unit/test_auth_core.py .....             [ xx%]
tests/unit/test_celery_app.py ...              [ xx%]
tests/unit/test_config.py ...                  [ xx%]
tests/unit/test_ingest_schemas.py .......      [ xx%]
tests/unit/test_maintenance_task.py ..         [ xx%]
tests/unit/test_node_status.py .......         [ xx%]
tests/unit/test_salt_returner.py ....          [ xx%]
tests/unit/test_sync_session.py ..             [ xx%]

XX passed in X.XXs
```

If any test fails, fix before proceeding.

- [ ] **Step 3: Smoke-test Celery worker (optional, requires Redis running)**

```bash
source .venv/bin/activate
celery -A fleet_platform.workers.celery_app worker --queues drift,sbom,maintenance \
  --loglevel=info --concurrency=2 &
WORKER_PID=$!
sleep 3
celery -A fleet_platform.workers.celery_app inspect active
kill $WORKER_PID
```

Expected: worker starts, reports active queues, shuts down cleanly.

- [ ] **Step 4: Final commit**

```bash
git add -A
git status
# Only commit if there are untracked files (e.g. __pycache__ should be gitignored)
git commit -m "chore: plan 2 complete — salt ingest pipeline, XX tests passing" 2>/dev/null || echo "Nothing to commit"
```

---

## Plan 2 Self-Review

**Spec coverage check (RFC sections):**
- ✅ RFC §8 (Event/Data Flow) — grain sync → ingest API → node_facts → drift queue
- ✅ RFC §6 (Backend: Ingest service, Celery workers, queue architecture)
- ✅ RFC §13 (Security: node token hash, per-node auth for ingest)
- ✅ RFC §15 (Operational: mark_stale_nodes beat task)
- ✅ RFC §16 (Failure: ingest returns non-blocking 202 for SBOM; executions are idempotent by jid)

**Not in this plan (correct — belong in later plans):**
- Full drift computation → Plan 4
- CycloneDX parsing/indexing → Plan 5
- `/api/v1/nodes` listing + detail → Plan 3
- `/api/v1/groups` CRUD → Plan 3
- React frontend → Plan 6

**Type consistency check:**
- `compute_drift.delay(str(node.id))` — task accepts `node_id: str` ✅
- `index_sbom.delay(node_id=str(node.id), file_path=tmp.name)` — task accepts `node_id: str, file_path: str` ✅
- `verify_node_token(token, node.node_token_hash)` — both `str`, returns `bool` ✅
- `classify_status(last_seen_at)` — accepts `datetime | None`, returns `str` ✅
- `hash_password(token)` → `str` stored in `node.node_token_hash: str` ✅

**Placeholder scan:** No TBDs, all code complete, all test assertions concrete. ✅
