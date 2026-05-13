# Fleet Platform — Plan 3: Fleet API

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the accumulated fleet data through a complete read/write REST API — fleet overview, node listing with filtering, node detail, tags, groups, and dynamic group resolution.

**Architecture:** Four new FastAPI routers (`fleet`, `nodes` extended, `groups`, `search`) backed by SQLAlchemy async queries with cursor/offset pagination. Fleet overview is Redis-cached (15 s TTL) to avoid repeated aggregation queries on every dashboard load. Dynamic groups evaluate a JSON predicate against the `tags` table at query time using correlated EXISTS subqueries. The `group_resolver` service is stateless and unit-testable independently of HTTP.

**Tech Stack:** Python 3.13, FastAPI 0.115, SQLAlchemy 2.0, redis.asyncio 5.x, pydantic v2, pytest 8.3, pytest-asyncio 1.3, httpx 0.28

**Branch:** `feat/plan-3-fleet-api` (branch from `master` before starting)

---

## Scope

This is Plan 3 of 6:
- ✅ Plan 1: Foundation — DB, FastAPI, JWT auth
- ✅ Plan 2: Salt + ingest pipeline
- **Plan 3 (this):** Fleet API — overview, nodes, groups, search
- Plan 4: Drift engine
- Plan 5: SBOM pipeline
- Plan 6: React frontend

When Plan 3 is complete: every node, group, and tag operation the frontend needs is available via a tested API. Drift and SBOM endpoints are stubs (Plans 4 & 5).

---

## File Map

```
fleet_platform/
├── api/
│   ├── deps.py              MODIFY — add get_redis() async dependency
│   ├── main.py              MODIFY — register fleet + groups routers
│   └── routes/
│       ├── nodes.py         MODIFY — add GET /nodes, /nodes/{id}, /facts, /packages, /tags
│       ├── fleet.py         CREATE — GET /api/v1/fleet/overview (Redis-cached)
│       ├── groups.py        CREATE — CRUD + members + dynamic resolution
│       └── search.py        CREATE — GET /api/v1/search?q=
├── schemas/
│   ├── fleet.py             CREATE — FleetOverviewResponse, NodeListItem, NodeDetailResponse
│   ├── group.py             CREATE — GroupCreate, GroupResponse, GroupMemberAdd
│   └── tag.py               CREATE — TagCreate, TagResponse
└── services/
    └── group_resolver.py    CREATE — resolve_dynamic_group() predicate evaluator

tests/
└── integration/
    ├── test_fleet_overview.py    CREATE — 4 tests
    ├── test_nodes_api.py         CREATE — 8 tests
    ├── test_groups_api.py        CREATE — 9 tests
    └── test_search_api.py        CREATE — 3 tests
```

---

## Task 1: Redis dependency + fleet schemas

**Files:**
- Modify: `fleet_platform/api/deps.py`
- Create: `fleet_platform/schemas/fleet.py`
- Create: `fleet_platform/schemas/tag.py`
- Create: `fleet_platform/schemas/group.py`
- Create: `tests/unit/test_fleet_schemas.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_fleet_schemas.py
import uuid
from datetime import UTC, datetime

from fleet_platform.schemas.fleet import FleetOverviewResponse, NodeListItem, NodeDetailResponse
from fleet_platform.schemas.group import GroupCreate, GroupResponse
from fleet_platform.schemas.tag import TagCreate, TagResponse


def test_fleet_overview_response():
    r = FleetOverviewResponse(
        total_nodes=10, online=8, stale=1, offline=1, unknown=0,
        avg_drift_score=12, nodes_clean=6, nodes_low=2, nodes_medium=1,
        nodes_high=1, nodes_critical=0, last_updated=datetime.now(UTC),
    )
    assert r.total_nodes == 10
    assert r.online == 8


def test_node_list_item_has_required_fields():
    item = NodeListItem(
        id=uuid.uuid4(), minion_id="mac-01.local", hostname="mac-01",
        status="online", drift_score=5, last_seen_at=datetime.now(UTC),
        tags=[],
    )
    assert item.status == "online"


def test_group_create_requires_name_and_type():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        GroupCreate(type="static")  # missing name


def test_group_create_static():
    g = GroupCreate(name="prod-builders", type="static")
    assert g.predicate is None


def test_group_create_dynamic_requires_predicate():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        GroupCreate(name="prod", type="dynamic")  # missing predicate


def test_tag_create():
    t = TagCreate(key="env", value="prod")
    assert t.key == "env"
```

- [ ] **Step 2: Run — expect ImportError**

```bash
cd /home/dk/Documents/git/kri && source .venv/bin/activate
pytest tests/unit/test_fleet_schemas.py -v
```

Expected: `ImportError: cannot import name 'FleetOverviewResponse'`

- [ ] **Step 3: Create fleet_platform/schemas/fleet.py**

```python
# fleet_platform/schemas/fleet.py
import uuid
from datetime import datetime

from pydantic import BaseModel


class TagResponse(BaseModel):
    key: str
    value: str

    model_config = {"from_attributes": True}


class NodeListItem(BaseModel):
    id: uuid.UUID
    minion_id: str
    hostname: str | None
    ip_address: str | None = None
    os_version: str | None
    hardware_model: str | None
    status: str
    drift_score: int
    last_seen_at: datetime | None
    tags: list[TagResponse]

    model_config = {"from_attributes": True}


class NodeDetailResponse(NodeListItem):
    os_build: str | None
    cpu_cores: int | None
    ram_gb: float | None
    storage_gb: float | None
    first_seen_at: datetime
    created_at: datetime


class FleetOverviewResponse(BaseModel):
    total_nodes: int
    online: int
    stale: int
    offline: int
    unknown: int
    avg_drift_score: int
    nodes_clean: int
    nodes_low: int
    nodes_medium: int
    nodes_high: int
    nodes_critical: int
    last_updated: datetime
```

