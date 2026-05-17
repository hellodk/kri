# Audit Fix Plan 9 — Missing Features: User Management, Node Decommission, Audit Log API

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three missing features required for mission-critical ops: user management API (create/list/deactivate users), node soft-delete/decommission, and an audit log read API so the audit trail is actually accessible.

**Architecture:** User management is admin-only CRUD on the existing `users` table. Node decommission adds a `deleted_at` column via Alembic migration and filters it from all list queries — hard delete is not supported (audit events reference the UUID). Audit log API is a read-only paginated endpoint with filters for actor, action, resource_type, and date range.

**Tech Stack:** Python 3.13, FastAPI 0.115, SQLAlchemy 2.0 async, Alembic, psycopg3.

---

## Task 1: User Management API (M5)

**Files:**
- Create: `fleet_platform/api/routes/users.py`
- Create: `fleet_platform/schemas/user.py`
- Modify: `fleet_platform/api/main.py`
- Test: `tests/integration/test_users_api.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_users_api.py
import pytest
from httpx import AsyncClient


async def test_admin_can_list_users(admin_client: AsyncClient):
    r = await admin_client.get("/api/v1/users")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert data["total"] >= 1
    # Each item has expected fields
    user = data["items"][0]
    assert "id" in user
    assert "email" in user
    assert "role" in user
    assert "is_active" in user
    # password_hash must NOT be exposed
    assert "password_hash" not in user


async def test_admin_can_create_user(admin_client: AsyncClient):
    r = await admin_client.post("/api/v1/users", json={
        "email": "newop@fleet.local",
        "password": "Secur3Pass!",
        "role": "operator",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["email"] == "newop@fleet.local"
    assert data["role"] == "operator"
    assert "password_hash" not in data


async def test_admin_can_deactivate_user(admin_client: AsyncClient):
    # Create then deactivate
    r = await admin_client.post("/api/v1/users", json={
        "email": "todeactivate@fleet.local",
        "password": "Secur3Pass!",
        "role": "viewer",
    })
    user_id = r.json()["id"]
    r2 = await admin_client.patch(f"/api/v1/users/{user_id}", json={"is_active": False})
    assert r2.status_code == 200
    assert r2.json()["is_active"] is False


async def test_viewer_cannot_manage_users(viewer_client: AsyncClient):
    r = await viewer_client.get("/api/v1/users")
    assert r.status_code == 403


async def test_duplicate_email_rejected(admin_client: AsyncClient):
    await admin_client.post("/api/v1/users", json={
        "email": "dup@fleet.local", "password": "Secur3Pass!", "role": "viewer"
    })
    r = await admin_client.post("/api/v1/users", json={
        "email": "dup@fleet.local", "password": "Secur3Pass!", "role": "viewer"
    })
    assert r.status_code == 409


async def test_weak_password_rejected(admin_client: AsyncClient):
    r = await admin_client.post("/api/v1/users", json={
        "email": "weak@fleet.local", "password": "abc", "role": "viewer"
    })
    assert r.status_code == 422
```

- [ ] **Step 2: Run to confirm they fail**

```bash
source .venv/bin/activate && pytest tests/integration/test_users_api.py -v
```

Expected: all fail (no route yet).

- [ ] **Step 3: Create user schemas**

```python
# fleet_platform/schemas/user.py
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role: str = "viewer"

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str) -> str:
        if v not in ("admin", "operator", "viewer"):
            raise ValueError("Role must be admin, operator, or viewer")
        return v


class UserUpdate(BaseModel):
    role: str | None = None
    is_active: bool | None = None

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str | None) -> str | None:
        if v is not None and v not in ("admin", "operator", "viewer"):
            raise ValueError("Role must be admin, operator, or viewer")
        return v


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    role: str
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
```

- [ ] **Step 4: Create users router**

```python
# fleet_platform/api/routes/users.py
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user, hash_password, require_role
from fleet_platform.core.audit import audit
from fleet_platform.models.user import User
from fleet_platform.schemas.common import PaginatedResponse
from fleet_platform.schemas.user import UserCreate, UserResponse, UserUpdate

router = APIRouter(prefix="/api/v1/users")


@router.get("", response_model=PaginatedResponse[UserResponse])
async def list_users(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin")),
):
    total = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    result = await db.execute(
        select(User).order_by(User.created_at.desc())
        .offset((page - 1) * per_page).limit(per_page)
    )
    users = result.scalars().all()
    return PaginatedResponse(
        items=[UserResponse.model_validate(u) for u in users],
        total=total, page=page, per_page=per_page,
    )


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("admin")),
):
    existing = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    await audit(db, actor=claims["email"], action="user.create",
                resource_type="user", resource_id=user.id,
                new_value={"email": user.email, "role": user.role})
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("admin")),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    old = {"role": user.role, "is_active": user.is_active}
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active

    await audit(db, actor=claims["email"], action="user.update",
                resource_type="user", resource_id=user.id,
                old_value=old, new_value=payload.model_dump(exclude_none=True))
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)
```

