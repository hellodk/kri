"""Unit tests for #768 — ingest rate limiter must fail CLOSED on Redis failure.

Updated for #747: _check_ingest_rate_limit is now async and uses the shared
aioredis singleton from deps.get_redis() instead of a per-module sync client.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

import fleet_platform.api.routes.ingest as _ingest_mod


def _make_redis_mock(count: int = 1) -> tuple:
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(return_value=[count, True])
    mock_redis = MagicMock()
    mock_redis.pipeline.return_value = mock_pipe
    return mock_redis, mock_pipe


# ---------------------------------------------------------------------------
# Fail-closed: Redis connection failure → 503, not allow-through
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_connection_failure_raises_503():
    """If Redis is unreachable, _check_ingest_rate_limit must raise HTTP 503."""
    with patch.object(_ingest_mod, "get_redis", AsyncMock(side_effect=Exception("redis down"))):
        with pytest.raises(HTTPException) as exc_info:
            await _ingest_mod._check_ingest_rate_limit("node-offline")

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_redis_pipeline_failure_raises_503():
    """If Redis pipeline.execute() raises, _check_ingest_rate_limit must raise 503."""
    mock_pipe = MagicMock()
    mock_pipe.execute = AsyncMock(side_effect=Exception("pipeline broken"))
    mock_redis = MagicMock()
    mock_redis.pipeline.return_value = mock_pipe

    with patch.object(_ingest_mod, "get_redis", AsyncMock(return_value=mock_redis)):
        with pytest.raises(HTTPException) as exc_info:
            await _ingest_mod._check_ingest_rate_limit("node-pipe-fail")

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_normal_allow_still_works():
    """Happy-path: within limit → True (allow)."""
    mock_redis, _ = _make_redis_mock(1)

    with patch.object(_ingest_mod, "get_redis", AsyncMock(return_value=mock_redis)):
        assert await _ingest_mod._check_ingest_rate_limit("node-ok") is True


@pytest.mark.asyncio
async def test_normal_deny_still_works():
    """Happy-path: over limit → False (deny)."""
    mock_redis, _ = _make_redis_mock(999)

    with patch.object(_ingest_mod, "get_redis", AsyncMock(return_value=mock_redis)):
        assert await _ingest_mod._check_ingest_rate_limit("node-over") is False


@pytest.mark.asyncio
async def test_503_detail_mentions_rate_limit_service():
    """The 503 response should give operators a clue why ingest was rejected."""
    with patch.object(_ingest_mod, "get_redis", AsyncMock(side_effect=ConnectionError("refused"))):
        with pytest.raises(HTTPException) as exc_info:
            await _ingest_mod._check_ingest_rate_limit("node-detail")

    detail = str(exc_info.value.detail).lower()
    assert "rate" in detail or "redis" in detail or "unavailable" in detail