- [ ] **Step 4: Create fleet_platform/schemas/tag.py**

```python
# fleet_platform/schemas/tag.py
from pydantic import BaseModel


class TagCreate(BaseModel):
    key: str
    value: str


class TagResponse(BaseModel):
    key: str
    value: str

    model_config = {"from_attributes": True}
```

- [ ] **Step 5: Create fleet_platform/schemas/group.py**

```python
# fleet_platform/schemas/group.py
import uuid
from datetime import datetime

from pydantic import BaseModel, model_validator


class GroupCreate(BaseModel):
    name: str
    description: str | None = None
    type: str  # "static" or "dynamic"
    predicate: dict | None = None

    @model_validator(mode="after")
    def predicate_required_for_dynamic(self) -> "GroupCreate":
        if self.type == "dynamic" and not self.predicate:
            raise ValueError("predicate is required for dynamic groups")
        return self


class GroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    predicate: dict | None = None


class GroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    type: str
    predicate: dict | None
    member_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class GroupMemberAdd(BaseModel):
    node_id: uuid.UUID
```

- [ ] **Step 6: Add missing import to test file**

Add `import pytest` at the top of `tests/unit/test_fleet_schemas.py`.

- [ ] **Step 7: Run tests — expect 6 passed**

```bash
source .venv/bin/activate && pytest tests/unit/test_fleet_schemas.py -v
```

Expected: `6 passed`

- [ ] **Step 8: Add get_redis() to fleet_platform/api/deps.py**

Replace the entire file:

```python
# fleet_platform/api/deps.py
from collections.abc import AsyncGenerator

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.config import settings
from fleet_platform.db.session import AsyncSessionLocal

_redis_client: aioredis.Redis | None = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client
```

- [ ] **Step 9: Commit**

```bash
git add fleet_platform/schemas/fleet.py fleet_platform/schemas/tag.py \
        fleet_platform/schemas/group.py fleet_platform/api/deps.py \
        tests/unit/test_fleet_schemas.py
git commit -m "feat: fleet/group/tag schemas + Redis dependency"
```

---

## Task 2: Fleet overview endpoint

**Files:**
- Create: `fleet_platform/api/routes/fleet.py`
- Create: `tests/integration/test_fleet_overview.py`
- Modify: `fleet_platform/api/main.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/test_fleet_overview.py
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


async def test_fleet_overview_returns_200(admin_client: AsyncClient):
    with patch("fleet_platform.api.routes.fleet.get_redis") as mock_redis_dep:
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None   # cache miss
        mock_redis.setex = AsyncMock()
        mock_redis_dep.return_value = mock_redis
        response = await admin_client.get("/api/v1/fleet/overview")
    assert response.status_code == 200


async def test_fleet_overview_shape(admin_client: AsyncClient):
    with patch("fleet_platform.api.routes.fleet.get_redis") as mock_redis_dep:
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_redis.setex = AsyncMock()
        mock_redis_dep.return_value = mock_redis
        response = await admin_client.get("/api/v1/fleet/overview")
    data = response.json()
    for field in ("total_nodes", "online", "stale", "offline", "avg_drift_score",
                  "nodes_clean", "nodes_low", "nodes_medium", "nodes_high",
                  "nodes_critical", "last_updated"):
        assert field in data, f"missing field: {field}"


async def test_fleet_overview_serves_cache(admin_client: AsyncClient):
    import json
    from datetime import UTC, datetime
    cached = json.dumps({
        "total_nodes": 42, "online": 40, "stale": 1, "offline": 1, "unknown": 0,
        "avg_drift_score": 7, "nodes_clean": 35, "nodes_low": 4, "nodes_medium": 2,
        "nodes_high": 1, "nodes_critical": 0,
        "last_updated": datetime.now(UTC).isoformat(),
    })
    with patch("fleet_platform.api.routes.fleet.get_redis") as mock_redis_dep:
        mock_redis = AsyncMock()
        mock_redis.get.return_value = cached
        mock_redis_dep.return_value = mock_redis
        response = await admin_client.get("/api/v1/fleet/overview")
    assert response.status_code == 200
    assert response.json()["total_nodes"] == 42


async def test_fleet_overview_requires_auth(client: AsyncClient):
    response = await client.get("/api/v1/fleet/overview")
    assert response.status_code == 401
```

- [ ] **Step 2: Run — expect 404**

```bash
source .venv/bin/activate && pytest tests/integration/test_fleet_overview.py -v
```

- [ ] **Step 3: Create fleet_platform/api/routes/fleet.py**