- [ ] **Step 5: Register router in main.py**

Add `users` to the import and `app.include_router(users.router, tags=["users"])`.

- [ ] **Step 6: Run tests**

```bash
source .venv/bin/activate && pytest tests/integration/test_users_api.py -v
```

Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
git add fleet_platform/api/routes/users.py fleet_platform/schemas/user.py \
  fleet_platform/api/main.py tests/integration/test_users_api.py
git commit -m "feat(M5): user management API — list, create, update (admin only)"
```

---

## Task 2: Node Soft Delete / Decommission (M4)

**Files:**
- Create: `fleet_platform/db/migrations/versions/003_node_soft_delete.py`
- Modify: `fleet_platform/models/node.py` — add `deleted_at`
- Modify: `fleet_platform/api/routes/nodes.py` — add DELETE endpoint, filter deleted from lists
- Modify: `fleet_platform/api/routes/fleet.py` — filter deleted from overview counts
- Test: `tests/integration/test_nodes_api.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/integration/test_nodes_api.py`:

```python
async def test_admin_can_decommission_node(admin_client: AsyncClient, registered_node):
    node, _ = registered_node
    r = await admin_client.delete(f"/api/v1/nodes/{node.id}")
    assert r.status_code == 204


async def test_decommissioned_node_absent_from_list(admin_client: AsyncClient, registered_node):
    node, _ = registered_node
    await admin_client.delete(f"/api/v1/nodes/{node.id}")
    r = await admin_client.get("/api/v1/nodes")
    ids = [n["id"] for n in r.json()["items"]]
    assert str(node.id) not in ids


async def test_decommission_requires_admin(viewer_client: AsyncClient, registered_node):
    node, _ = registered_node
    r = await viewer_client.delete(f"/api/v1/nodes/{node.id}")
    assert r.status_code == 403
```

- [ ] **Step 2: Create migration 003**

```python
# fleet_platform/db/migrations/versions/003_node_soft_delete.py
"""Add deleted_at to nodes for soft-delete / decommission support."""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "nodes",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_nodes_deleted_at", "nodes", ["deleted_at"])


def downgrade():
    op.drop_index("idx_nodes_deleted_at", table_name="nodes")
    op.drop_column("nodes", "deleted_at")
```

Run migration:
```bash
source .venv/bin/activate && alembic upgrade head
```

Also run on the test DB:
```bash
TEST_DATABASE_URL=postgresql+psycopg://fleet:fleet@localhost:5432/fleet_test \
  alembic upgrade head
```

- [ ] **Step 3: Add deleted_at to Node model**

In `fleet_platform/models/node.py`:

```python
from datetime import datetime
# add after last_seen_at:
deleted_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=True), nullable=True, default=None, index=True
)
```

- [ ] **Step 4: Add DELETE endpoint and filter in nodes.py**

```python
from datetime import UTC, datetime

# Add to list_nodes query:
query = query.where(Node.deleted_at.is_(None))

# Add decommission endpoint:
@router.delete("/{node_id}", status_code=204)
async def decommission_node(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("admin")),
):
    result = await db.execute(
        select(Node).where(Node.id == node_id).where(Node.deleted_at.is_(None))
    )
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")
    node.deleted_at = datetime.now(UTC)
    await audit(db, actor=claims["email"], action="node.decommission",
                resource_type="node", resource_id=node.id,
                old_value={"hostname": node.hostname, "status": node.status})
    await db.commit()
```

- [ ] **Step 5: Filter deleted nodes from fleet overview**

In `fleet_platform/api/routes/fleet.py`, add `.where(Node.deleted_at.is_(None))` to the fleet overview count query.

In `fleet_platform/api/routes/fleet.py` node list (if it has one): same filter.

- [ ] **Step 6: Run tests**

```bash
source .venv/bin/activate && pytest tests/integration/test_nodes_api.py -v
```

Expected: all existing + 3 new pass.

- [ ] **Step 7: Commit**

```bash
git add fleet_platform/db/migrations/versions/003_node_soft_delete.py \
  fleet_platform/models/node.py fleet_platform/api/routes/nodes.py \
  fleet_platform/api/routes/fleet.py tests/integration/test_nodes_api.py
