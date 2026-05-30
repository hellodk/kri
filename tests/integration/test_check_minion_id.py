"""Unit tests for GET /api/v1/fleet/nodes/check-minion-id"""
import secrets
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fleet_platform.core.auth import create_access_token, hash_password
from fleet_platform.core.config import settings
from fleet_platform.models import Base, User
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
async def admin_user(db_session: AsyncSession):
    user = User(
        email="admin-check-mid@fleet.local",
        password_hash=hash_password("admin123"),
        role="admin",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    yield user
    await db_session.delete(user)
    await db_session.commit()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def auth_headers(admin_user: User) -> dict[str, str]:
    token = create_access_token(
        user_id=str(admin_user.id),
        email=admin_user.email,
        role=admin_user.role,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def existing_node(db_session: AsyncSession):
    """A node already registered in the database."""
    node = Node(
        minion_id="check-mid-existing.local",
        hostname="check-mid-existing",
        node_token_hash=hash_password(secrets.token_urlsafe(32)),
        first_seen_at=datetime.now(UTC),
        status="online",
        bootstrap_status="bootstrapped",
    )
    db_session.add(node)
    await db_session.commit()
    await db_session.refresh(node)
    yield node
    await db_session.delete(node)
    await db_session.commit()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def admin_client(app_with_test_db, auth_headers: dict[str, str]):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_test_db),
        base_url="http://testserver",
        headers=auth_headers,
    ) as ac:
        yield ac


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def anon_client(app_with_test_db):
    """Client with no authentication headers."""
    async with AsyncClient(
        transport=ASGITransport(app=app_with_test_db),
        base_url="http://testserver",
    ) as ac:
        yield ac


# ─── Tests ─────────────────────────────────────────────────────────────────────


async def test_available_minion_id(admin_client: AsyncClient):
    """A minion_id not in the DB returns available=True."""
    response = await admin_client.get(
        "/api/v1/fleet/nodes/check-minion-id",
        params={"id": "brand-new-node.local"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["available"] is True
    assert data["existing_node"] is None


async def test_taken_minion_id(admin_client: AsyncClient, existing_node: Node):
    """A minion_id already in the DB returns available=False with node summary."""
    response = await admin_client.get(
        "/api/v1/fleet/nodes/check-minion-id",
        params={"id": existing_node.minion_id},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["available"] is False
    node_summary = data["existing_node"]
    assert node_summary is not None
    assert node_summary["id"] == str(existing_node.id)
    assert node_summary["hostname"] == existing_node.hostname
    assert node_summary["status"] == existing_node.status
    assert node_summary["bootstrap_status"] == existing_node.bootstrap_status


async def test_invalid_format_rejected(admin_client: AsyncClient):
    """A minion_id with invalid chars (spaces, slashes) returns 422."""
    for bad_id in ["has space", "has/slash", "has@at", "has#hash"]:
        response = await admin_client.get(
            "/api/v1/fleet/nodes/check-minion-id",
            params={"id": bad_id},
        )
        assert response.status_code == 422, (
            f"Expected 422 for {bad_id!r}, got {response.status_code}"
        )
        detail = response.json()["detail"]
        assert "minion_id" in detail.lower() or "invalid" in detail.lower()


async def test_requires_auth(anon_client: AsyncClient):
    """Unauthenticated request returns 401."""
    response = await anon_client.get(
        "/api/v1/fleet/nodes/check-minion-id",
        params={"id": "some-node"},
    )
    assert response.status_code == 401


async def test_missing_id_query_param_rejected(admin_client: AsyncClient):
    """Omitting the 'id' query parameter entirely returns 422."""
    response = await admin_client.get("/api/v1/fleet/nodes/check-minion-id")
    assert response.status_code == 422


async def test_valid_id_formats_accepted(admin_client: AsyncClient):
    """IDs using all valid character classes are accepted (available=True when not in DB)."""
    valid_ids = [
        "mac-mini-01",
        "node.local",
        "mac_mini_01",
        "NODE123",
        "a",
        "a-b.c_d",
    ]
    for mid in valid_ids:
        response = await admin_client.get(
            "/api/v1/fleet/nodes/check-minion-id",
            params={"id": mid},
        )
        assert response.status_code == 200, (
            f"Expected 200 for {mid!r}, got {response.status_code}: {response.text}"
        )
        assert response.json()["available"] is True
