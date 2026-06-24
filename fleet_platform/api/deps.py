from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

# Redis client lifecycle now lives in fleet_platform.core.redis so that the service
# layer can use the shared client without importing the API layer (#746 / ARC-2).
# init_redis() configures the client with health_check_interval=30. Re-exported here
# for backward compatibility — existing imports of get_redis/init_redis/close_redis
# from this module (and FastAPI dependency_overrides keyed on deps.get_redis) keep
# working because they reference the very same objects.
from fleet_platform.core.redis import close_redis, get_redis, init_redis
from fleet_platform.db.session import AsyncSessionLocal

__all__ = ["get_db", "get_redis", "init_redis", "close_redis"]


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
