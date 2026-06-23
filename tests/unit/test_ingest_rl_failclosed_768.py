"""Unit tests for #768 — ingest rate limiter must fail CLOSED on Redis failure.

The previous behaviour was to return True (allow) when Redis was unavailable.
After the fix, a Redis error on the ingest path must result in a 503 Service
Unavailable rather than allowing the request through unchecked.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

MODULE = "fleet_platform.api.routes.ingest"


@pytest.fixture(autouse=True)
def reset_ingest_redis_client():
    import fleet_platform.api.routes.ingest as ingest_mod

    ingest_mod._ingest_redis_client = None
    yield
    ingest_mod._ingest_redis_client = None


# ---------------------------------------------------------------------------
# Fail-closed: Redis connection failure → 503, not allow-through
# ---------------------------------------------------------------------------


def test_redis_connection_failure_raises_503():
    """If Redis is unreachable, _check_ingest_rate_limit must raise HTTP 503."""
    with patch(f"{MODULE}.sync_redis.Redis.from_url", side_effect=Exception("redis down")):
        from fleet_platform.api.routes.ingest import _check_ingest_rate_limit

        with pytest.raises(HTTPException) as exc_info:
            _check_ingest_rate_limit("node-offline")

    assert exc_info.value.status_code == 503


def test_redis_pipeline_failure_raises_503():
    """If Redis pipeline.execute() raises, _check_ingest_rate_limit must raise 503."""
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_pipe.execute.side_effect = Exception("pipeline broken")
    mock_redis.pipeline.return_value = mock_pipe

    with patch(f"{MODULE}.sync_redis.Redis.from_url", return_value=mock_redis):
        from fleet_platform.api.routes.ingest import _check_ingest_rate_limit

        with pytest.raises(HTTPException) as exc_info:
            _check_ingest_rate_limit("node-pipe-fail")

    assert exc_info.value.status_code == 503


def test_normal_allow_still_works():
    """Happy-path: within limit → True (allow)."""
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_pipe.execute.return_value = [1, True]
    mock_redis.pipeline.return_value = mock_pipe

    with patch(f"{MODULE}.sync_redis.Redis.from_url", return_value=mock_redis):
        from fleet_platform.api.routes.ingest import _check_ingest_rate_limit

        assert _check_ingest_rate_limit("node-ok") is True


def test_normal_deny_still_works():
    """Happy-path: over limit → False (deny)."""
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_pipe.execute.return_value = [999, True]
    mock_redis.pipeline.return_value = mock_pipe

    with patch(f"{MODULE}.sync_redis.Redis.from_url", return_value=mock_redis):
        from fleet_platform.api.routes.ingest import _check_ingest_rate_limit

        assert _check_ingest_rate_limit("node-over") is False


def test_503_detail_mentions_rate_limit_service():
    """The 503 response should give operators a clue why ingest was rejected."""
    with patch(f"{MODULE}.sync_redis.Redis.from_url", side_effect=ConnectionError("refused")):
        from fleet_platform.api.routes.ingest import _check_ingest_rate_limit

        with pytest.raises(HTTPException) as exc_info:
            _check_ingest_rate_limit("node-detail")

    detail = str(exc_info.value.detail).lower()
    assert "rate" in detail or "redis" in detail or "unavailable" in detail