```python
# fleet_platform/api/routes/fleet.py
import json
from datetime import UTC, datetime

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db, get_redis
from fleet_platform.core.auth import get_current_user
from fleet_platform.models.node import Node
from fleet_platform.schemas.fleet import FleetOverviewResponse

router = APIRouter(prefix="/api/v1/fleet")

_OVERVIEW_CACHE_KEY = "fleet:overview"
_OVERVIEW_TTL = 15  # seconds


@router.get("/overview", response_model=FleetOverviewResponse)
async def fleet_overview(
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(get_redis),
    _: dict = Depends(get_current_user),
):
    cached = await redis.get(_OVERVIEW_CACHE_KEY)
    if cached:
        return FleetOverviewResponse(**json.loads(cached))

    rows = await db.execute(
        select(
            func.count().label("total"),
            func.sum((Node.status == "online").cast(func.INTEGER)).label("online"),
            func.sum((Node.status == "stale").cast(func.INTEGER)).label("stale"),
            func.sum((Node.status == "offline").cast(func.INTEGER)).label("offline"),
            func.sum((Node.status == "unknown").cast(func.INTEGER)).label("unknown"),
            func.coalesce(func.avg(Node.drift_score), 0).label("avg_drift"),
            func.sum((Node.drift_score <= 5).cast(func.INTEGER)).label("clean"),
            func.sum(((Node.drift_score >= 6) & (Node.drift_score <= 20)).cast(func.INTEGER)).label("low"),
            func.sum(((Node.drift_score >= 21) & (Node.drift_score <= 50)).cast(func.INTEGER)).label("medium"),
            func.sum(((Node.drift_score >= 51) & (Node.drift_score <= 80)).cast(func.INTEGER)).label("high"),
            func.sum((Node.drift_score >= 81).cast(func.INTEGER)).label("critical"),
        )
    )
    row = rows.one()
    now = datetime.now(UTC)

    data = FleetOverviewResponse(
        total_nodes=row.total or 0,
        online=row.online or 0,
        stale=row.stale or 0,
        offline=row.offline or 0,
        unknown=row.unknown or 0,
        avg_drift_score=int(row.avg_drift or 0),
        nodes_clean=row.clean or 0,
        nodes_low=row.low or 0,
        nodes_medium=row.medium or 0,
        nodes_high=row.high or 0,
        nodes_critical=row.critical or 0,
        last_updated=now,
    )

    await redis.setex(_OVERVIEW_CACHE_KEY, _OVERVIEW_TTL, data.model_dump_json())
    return data
```

- [ ] **Step 4: Register fleet router in fleet_platform/api/main.py**

Change the import line:
```python
from fleet_platform.api.routes import health, auth, nodes, ingest
```
to:
```python
from fleet_platform.api.routes import health, auth, nodes, ingest, fleet
```

Add after `app.include_router(ingest.router, tags=["ingest"])`:
```python
app.include_router(fleet.router, tags=["fleet"])
```

- [ ] **Step 5: Run tests — expect 4 passed**

```bash
source .venv/bin/activate && pytest tests/integration/test_fleet_overview.py -v
```

Note: The SQLAlchemy boolean cast for PostgreSQL may need adjustment. If tests fail with a cast error, replace the boolean cast pattern with `case((condition, 1), else_=0)`:

```python
from sqlalchemy import case
# Replace e.g.:
func.sum((Node.status == "online").cast(func.INTEGER))
# With:
func.sum(case((Node.status == "online", 1), else_=0))
```

- [ ] **Step 6: Commit**

```bash
git add fleet_platform/api/routes/fleet.py fleet_platform/api/main.py \
        tests/integration/test_fleet_overview.py
git commit -m "feat: GET /api/v1/fleet/overview with Redis cache"
```

---

## Task 3: Node listing + filtering

**Files:**
- Modify: `fleet_platform/api/routes/nodes.py`
- Create: `tests/integration/test_nodes_api.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/test_nodes_api.py
import secrets
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.auth import hash_password
from fleet_platform.models.node import Node, Tag


@pytest.fixture
async def two_nodes(db_session: AsyncSession):
    token_a = secrets.token_urlsafe(32)
    token_b = secrets.token_urlsafe(32)
    node_a = Node(
        minion_id="api-node-a.local", hostname="api-node-a",
        node_token_hash=hash_password(token_a),
        first_seen_at=datetime.now(UTC), status="online", drift_score=10,
    )
    node_b = Node(
        minion_id="api-node-b.local", hostname="api-node-b",
        node_token_hash=hash_password(token_b),
        first_seen_at=datetime.now(UTC), status="offline", drift_score=55,
    )
    db_session.add_all([node_a, node_b])
    await db_session.commit()
    await db_session.refresh(node_a)
    await db_session.refresh(node_b)

    tag = Tag(node_id=node_a.id, key="env", value="prod",
              created_at=datetime.now(UTC))
    db_session.add(tag)
    await db_session.commit()

    yield node_a, node_b

    await db_session.delete(node_a)
    await db_session.delete(node_b)
    await db_session.commit()


async def test_list_nodes_returns_200(admin_client: AsyncClient, two_nodes):
    response = await admin_client.get("/api/v1/nodes")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 2


async def test_list_nodes_filter_by_status(admin_client: AsyncClient, two_nodes):
    response = await admin_client.get("/api/v1/nodes?status=online")
    assert response.status_code == 200
    items = response.json()["items"]
    assert all(n["status"] == "online" for n in items)


async def test_list_nodes_filter_by_tag(admin_client: AsyncClient, two_nodes):
    response = await admin_client.get("/api/v1/nodes?tag=env:prod")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) >= 1
    assert items[0]["hostname"] == "api-node-a"


async def test_list_nodes_pagination(admin_client: AsyncClient, two_nodes):
    response = await admin_client.get("/api/v1/nodes?page=1&per_page=1")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["per_page"] == 1


async def test_get_node_detail(admin_client: AsyncClient, two_nodes):
    node_a, _ = two_nodes
    response = await admin_client.get(f"/api/v1/nodes/{node_a.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["minion_id"] == "api-node-a.local"
    assert "cpu_cores" in data
    assert "node_token_hash" not in data  # must never be exposed


async def test_get_node_not_found(admin_client: AsyncClient):
    import uuid
    response = await admin_client.get(f"/api/v1/nodes/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_list_nodes_requires_auth(client: AsyncClient):
    response = await client.get("/api/v1/nodes")
    assert response.status_code == 401


async def test_get_node_requires_auth(client: AsyncClient, two_nodes):
    node_a, _ = two_nodes
    response = await client.get(f"/api/v1/nodes/{node_a.id}")
    assert response.status_code == 401
```

