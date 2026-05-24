import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fleet_platform.core.auth import hash_password
from fleet_platform.core.config import settings
from fleet_platform.models import Base, User


class _FakeRedis:
    """Simple in-memory Redis stand-in that tracks setex/exists state."""

    def __init__(self):
        self._store: dict[str, str] = {}

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self._store[key] = value

    async def exists(self, key: str) -> int:
        return 1 if key in self._store else 0

    async def get(self, key: str):
        return self._store.get(key)

    def reset(self):
        self._store.clear()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def test_engine():
    engine = create_async_engine(settings.test_database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(loop_scope="module")
async def db_session(test_engine):
    TestSession = async_sessionmaker(test_engine, expire_on_commit=False)
    async with TestSession() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(loop_scope="module")
async def test_user(db_session: AsyncSession):
    user = User(
        email="test@fleet.local",
        password_hash=hash_password("password123"),
        role="operator",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    yield user
    await db_session.delete(user)
    await db_session.commit()


@pytest.fixture(scope="module")
def auth_fake_redis() -> _FakeRedis:
    """Module-scoped stateful Redis stand-in shared across auth tests."""
    return _FakeRedis()


@pytest_asyncio.fixture(loop_scope="module")
async def auth_client(test_engine, auth_fake_redis: _FakeRedis):
    from slowapi import Limiter
    from slowapi.util import get_remote_address
    import fleet_platform.api.limiter as limiter_module

    test_limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")
    limiter_module.limiter = test_limiter

    from fleet_platform.api.main import create_app
    from fleet_platform.api import deps

    app = create_app()
    app.state.limiter = test_limiter
    TestSession = async_sessionmaker(test_engine, expire_on_commit=False)

    async def override_get_db():
        async with TestSession() as session:
            yield session

    async def override_get_redis():
        return auth_fake_redis

    app.dependency_overrides[deps.get_db] = override_get_db
    app.dependency_overrides[deps.get_redis] = override_get_redis

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as ac:
        yield ac


async def test_login_success(auth_client, test_user):
    response = await auth_client.post("/auth/login", json={
        "email": "test@fleet.local",
        "password": "password123",
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"


async def test_login_wrong_password(auth_client, test_user):
    response = await auth_client.post("/auth/login", json={
        "email": "test@fleet.local",
        "password": "wrongpassword",
    })
    assert response.status_code == 401


async def test_login_unknown_email(auth_client):
    response = await auth_client.post("/auth/login", json={
        "email": "nobody@fleet.local",
        "password": "password123",
    })
    assert response.status_code == 401


async def test_refresh_token(auth_client, test_user):
    login = await auth_client.post("/auth/login", json={
        "email": "test@fleet.local",
        "password": "password123",
    })
    refresh_token = login.json()["refresh_token"]
    response = await auth_client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    assert "access_token" in response.json()


async def test_protected_endpoint_without_token(auth_client):
    response = await auth_client.get("/auth/me")
    assert response.status_code == 401


async def test_protected_endpoint_with_valid_token(auth_client, test_user):
    login = await auth_client.post("/auth/login", json={
        "email": "test@fleet.local",
        "password": "password123",
    })
    token = login.json()["access_token"]
    response = await auth_client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@fleet.local"
    assert data["role"] == "operator"


async def test_logout_revokes_refresh_token(auth_client, auth_fake_redis: _FakeRedis, test_user):
    """After logout with refresh_token, the refresh token must be rejected."""
    auth_fake_redis.reset()
    r = await auth_client.post("/auth/login", json={"email": "test@fleet.local", "password": "password123"})
    tokens = r.json()
    access = tokens["access_token"]
    refresh = tokens["refresh_token"]

    lo = await auth_client.post(
        "/auth/logout",
        json={"refresh_token": refresh},
        headers={"Authorization": f"Bearer {access}"},
    )
    assert lo.status_code == 204

    r2 = await auth_client.post("/auth/refresh", json={"refresh_token": refresh})
    assert r2.status_code == 401


async def test_refresh_rotates_tokens(auth_client, auth_fake_redis: _FakeRedis, test_user):
    """Using a refresh token issues new access + new refresh; old refresh is revoked."""
    auth_fake_redis.reset()
    r = await auth_client.post("/auth/login", json={"email": "test@fleet.local", "password": "password123"})
    tokens = r.json()
    old_refresh = tokens["refresh_token"]

    r2 = await auth_client.post("/auth/refresh", json={"refresh_token": old_refresh})
    assert r2.status_code == 200
    new_tokens = r2.json()
    assert "access_token" in new_tokens
    assert "refresh_token" in new_tokens
    assert new_tokens["refresh_token"] != old_refresh

    # Old refresh must now be rejected
    r3 = await auth_client.post("/auth/refresh", json={"refresh_token": old_refresh})
    assert r3.status_code == 401


async def test_logout_without_refresh_token_still_succeeds(auth_client, auth_fake_redis: _FakeRedis, test_user):
    """Logout with no refresh_token body still returns 204."""
    auth_fake_redis.reset()
    r = await auth_client.post("/auth/login", json={"email": "test@fleet.local", "password": "password123"})
    access = r.json()["access_token"]
    lo = await auth_client.post("/auth/logout", headers={"Authorization": f"Bearer {access}"})
    assert lo.status_code == 204
