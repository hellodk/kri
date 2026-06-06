# tests/integration/conftest.py
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fleet_platform.core.auth import create_access_token, hash_password
from fleet_platform.core.config import settings
from fleet_platform.models import Base, User


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def test_engine():
    engine = create_async_engine(settings.test_database_url, echo=False)
    async with engine.begin() as conn:
        # Ensure required extensions are present (pg_trgm for search, vector,
        # timescaledb).  CREATE EXTENSION IF NOT EXISTS is idempotent.
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        # Use CASCADE to handle FK dependencies between tables that were
        # created by alembic migrations (e.g. ssh_sessions → groups) but are
        # not represented in Base.metadata.  Without CASCADE the drop_all
        # call fails when the DB was previously initialised by migrations.
        await conn.execute(
            text(
                "DO $$ DECLARE r RECORD; BEGIN "
                "FOR r IN SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' LOOP "
                "EXECUTE 'DROP TABLE IF EXISTS public.' || quote_ident(r.tablename) || ' CASCADE'; "
                "END LOOP; END $$"
            )
        )
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

    # Use in-memory rate limiter for tests to avoid 429 false positives
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
    app._test_mock_redis = mock_redis  # expose for tests that need to configure it
    return app


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def client(app_with_test_db):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_test_db),
        base_url="http://testserver",
    ) as ac:
        yield ac


@pytest_asyncio.fixture(scope="module", loop_scope="module")
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


@pytest_asyncio.fixture(scope="module", loop_scope="module")
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


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def admin_token(admin_user: User) -> str:
    return create_access_token(
        user_id=str(admin_user.id),
        email=admin_user.email,
        role=admin_user.role,
    )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def viewer_token(viewer_user: User) -> str:
    return create_access_token(
        user_id=str(viewer_user.id),
        email=viewer_user.email,
        role=viewer_user.role,
    )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def admin_client(app_with_test_db, admin_token: str):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_test_db),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {admin_token}"},
    ) as ac:
        yield ac


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def viewer_client(app_with_test_db, viewer_token: str):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_test_db),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {viewer_token}"},
    ) as ac:
        yield ac


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def operator_user(db_session: AsyncSession):
    user = User(
        email="operator-test@fleet.local",
        password_hash=hash_password("operator123"),
        role="operator",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    yield user
    await db_session.delete(user)
    await db_session.commit()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def operator_token(operator_user: User) -> str:
    return create_access_token(
        user_id=str(operator_user.id),
        email=operator_user.email,
        role=operator_user.role,
    )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def operator_client(app_with_test_db, operator_token: str):
    async with AsyncClient(
        transport=ASGITransport(app=app_with_test_db),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {operator_token}"},
    ) as ac:
        yield ac