- [ ] **Step 2: Run — expect 404 / 401 (endpoints missing)**

```bash
source .venv/bin/activate && pytest tests/integration/test_nodes_api.py -v
```

- [ ] **Step 3: Add node listing + detail to fleet_platform/api/routes/nodes.py**

The current `nodes.py` only has `POST /register`. Add the read endpoints by appending to the file.

First, add these imports at the top of `fleet_platform/api/routes/nodes.py`:

```python
import uuid

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from fleet_platform.core.auth import get_current_user
from fleet_platform.models.node import Tag
from fleet_platform.schemas.fleet import NodeDetailResponse, NodeListItem
from fleet_platform.schemas.common import PaginatedResponse
```

Then add these endpoints after `register_node`:

```python
@router.get("", response_model=PaginatedResponse[NodeListItem])
async def list_nodes(
    status: str | None = None,
    tag: str | None = None,
    group_id: uuid.UUID | None = None,
    sort: str = "drift_score:desc",
    page: int = 1,
    per_page: int = 25,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    query = (
        select(Node)
        .options(selectinload(Node.tags))
    )

    if status:
        query = query.where(Node.status == status)

    if tag:
        key, _, value = tag.partition(":")
        subq = (
            select(Tag.node_id)
            .where(Tag.key == key, Tag.value == value)
            .scalar_subquery()
        )
        query = query.where(Node.id.in_(subq))

    if group_id:
        from fleet_platform.models.group import GroupMember
        member_subq = (
            select(GroupMember.node_id)
            .where(GroupMember.group_id == group_id)
            .scalar_subquery()
        )
        query = query.where(Node.id.in_(member_subq))

    sort_field, _, sort_dir = sort.partition(":")
    sort_col = getattr(Node, sort_field, Node.drift_score)
    query = query.order_by(sort_col.desc() if sort_dir == "desc" else sort_col.asc())

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar_one()

    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    nodes = result.scalars().all()

    return PaginatedResponse(
        items=[NodeListItem.model_validate(n) for n in nodes],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/{node_id}", response_model=NodeDetailResponse)
async def get_node(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(Node).options(selectinload(Node.tags)).where(Node.id == node_id)
    )
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")
    return NodeDetailResponse.model_validate(node)
```

- [ ] **Step 4: Run tests — expect 8 passed**

```bash
source .venv/bin/activate && pytest tests/integration/test_nodes_api.py -v
```

If `sort_col` raises `AttributeError` for invalid sort fields, add:

```python
_SORT_FIELDS = {"drift_score", "hostname", "status", "last_seen_at", "created_at"}
sort_field = sort_field if sort_field in _SORT_FIELDS else "drift_score"
```

- [ ] **Step 5: Commit**

```bash
git add fleet_platform/api/routes/nodes.py tests/integration/test_nodes_api.py
git commit -m "feat: GET /api/v1/nodes list+filter+paginate + GET /api/v1/nodes/{id}"
```

---

## Task 4: Node facts, packages, and tags endpoints

**Files:**
- Modify: `fleet_platform/api/routes/nodes.py`
- Modify: `tests/integration/test_nodes_api.py` (add more tests)

- [ ] **Step 1: Add tests to test_nodes_api.py**

Append to `tests/integration/test_nodes_api.py`:

```python
async def test_get_node_facts_no_grains_returns_empty(admin_client: AsyncClient, two_nodes):
    node_a, _ = two_nodes
    response = await admin_client.get(f"/api/v1/nodes/{node_a.id}/facts")
    assert response.status_code == 200
    # No grains ingested for this node, so grains dict is empty or 404
    assert response.json() in ({"grains": {}}, {"grains": None}) or response.status_code == 404


async def test_add_tag_to_node(admin_client: AsyncClient, two_nodes):
    node_a, _ = two_nodes
    response = await admin_client.post(
        f"/api/v1/nodes/{node_a.id}/tags",
        json={"key": "team", "value": "mobile"},
    )
    assert response.status_code == 201
    assert response.json()["key"] == "team"


async def test_add_tag_requires_operator(viewer_client: AsyncClient, two_nodes):
    node_a, _ = two_nodes
    response = await viewer_client.post(
        f"/api/v1/nodes/{node_a.id}/tags",
        json={"key": "team", "value": "mobile"},
    )
    assert response.status_code == 403


async def test_delete_tag_from_node(admin_client: AsyncClient, two_nodes, db_session: AsyncSession):
    node_a, _ = two_nodes
    # The env:prod tag was added in the fixture
    response = await admin_client.delete(f"/api/v1/nodes/{node_a.id}/tags/env")
    assert response.status_code == 204


async def test_delete_nonexistent_tag_returns_404(admin_client: AsyncClient, two_nodes):
    node_a, _ = two_nodes
    response = await admin_client.delete(f"/api/v1/nodes/{node_a.id}/tags/nonexistent-key")
    assert response.status_code == 404
```

