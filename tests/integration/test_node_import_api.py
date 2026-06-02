# tests/integration/test_node_import_api.py
"""Integration tests for bulk node import endpoints (#360).

POST /api/v1/fleet/nodes/import/validate
POST /api/v1/fleet/nodes/import/commit
"""
import secrets
from datetime import UTC, datetime

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fleet_platform.core.auth import create_access_token, hash_password
from fleet_platform.core.config import settings
from fleet_platform.models import Base, User
from fleet_platform.models.group import Group, GroupMember
from fleet_platform.models.node import Node

# ─── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def test_engine():
    engine = create_async_engine(settings.test_database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def db_session(test_engine):
    TestSession = async_sessionmaker(test_engine, expire_on_commit=False)
    async with TestSession() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def app_with_test_db(test_engine):
    from unittest.mock import AsyncMock

    from slowapi import Limiter
    from slowapi.util import get_remote_address

    import fleet_platform.api.limiter as limiter_module

    test_limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")
    limiter_module.limiter = test_limiter

    from fleet_platform.api import deps
    from fleet_platform.api.main import create_app

    app = create_app()
    app.state.limiter = test_limiter
    TestSession = async_sessionmaker(test_engine, expire_on_commit=False)

    async def override_get_db():
        async with TestSession() as session:
            yield session

    mock_redis = AsyncMock()
    mock_redis.get.return_value = None
    mock_redis.setex = AsyncMock()

    async def override_get_redis():
        return mock_redis

    app.dependency_overrides[deps.get_db] = override_get_db
    app.dependency_overrides[deps.get_redis] = override_get_redis
    return app


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def operator_user(db_session: AsyncSession):
    user = User(
        email="bulk-import-op@fleet.local",
        password_hash=hash_password("op123"),
        role="operator",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    yield user
    await db_session.delete(user)
    await db_session.commit()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def viewer_user(db_session: AsyncSession):
    user = User(
        email="bulk-import-viewer@fleet.local",
        password_hash=hash_password("view123"),
        role="viewer",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    yield user
    await db_session.delete(user)
    await db_session.commit()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def operator_client(app_with_test_db, operator_user: User):
    token = create_access_token(
        user_id=str(operator_user.id),
        email=operator_user.email,
        role=operator_user.role,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app_with_test_db),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"},
    ) as ac:
        yield ac


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def viewer_client(app_with_test_db, viewer_user: User):
    token = create_access_token(
        user_id=str(viewer_user.id),
        email=viewer_user.email,
        role=viewer_user.role,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app_with_test_db),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {token}"},
    ) as ac:
        yield ac


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def existing_node(db_session: AsyncSession):
    """A node already in the DB to test duplicate detection."""
    node = Node(
        minion_id="bulk-import-existing.local",
        hostname="bulk-import-existing",
        ip_address="10.99.99.1",
        node_token_hash=hash_password(secrets.token_urlsafe(32)),
        first_seen_at=datetime.now(UTC),
        status="online",
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)
    yield node
    await db_session.delete(node)
    await db_session.commit()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def test_group(db_session: AsyncSession):
    """A group to test GroupMember creation on commit."""
    group = Group(
        name="bulk-import-test-group",
        type="static",
    )
    db_session.add(group)
    await db_session.commit()
    await db_session.refresh(group)
    yield group
    await db_session.delete(group)
    await db_session.commit()


# ─── Validate endpoint ─────────────────────────────────────────────────────────


async def test_validate_paste_classifies_new(operator_client: AsyncClient, existing_node: Node):
    """Validate endpoint returns 'new' for unknown nodes and 'duplicate' for existing ones."""
    payload = {
        "source": "paste",
        "text": "brand-new-node-1.local,192.168.200.1\nbulk-import-existing.local,10.0.0.99",
    }
    resp = await operator_client.post("/api/v1/fleet/nodes/import/validate", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "rows" in data
    assert "summary" in data

    statuses = {r["minion_id"]: r["status"] for r in data["rows"]}
    assert statuses["brand-new-node-1.local"] == "new"
    assert statuses["bulk-import-existing.local"] == "duplicate"


async def test_validate_paste_classifies_duplicate_ip(operator_client: AsyncClient, existing_node: Node):
    """Validate detects a new minion_id but an already-used IP as duplicate."""
    payload = {
        "source": "paste",
        "text": f"fresh-node-zz,{existing_node.ip_address}",
    }
    resp = await operator_client.post("/api/v1/fleet/nodes/import/validate", json=payload)
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    assert rows[0]["status"] == "duplicate"
    assert "IP" in rows[0]["reason"]


async def test_validate_csv_source(operator_client: AsyncClient):
    """Validate endpoint works with CSV source."""
    csv_content = "minion_id,hostname,ip\nnew-csv-node-1,new-csv-node-1.local,10.200.1.1"
    payload = {"source": "csv", "csv_content": csv_content}
    resp = await operator_client.post("/api/v1/fleet/nodes/import/validate", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["summary"]["new"] == 1
    assert data["summary"]["total"] == 1


async def test_validate_invalid_ip_detected(operator_client: AsyncClient):
    """Validate endpoint marks rows with invalid IPs as 'invalid'."""
    payload = {
        "source": "paste",
        "text": "bad-ip-node,not-an-ip-address",
    }
    resp = await operator_client.post("/api/v1/fleet/nodes/import/validate", json=payload)
    assert resp.status_code == 200, resp.text
    rows = resp.json()["rows"]
    assert rows[0]["status"] == "invalid"


async def test_validate_unknown_source_rejected(operator_client: AsyncClient):
    """Validate endpoint returns 400 for unknown source type."""
    payload = {"source": "cidr"}
    resp = await operator_client.post("/api/v1/fleet/nodes/import/validate", json=payload)
    assert resp.status_code == 400


async def test_validate_requires_auth(viewer_client: AsyncClient):
    """Viewer role cannot call the validate endpoint — 403 expected."""
    payload = {"source": "paste", "text": "192.168.1.1"}
    resp = await viewer_client.post("/api/v1/fleet/nodes/import/validate", json=payload)
    assert resp.status_code == 403


async def test_validate_summary_counts(operator_client: AsyncClient, existing_node: Node):
    """Summary dict from validate has correct counts across statuses."""
    payload = {
        "source": "paste",
        "text": (
            "valid-fresh-node-a,10.201.1.1\n"  # new
            "bulk-import-existing.local,10.0.0.5\n"  # duplicate (minion_id clash)
            "bad-node!,not-an-ip\n"  # invalid
        ),
    }
    resp = await operator_client.post("/api/v1/fleet/nodes/import/validate", json=payload)
    assert resp.status_code == 200, resp.text
    summary = resp.json()["summary"]
    assert summary["new"] == 1
    assert summary["duplicate"] == 1
    assert summary["invalid"] == 1
    assert summary["total"] == 3


# ─── Commit endpoint ───────────────────────────────────────────────────────────


async def test_commit_creates_new_nodes(operator_client: AsyncClient, db_session: AsyncSession):
    """Commit endpoint persists rows with status='new' and returns their IDs."""
    rows = [
        {"minion_id": "commit-test-node-1.local", "hostname": "commit-test-node-1", "ip": "10.202.0.1", "status": "new", "reason": ""},
        {"minion_id": "commit-test-node-2.local", "hostname": "commit-test-node-2", "ip": "10.202.0.2", "status": "new", "reason": ""},
    ]
    resp = await operator_client.post(
        "/api/v1/fleet/nodes/import/commit",
        json={"rows": rows},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["created"] == 2
    assert data["skipped"] == 0
    assert len(data["node_ids"]) == 2


async def test_commit_skips_non_new_rows(operator_client: AsyncClient):
    """Commit endpoint skips rows not marked 'new' and reports them as skipped."""
    rows = [
        {"minion_id": "commit-node-new", "hostname": "commit-node-new", "ip": "10.203.0.1", "status": "new", "reason": ""},
        {"minion_id": "commit-node-dup", "hostname": "commit-node-dup", "ip": "10.203.0.2", "status": "duplicate", "reason": "already exists"},
        {"minion_id": "commit-node-bad", "hostname": "commit-node-bad", "ip": "bad-ip", "status": "invalid", "reason": "invalid IP"},
    ]
    resp = await operator_client.post(
        "/api/v1/fleet/nodes/import/commit",
        json={"rows": rows},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["created"] == 1
    assert data["skipped"] == 2


async def test_commit_with_group_id_adds_members(
    operator_client: AsyncClient,
    test_group: Group,
    db_session: AsyncSession,
    test_engine,
):
    """Commit with group_id creates GroupMember rows for each created node."""
    rows = [
        {"minion_id": "commit-group-node-1", "hostname": "commit-group-node-1", "ip": "10.204.0.1", "status": "new", "reason": ""},
    ]
    resp = await operator_client.post(
        "/api/v1/fleet/nodes/import/commit",
        json={"rows": rows, "group_id": str(test_group.id)},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["created"] == 1

    # Verify GroupMember was created in the DB
    import uuid

    from sqlalchemy import select as sa_select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    TestSession = async_sessionmaker(test_engine, expire_on_commit=False)
    async with TestSession() as session:
        result = await session.execute(
            sa_select(GroupMember).where(GroupMember.group_id == test_group.id)
        )
        members = result.scalars().all()

    assert len(members) >= 1
    node_id = uuid.UUID(data["node_ids"][0])
    member_node_ids = [m.node_id for m in members]
    assert node_id in member_node_ids


async def test_commit_requires_auth(viewer_client: AsyncClient):
    """Viewer role cannot call the commit endpoint — 403 expected."""
    rows = [{"minion_id": "x", "status": "new", "reason": ""}]
    resp = await viewer_client.post("/api/v1/fleet/nodes/import/commit", json={"rows": rows})
    assert resp.status_code == 403
