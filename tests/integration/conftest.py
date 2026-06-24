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
    from unittest.mock import AsyncMock, MagicMock

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
    # Pipeline is synchronous in redis.asyncio (only execute() is awaited).
    # Ingest rate-limiting (#747) uses incr/expire via a pipeline, so return a
    # sync pipeline mock whose execute() resolves to a low count (allowed).
    _mock_pipe = MagicMock()
    _mock_pipe.incr.return_value = _mock_pipe
    _mock_pipe.expire.return_value = _mock_pipe
    _mock_pipe.execute = AsyncMock(return_value=[1, True])
    mock_redis.pipeline = MagicMock(return_value=_mock_pipe)

    async def override_get_redis():
        return mock_redis

    app.dependency_overrides[deps.get_db] = override_get_db
    app.dependency_overrides[deps.get_redis] = override_get_redis
    app._test_mock_redis = mock_redis  # expose for tests that need to configure it
    return app


# ---------------------------------------------------------------------------
# Per-test transaction isolation (#805)
#
# Each test runs inside a raw connection with an outer transaction that is
# rolled back unconditionally in teardown.  The app's get_db override is
# temporarily replaced with one that creates sessions bound to that same
# connection using join_transaction_mode="create_savepoint" so that:
#   • session.commit() inside a route releases the savepoint and opens a new
#     one, but does NOT flush changes to the outer transaction on disk.
#   • The outer conn.rollback() at the end of each test discards all writes.
#
# Module-scoped user fixtures commit their rows before this fixture runs for
# the first test in the module, so those rows remain visible throughout the
# module and are cleaned up by the user fixtures' own teardown.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(autouse=True, loop_scope="module")
async def _per_test_db_savepoint(test_engine, app_with_test_db):
    """Roll back every test's DB writes via an outer connection-level transaction."""
    from fleet_platform.api import deps

    conn = await test_engine.connect()
    await conn.begin()

    # Replace get_db with one that always yields a session bound to our
    # connection; create_savepoint ensures commit() is a no-op on the outer tx.
    original_override = app_with_test_db.dependency_overrides.get(deps.get_db)

    async def _get_db_isolated():
        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()

    app_with_test_db.dependency_overrides[deps.get_db] = _get_db_isolated

    yield  # test executes here

    # Restore the module-level override before rolling back so the next test
    # gets a fresh isolated session rather than the closed connection above.
    if original_override is not None:
        app_with_test_db.dependency_overrides[deps.get_db] = original_override

    await conn.rollback()
    await conn.close()


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