- [ ] **Step 2: Run — expect 5 failures (endpoints missing)**

```bash
source .venv/bin/activate && pytest tests/integration/test_nodes_api.py -v -k "facts or tag"
```

- [ ] **Step 3: Add facts + packages + tags endpoints to fleet_platform/api/routes/nodes.py**

Add these imports at the top of `nodes.py` (if not already present):

```python
from datetime import UTC, datetime
from fleet_platform.models.facts import NodeFact
from fleet_platform.schemas.tag import TagCreate, TagResponse
from fleet_platform.core.audit import audit
```

Append these endpoints to `nodes.py`:

```python
@router.get("/{node_id}/facts")
async def get_node_facts(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    result = await db.execute(
        select(NodeFact)
        .where(NodeFact.node_id == node_id)
        .order_by(NodeFact.collected_at.desc())
        .limit(1)
    )
    fact = result.scalar_one_or_none()
    return {"grains": fact.grains if fact else {}}


@router.get("/{node_id}/packages")
async def get_node_packages(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Return installed packages extracted from the latest Salt grain snapshot."""
    result = await db.execute(
        select(NodeFact)
        .where(NodeFact.node_id == node_id)
        .order_by(NodeFact.collected_at.desc())
        .limit(1)
    )
    fact = result.scalar_one_or_none()
    if not fact:
        return {"items": [], "source": "grains"}

    grains = fact.grains
    # Salt macOS: brew packages are in grains["pkgs"] as {name: version}
    pkgs_raw = grains.get("pkgs") or grains.get("brew_pkgs") or {}
    packages = [
        {"name": name, "version": version, "source": "brew"}
        for name, version in (pkgs_raw.items() if isinstance(pkgs_raw, dict) else [])
    ]
    return {"items": packages, "source": "grains", "collected_at": fact.collected_at}


@router.post("/{node_id}/tags", response_model=TagResponse, status_code=201)
async def add_node_tag(
    node_id: uuid.UUID,
    payload: TagCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")

    # Upsert: replace existing tag with same key
    existing = await db.execute(
        select(Tag).where(Tag.node_id == node_id, Tag.key == payload.key)
    )
    tag = existing.scalar_one_or_none()
    if tag:
        tag.value = payload.value
    else:
        tag = Tag(node_id=node_id, key=payload.key, value=payload.value,
                  created_at=datetime.now(UTC))
        db.add(tag)

    await audit(db, actor=claims["email"], action="node.tag.upsert",
                resource_type="node", resource_id=node_id,
                new_value={"key": payload.key, "value": payload.value})
    await db.commit()
    await db.refresh(tag)
    return TagResponse.model_validate(tag)


@router.delete("/{node_id}/tags/{key}", status_code=204)
async def delete_node_tag(
    node_id: uuid.UUID,
    key: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    result = await db.execute(
        select(Tag).where(Tag.node_id == node_id, Tag.key == key)
    )
    tag = result.scalar_one_or_none()
    if not tag:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")

    old_value = {"key": tag.key, "value": tag.value}
    await db.delete(tag)
    await audit(db, actor=claims["email"], action="node.tag.delete",
                resource_type="node", resource_id=node_id, old_value=old_value)
    await db.commit()
```

- [ ] **Step 4: Run all nodes tests — expect 13 passed**

```bash
source .venv/bin/activate && pytest tests/integration/test_nodes_api.py -v
```

- [ ] **Step 5: Commit**

```bash
git add fleet_platform/api/routes/nodes.py tests/integration/test_nodes_api.py
git commit -m "feat: node facts, packages, and tag add/remove endpoints"
```

---

## Task 5: Dynamic group resolver service

**Files:**
- Create: `fleet_platform/services/group_resolver.py`
- Create: `tests/unit/test_group_resolver.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_group_resolver.py
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from fleet_platform.services.group_resolver import resolve_dynamic_group, validate_predicate


def test_validate_predicate_valid():
    p = {"and": [{"key": "env", "value": "prod"}]}
    assert validate_predicate(p) is True


def test_validate_predicate_missing_and():
    assert validate_predicate({}) is False
    assert validate_predicate({"or": []}) is False


def test_validate_predicate_missing_key():
    assert validate_predicate({"and": [{"value": "prod"}]}) is False


def test_validate_predicate_missing_value():
    assert validate_predicate({"and": [{"key": "env"}]}) is False


def test_validate_predicate_empty_conditions():
    assert validate_predicate({"and": []}) is False


async def test_resolve_empty_predicate_returns_empty():
    mock_db = AsyncMock()
    result = await resolve_dynamic_group({}, mock_db)
    assert result == []
```

- [ ] **Step 2: Run — expect ImportError**

```bash
source .venv/bin/activate && pytest tests/unit/test_group_resolver.py -v
```

- [ ] **Step 3: Create fleet_platform/services/group_resolver.py**

