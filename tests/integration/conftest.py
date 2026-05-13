# tests/integration/conftest.py
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fleet_platform.core.auth import create_access_token, hash_password
from fleet_platform.core.config import settings
from fleet_platform.models import Base, User


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
    from fleet_platform.api.main import create_app
    from fleet_platform.api import deps

    app = create_app()
    TestSession = async_sessionmaker(test_engine, expire_on_commit=False)

    async def override_get_db():
        async with TestSession() as session:
            yield session

    app.dependency_overrides[deps.get_db] = override_get_db
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
