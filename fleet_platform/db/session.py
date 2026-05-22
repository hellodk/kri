from collections.abc import AsyncGenerator, Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from fleet_platform.core.config import settings

# ── Async engine — used by FastAPI request handlers ──────────────────
_DB_OPTS = {"options": "-c timescaledb.telemetry_level=off"}

engine = create_async_engine(
    settings.database_url,
    echo=settings.is_development,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_pre_ping=True,
    connect_args=_DB_OPTS,
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
    connect_args=_DB_OPTS,
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