```python
# fleet_platform/services/group_resolver.py
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.node import Node, Tag


def validate_predicate(predicate: dict) -> bool:
    """Return True if predicate has the correct structure for a dynamic group."""
    conditions = predicate.get("and")
    if not conditions or not isinstance(conditions, list):
        return False
    for cond in conditions:
        if "key" not in cond or "value" not in cond:
            return False
    return True


async def resolve_dynamic_group(
    predicate: dict, db: AsyncSession
) -> list[uuid.UUID]:
    """Return node IDs matching all conditions in the predicate.

    Predicate format: {"and": [{"key": "env", "value": "prod"}, ...]}
    Empty or invalid predicate returns [].
    """
    if not validate_predicate(predicate):
        return []

    query = select(Node.id)
    for cond in predicate["and"]:
        subq = (
            select(Tag.node_id)
            .where(Tag.key == cond["key"])
            .where(Tag.value == cond["value"])
            .scalar_subquery()
        )
        query = query.where(Node.id.in_(subq))

    result = await db.execute(query)
    return [row[0] for row in result.fetchall()]
```

- [ ] **Step 4: Run — expect 6 passed**

```bash
source .venv/bin/activate && pytest tests/unit/test_group_resolver.py -v
```

- [ ] **Step 5: Commit**

```bash
git add fleet_platform/services/group_resolver.py tests/unit/test_group_resolver.py
git commit -m "feat: dynamic group resolver — validate_predicate() + resolve_dynamic_group()"
```

---

## Task 6: Groups API

**Files:**
- Create: `fleet_platform/api/routes/groups.py`
- Create: `tests/integration/test_groups_api.py`
- Modify: `fleet_platform/api/main.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_groups_api.py
import uuid

import pytest
from httpx import AsyncClient


async def test_create_static_group(admin_client: AsyncClient):
    response = await admin_client.post(
        "/api/v1/groups",
        json={"name": "prod-servers", "type": "static"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "prod-servers"
    assert data["type"] == "static"
    assert "id" in data


async def test_create_dynamic_group(admin_client: AsyncClient):
    response = await admin_client.post(
        "/api/v1/groups",
        json={
            "name": "prod-builders",
            "type": "dynamic",
            "predicate": {"and": [{"key": "env", "value": "prod"}, {"key": "role", "value": "builder"}]},
        },
    )
    assert response.status_code == 201
    assert response.json()["predicate"]["and"][0]["key"] == "env"


async def test_create_dynamic_group_missing_predicate_returns_422(admin_client: AsyncClient):
    response = await admin_client.post(
        "/api/v1/groups",
        json={"name": "broken", "type": "dynamic"},
    )
    assert response.status_code == 422


async def test_list_groups(admin_client: AsyncClient):
    response = await admin_client.get("/api/v1/groups")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data


async def test_get_group(admin_client: AsyncClient):
    create = await admin_client.post(
        "/api/v1/groups",
        json={"name": "test-get-group", "type": "static"},
    )
    group_id = create.json()["id"]
    response = await admin_client.get(f"/api/v1/groups/{group_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "test-get-group"


async def test_delete_group(admin_client: AsyncClient):
    create = await admin_client.post(
        "/api/v1/groups",
        json={"name": "to-delete", "type": "static"},
    )
    group_id = create.json()["id"]
    response = await admin_client.delete(f"/api/v1/groups/{group_id}")
    assert response.status_code == 204


async def test_get_deleted_group_returns_404(admin_client: AsyncClient):
    response = await admin_client.get(f"/api/v1/groups/{uuid.uuid4()}")
    assert response.status_code == 404


async def test_create_group_requires_operator(viewer_client: AsyncClient):
    response = await viewer_client.post(
        "/api/v1/groups",
        json={"name": "viewer-group", "type": "static"},
    )
    assert response.status_code == 403


async def test_list_groups_requires_auth(client: AsyncClient):
    response = await client.get("/api/v1/groups")
    assert response.status_code == 401
```

- [ ] **Step 2: Run — expect 404/401 (routes missing)**

```bash
source .venv/bin/activate && pytest tests/integration/test_groups_api.py -v
```

- [ ] **Step 3: Create fleet_platform/api/routes/groups.py**

