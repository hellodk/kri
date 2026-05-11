import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from platform.core.auth import hash_password
from platform.core.config import settings
from platform.models import Base, User


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


@pytest_asyncio.fixture(loop_scope="module")
async def auth_client(test_engine):
    from platform.api.main import create_app
    from platform.api import deps

    app = create_app()
    TestSession = async_sessionmaker(test_engine, expire_on_commit=False)

    async def override_get_db():
        async with TestSession() as session:
            yield session

    app.dependency_overrides[deps.get_db] = override_get_db

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