git commit -m "feat(M4): node soft-delete/decommission — DELETE /api/v1/nodes/:id, filter deleted from all lists"
```

---

## Task 3: Audit Log Read API

**Files:**
- Create: `fleet_platform/api/routes/audit_log.py`
- Modify: `fleet_platform/api/main.py`
- Create: `fleet_platform/schemas/audit.py`
- Test: `tests/integration/test_audit_api.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_audit_api.py
import pytest
from httpx import AsyncClient


async def test_admin_can_list_audit_events(admin_client: AsyncClient):
    r = await admin_client.get("/api/v1/audit")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert "total" in data


async def test_audit_filter_by_action(admin_client: AsyncClient):
    r = await admin_client.get("/api/v1/audit?action=auth.login")
    assert r.status_code == 200
    for item in r.json()["items"]:
        assert item["action"] == "auth.login"


async def test_audit_filter_by_resource_type(admin_client: AsyncClient):
    r = await admin_client.get("/api/v1/audit?resource_type=node")
    assert r.status_code == 200
    for item in r.json()["items"]:
        assert item["resource_type"] == "node"


async def test_viewer_cannot_read_audit(viewer_client: AsyncClient):
    r = await viewer_client.get("/api/v1/audit")
    assert r.status_code == 403
```

- [ ] **Step 2: Create audit schema**

```python
# fleet_platform/schemas/audit.py
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_at: datetime
    actor: str
    action: str
    resource_type: str | None
    resource_id: uuid.UUID | None
    ip_address: str | None
    new_value: dict | None
    old_value: dict | None
```

- [ ] **Step 3: Create audit_log router**

```python
# fleet_platform/api/routes/audit_log.py
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import require_role
from fleet_platform.models.audit import AuditEvent
from fleet_platform.schemas.audit import AuditEventResponse
from fleet_platform.schemas.common import PaginatedResponse

router = APIRouter(prefix="/api/v1/audit")


@router.get("", response_model=PaginatedResponse[AuditEventResponse])
async def list_audit_events(
    actor: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    from_dt: datetime | None = Query(default=None, alias="from"),
    to_dt: datetime | None = Query(default=None, alias="to"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("admin", "operator")),
):
    query = select(AuditEvent).order_by(AuditEvent.event_at.desc())

    if actor:
        query = query.where(AuditEvent.actor == actor)
    if action:
        query = query.where(AuditEvent.action == action)
    if resource_type:
        query = query.where(AuditEvent.resource_type == resource_type)
    if from_dt:
        query = query.where(AuditEvent.event_at >= from_dt)
    if to_dt:
        query = query.where(AuditEvent.event_at <= to_dt)

    total = (await db.execute(
        select(func.count()).select_from(query.subquery())
    )).scalar_one()

    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    events = result.scalars().all()

    return PaginatedResponse(
        items=[AuditEventResponse.model_validate(e) for e in events],
        total=total, page=page, per_page=per_page,
    )
```

- [ ] **Step 4: Register in main.py**

Add `audit_log` to imports and `app.include_router(audit_log.router, tags=["audit"])`.

- [ ] **Step 5: Run tests**

```bash
source .venv/bin/activate && pytest tests/integration/test_audit_api.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add fleet_platform/api/routes/audit_log.py fleet_platform/schemas/audit.py \
  fleet_platform/api/main.py tests/integration/test_audit_api.py
git commit -m "feat: audit log read API — GET /api/v1/audit with actor/action/resource/date filters"
```

---

## Task 4: Full Test Suite Verification

- [ ] **Step 1: Run migrations on test DB and full suite**

```bash
source .venv/bin/activate
alembic upgrade head  # ensure demo DB is current
python -m pytest tests/ -q --no-header 2>&1 | tail -5
```

Expected: `170+ passed, 0 failed`

- [ ] **Step 2: TypeScript check**

```bash
cd /home/dk/Documents/git/kri/frontend && npx tsc --noEmit
```

Expected: zero errors.

---

## Self-Review

- [x] M5: User management API (list, create, deactivate) — Task 1
- [x] M4: Node soft-delete / decommission with audit trail — Task 2
- [x] Audit log read API with filters — Task 3
- [ ] Not included: M3 alerting (webhook) — separate concern, Plan 10
- [ ] Not included: multi-tenancy / scoped RBAC — explicitly out of scope