```python
# fleet_platform/api/routes/groups.py
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user, require_role
from fleet_platform.models.group import Group, GroupMember
from fleet_platform.models.node import Node
from fleet_platform.schemas.common import PaginatedResponse
from fleet_platform.schemas.fleet import NodeListItem
from fleet_platform.schemas.group import GroupCreate, GroupMemberAdd, GroupResponse, GroupUpdate
from fleet_platform.services.group_resolver import resolve_dynamic_group

router = APIRouter(prefix="/api/v1/groups")


async def _get_group_or_404(group_id: uuid.UUID, db: AsyncSession) -> Group:
    result = await db.execute(select(Group).where(Group.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return group


async def _member_count(group_id: uuid.UUID, db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count()).where(GroupMember.group_id == group_id)
    )
    return result.scalar_one() or 0


@router.get("", response_model=PaginatedResponse[GroupResponse])
async def list_groups(
    page: int = 1,
    per_page: int = 25,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    total = (await db.execute(select(func.count()).select_from(Group))).scalar_one()
    result = await db.execute(
        select(Group).order_by(Group.name).offset((page - 1) * per_page).limit(per_page)
    )
    groups = result.scalars().all()
    items = []
    for g in groups:
        count = await _member_count(g.id, db)
        items.append(GroupResponse(
            id=g.id, name=g.name, description=g.description,
            type=g.type, predicate=g.predicate,
            member_count=count, created_at=g.created_at,
        ))
    return PaginatedResponse(items=items, total=total, page=page, per_page=per_page)


@router.post("", response_model=GroupResponse, status_code=201)
async def create_group(
    payload: GroupCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
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
    return GroupResponse(
        id=group.id, name=group.name, description=group.description,
        type=group.type, predicate=group.predicate,
        member_count=0, created_at=group.created_at,
    )


@router.get("/{group_id}", response_model=GroupResponse)
async def get_group(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    group = await _get_group_or_404(group_id, db)
    count = await _member_count(group_id, db)
    return GroupResponse(
        id=group.id, name=group.name, description=group.description,
        type=group.type, predicate=group.predicate,
        member_count=count, created_at=group.created_at,
    )


@router.patch("/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: uuid.UUID,
    payload: GroupUpdate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    group = await _get_group_or_404(group_id, db)
    if payload.name is not None:
        group.name = payload.name
    if payload.description is not None:
        group.description = payload.description
    if payload.predicate is not None:
        group.predicate = payload.predicate
    await db.commit()
    await db.refresh(group)
    count = await _member_count(group_id, db)
    return GroupResponse(
        id=group.id, name=group.name, description=group.description,
        type=group.type, predicate=group.predicate,
        member_count=count, created_at=group.created_at,
    )


@router.delete("/{group_id}", status_code=204)
async def delete_group(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    group = await _get_group_or_404(group_id, db)
    await db.delete(group)
    await db.commit()


@router.get("/{group_id}/nodes", response_model=PaginatedResponse[NodeListItem])
async def list_group_nodes(
    group_id: uuid.UUID,
    page: int = 1,
    per_page: int = 25,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    from sqlalchemy.orm import selectinload
    group = await _get_group_or_404(group_id, db)

    if group.type == "dynamic":
        node_ids = await resolve_dynamic_group(group.predicate or {}, db)
        query = (
            select(Node)
            .options(selectinload(Node.tags))
            .where(Node.id.in_(node_ids))
        )
    else:
        query = (
            select(Node)
            .options(selectinload(Node.tags))
            .join(GroupMember, GroupMember.node_id == Node.id)
            .where(GroupMember.group_id == group_id)
        )

    total = (await db.execute(
        select(func.count()).select_from(query.subquery())
    )).scalar_one()
    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    nodes = result.scalars().all()
    return PaginatedResponse(
        items=[NodeListItem.model_validate(n) for n in nodes],
        total=total, page=page, per_page=per_page,
    )


@router.post("/{group_id}/members", status_code=201)
async def add_group_member(
    group_id: uuid.UUID,
    payload: GroupMemberAdd,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    group = await _get_group_or_404(group_id, db)
    if group.type == "dynamic":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot add members to a dynamic group",
        )
    existing = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id, GroupMember.node_id == payload.node_id
        )
    )
    if existing.scalar_one_or_none():
        return {"status": "already_member"}
    db.add(GroupMember(group_id=group_id, node_id=payload.node_id,
                       added_at=datetime.now(UTC)))
    await db.commit()
    return {"status": "added"}


@router.delete("/{group_id}/members/{node_id}", status_code=204)
async def remove_group_member(
    group_id: uuid.UUID,
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    group = await _get_group_or_404(group_id, db)
    if group.type == "dynamic":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove members from a dynamic group",
        )
    result = await db.execute(
        select(GroupMember).where(
            GroupMember.group_id == group_id, GroupMember.node_id == node_id
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    await db.delete(member)
    await db.commit()
```

- [ ] **Step 4: Register groups router in fleet_platform/api/main.py**

Change import:
```python
from fleet_platform.api.routes import health, auth, nodes, ingest, fleet
```
to:
```python
from fleet_platform.api.routes import health, auth, nodes, ingest, fleet, groups
```

Add after `app.include_router(fleet.router, ...)`:
```python
app.include_router(groups.router, tags=["groups"])
```

- [ ] **Step 5: Run — expect 9 passed**

```bash
source .venv/bin/activate && pytest tests/integration/test_groups_api.py -v
```

- [ ] **Step 6: Commit**

```bash
git add fleet_platform/api/routes/groups.py fleet_platform/api/main.py \
        tests/integration/test_groups_api.py
git commit -m "feat: groups CRUD + member management + dynamic group resolution"
```

---

## Task 7: Search endpoint

**Files:**
- Create: `fleet_platform/api/routes/search.py`
- Create: `tests/integration/test_search_api.py`
- Modify: `fleet_platform/api/main.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_search_api.py
import secrets
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.auth import hash_password
from fleet_platform.models.node import Node, Tag


@pytest.fixture
async def searchable_node(db_session: AsyncSession):
    token = secrets.token_urlsafe(32)
    node = Node(
        minion_id="searchme-01.local", hostname="searchme-01",
        node_token_hash=hash_password(token),
        first_seen_at=datetime.now(UTC), status="online",
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)
    tag = Tag(node_id=node.id, key="role", value="searchable",
              created_at=datetime.now(UTC))
    db_session.add(tag)
    await db_session.commit()
    yield node
    await db_session.delete(node)
    await db_session.commit()


async def test_search_by_hostname(admin_client: AsyncClient, searchable_node):
    response = await admin_client.get("/api/v1/search?q=searchme")
    assert response.status_code == 200
    data = response.json()
    assert "nodes" in data
    assert any(n["hostname"] == "searchme-01" for n in data["nodes"])


async def test_search_requires_min_3_chars(admin_client: AsyncClient):
    response = await admin_client.get("/api/v1/search?q=ab")
    assert response.status_code == 422


async def test_search_requires_auth(client: AsyncClient):
    response = await client.get("/api/v1/search?q=searchme")
    assert response.status_code == 401
```

