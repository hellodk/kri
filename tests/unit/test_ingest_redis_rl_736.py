"""Unit tests for #736 (Redis client reuse) and #737 (atomic INCR+EXPIRE).

Updated for #747: _check_ingest_rate_limit is now async and uses the shared
aioredis singleton from deps.get_redis() instead of a per-module sync client.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import fleet_platform.api.routes.ingest as _ingest_mod


def _make_redis_mock(count: int = 1) -> tuple:
    """Return (mock_redis, mock_pipe).

    redis.asyncio.Redis.pipeline() is synchronous; only execute() is awaitable.
    """
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[count, True])
    mock_redis = MagicMock()
    mock_redis.pipeline.return_value = mock_pipe
    return mock_redis, mock_pipe


@pytest.mark.asyncio
async def test_rate_limit_uses_get_redis_singleton():
    """#747: multiple rate-limit calls must use the shared get_redis() client."""
    mock_redis, _ = _make_redis_mock(1)
    mock_get_redis = AsyncMock(return_value=mock_redis)

    with patch.object(_ingest_mod, "get_redis", mock_get_redis):
        await _ingest_mod._check_ingest_rate_limit("node-1")
        await _ingest_mod._check_ingest_rate_limit("node-2")
        await _ingest_mod._check_ingest_rate_limit("node-3")

    assert mock_get_redis.await_count == 3


@pytest.mark.asyncio
async def test_rate_limit_uses_pipeline_for_atomic_incr_expire():
    """#737: INCR and EXPIRE must be issued together via a Redis pipeline."""
    mock_redis, mock_pipe = _make_redis_mock(1)

    with patch.object(_ingest_mod, "get_redis", AsyncMock(return_value=mock_redis)):
        allowed = await _ingest_mod._check_ingest_rate_limit("node-abc")

    mock_redis.pipeline.assert_called_once()
    mock_pipe.incr.assert_called_once_with("ingest_rl:node-abc")
    mock_pipe.expire.assert_called_once_with("ingest_rl:node-abc", _ingest_mod._INGEST_RATE_WINDOW)
    mock_pipe.execute.assert_awaited_once()
    assert allowed is True


@pytest.mark.asyncio
async def test_rate_limit_denied_when_count_exceeds_limit():
    mock_redis, _ = _make_redis_mock(11)

    with patch.object(_ingest_mod, "get_redis", AsyncMock(return_value=mock_redis)):
        allowed = await _ingest_mod._check_ingest_rate_limit("node-hot")

    assert allowed is False


@pytest.mark.asyncio
async def test_rate_limit_fails_closed_on_redis_error():
    """#768: Redis failure must raise 503, not silently allow the request through."""
    from fastapi import HTTPException

    with patch.object(_ingest_mod, "get_redis", AsyncMock(side_effect=Exception("redis down"))):
        with pytest.raises(HTTPException) as exc_info:
            await _ingest_mod._check_ingest_rate_limit("node-y")
    assert exc_info.value.status_code == 503
