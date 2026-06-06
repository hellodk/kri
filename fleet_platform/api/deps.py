from collections.abc import AsyncGenerator

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.core.config import settings
from fleet_platform.db.session import AsyncSessionLocal

_redis_client: aioredis.Redis | None = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_redis() -> None:
    global _redis_client
    _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True, health_check_interval=30)


async def close_redis() -> None:
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True, health_check_interval=30)
    return _redis_client