- [ ] **Step 2: Run — expect 404**

```bash
source .venv/bin/activate && pytest tests/integration/test_search_api.py -v
```

- [ ] **Step 3: Create fleet_platform/api/routes/search.py**

```python
# fleet_platform/api/routes/search.py
from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user
from fleet_platform.models.node import Node
from fleet_platform.schemas.fleet import NodeListItem

router = APIRouter(prefix="/api/v1")


@router.get("/search")
async def search(
    q: str = Query(min_length=3, description="Search term (min 3 chars)"),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    pattern = f"%{q}%"
    result = await db.execute(
        select(Node)
        .options(selectinload(Node.tags))
        .where(
            or_(
                Node.hostname.ilike(pattern),
                Node.minion_id.ilike(pattern),
                Node.ip_address.cast(str).ilike(pattern),
            )
        )
        .limit(50)
    )
    nodes = result.scalars().all()
    return {
        "query": q,
        "nodes": [NodeListItem.model_validate(n) for n in nodes],
    }
```

- [ ] **Step 4: Register search router in fleet_platform/api/main.py**

Change import:
```python
from fleet_platform.api.routes import health, auth, nodes, ingest, fleet, groups
```
to:
```python
from fleet_platform.api.routes import health, auth, nodes, ingest, fleet, groups, search
```

Add after `app.include_router(groups.router, ...)`:
```python
app.include_router(search.router, tags=["search"])
```

- [ ] **Step 5: Run — expect 3 passed**

```bash
source .venv/bin/activate && pytest tests/integration/test_search_api.py -v
```

- [ ] **Step 6: Commit**

```bash
git add fleet_platform/api/routes/search.py fleet_platform/api/main.py \
        tests/integration/test_search_api.py
git commit -m "feat: GET /api/v1/search?q= — nodes by hostname/minion_id/IP"
```

---

## Task 8: Full test suite run

- [ ] **Step 1: Ensure Docker is running**

```bash
docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "postgres|redis"
```

If not running:
```bash
cd /home/dk/Documents/git/kri/deploy && docker compose up -d && cd ..
```

- [ ] **Step 2: Run the full suite**

```bash
cd /home/dk/Documents/git/kri && source .venv/bin/activate && pytest --tb=short -q
```

Expected: all tests passing (57 existing + ~30 new = ~87 total). Zero failures.

If any test fails due to the `fleet_overview` SQLAlchemy cast (CRITICAL: fix before committing):

```python
# Replace the boolean cast style in fleet.py:
func.sum((Node.status == "online").cast(func.INTEGER))
# With:
from sqlalchemy import case
func.sum(case((Node.status == "online", 1), else_=0))
```

- [ ] **Step 3: Smoke test the new endpoints**

```bash
source .venv/bin/activate && uvicorn fleet_platform.api.main:app --port 8000 &
PID=$!
sleep 3

TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@fleet.local","password":"changeme"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s http://localhost:8000/api/v1/fleet/overview -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
curl -s "http://localhost:8000/api/v1/nodes" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
curl -s http://localhost:8000/api/v1/groups -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

kill $PID
```

- [ ] **Step 4: Commit if anything changed**

```bash
git add -A && git status
git diff --cached --stat
# Only commit if there are actual changes beyond __pycache__
git commit -m "chore: plan 3 complete — all tests passing" 2>/dev/null || echo "nothing to commit"
```

---

## Plan 3 Self-Review

**Spec coverage (RFC):**
- ✅ RFC §12 `GET /api/v1/fleet/overview` — total, online/stale/offline, drift buckets
- ✅ RFC §12 `GET /api/v1/nodes` — pagination, status filter, tag filter, sort
- ✅ RFC §12 `GET /api/v1/nodes/{id}` — full detail (no token hash)
- ✅ RFC §12 `GET /api/v1/nodes/{id}/facts` — latest grains snapshot
- ✅ RFC §2 Tags — add/remove with operator role + audit
- ✅ RFC §12 Groups CRUD — static + dynamic
- ✅ RFC §12 Group members — add/remove static, resolve dynamic
- ✅ RFC §12 `GET /api/v1/search` — hostname/minion_id/IP search
- ✅ RFC §14 Redis caching — overview cached 15 s

**Not in this plan (correct):**
- `GET /api/v1/nodes/{id}/drift` → Plan 4
- `GET /api/v1/nodes/{id}/sbom` → Plan 5
- `GET /api/v1/nodes/{id}/executions` → Plan 4 (reads existing execution_jobs)
- React frontend → Plan 6

**Type consistency check:**
- `NodeListItem` used in nodes list, groups/nodes list, search → same schema ✅
- `GroupResponse` uses `member_count: int = 0` and is constructed manually (not `model_validate`) because `member_count` isn't a DB column ✅
- `require_role("operator", "admin")` for write ops, `get_current_user` for reads ✅
- `TagResponse` defined in both `fleet.py` and `tag.py` — the `fleet.py` version is nested inside `NodeListItem`. The standalone `tag.py` version is returned by tag endpoints. Both have `key` and `value`. No collision since they're used in different contexts ✅

**Placeholder scan:** No TBDs. All code complete. All test assertions concrete. ✅
