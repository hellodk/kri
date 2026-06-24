"""Shared async Redis client lifecycle.

Lives in ``core`` so that BOTH the API layer and the service/worker layers can
depend on it without anyone having to import ``fleet_platform.api`` (#746 / ARC-2:
the service layer must not import from the API layer). ``api.deps`` re-exports
these names for backward compatibility.
"""

from __future__ import annotations

import redis.asyncio as aioredis

from fleet_platform.core.config import settings

_redis_client: aioredis.Redis | None = None


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
