"""Unit tests for #736 (Redis client reuse) and #737 (atomic INCR+EXPIRE)."""

from unittest.mock import MagicMock, patch

import pytest

MODULE = "fleet_platform.api.routes.ingest"


@pytest.fixture(autouse=True)
def reset_ingest_redis_client():
    import fleet_platform.api.routes.ingest as ingest_mod

    ingest_mod._ingest_redis_client = None
    yield
    ingest_mod._ingest_redis_client = None


def test_rate_limit_reuses_single_redis_client():
    """#736: multiple limiter calls must not create a new Redis client each time."""
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_pipe.execute.return_value = [1, True]
    mock_redis.pipeline.return_value = mock_pipe

    with patch(f"{MODULE}.sync_redis.Redis.from_url", return_value=mock_redis) as from_url:
        from fleet_platform.api.routes.ingest import _check_ingest_rate_limit

        _check_ingest_rate_limit("node-1")
        _check_ingest_rate_limit("node-2")
        _check_ingest_rate_limit("node-3")

    from_url.assert_called_once()


def test_rate_limit_uses_pipeline_for_atomic_incr_expire():
    """#737: INCR and EXPIRE must be issued together via a Redis pipeline."""
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_pipe.execute.return_value = [1, True]
    mock_redis.pipeline.return_value = mock_pipe

    with patch(f"{MODULE}.sync_redis.Redis.from_url", return_value=mock_redis):
        from fleet_platform.api.routes.ingest import _INGEST_RATE_WINDOW, _check_ingest_rate_limit

        allowed = _check_ingest_rate_limit("node-abc")

    mock_redis.pipeline.assert_called_once()
    mock_pipe.incr.assert_called_once_with("ingest_rl:node-abc")
    mock_pipe.expire.assert_called_once_with("ingest_rl:node-abc", _INGEST_RATE_WINDOW)
    mock_pipe.execute.assert_called_once()
    assert allowed is True


def test_rate_limit_denied_when_count_exceeds_limit():
    mock_redis = MagicMock()
    mock_pipe = MagicMock()
    mock_pipe.execute.return_value = [11, True]
    mock_redis.pipeline.return_value = mock_pipe

    with patch(f"{MODULE}.sync_redis.Redis.from_url", return_value=mock_redis):
        from fleet_platform.api.routes.ingest import _check_ingest_rate_limit

        allowed = _check_ingest_rate_limit("node-hot")

    assert allowed is False


def test_rate_limit_fails_open_on_redis_error():
    with patch(f"{MODULE}.sync_redis.Redis.from_url", side_effect=Exception("redis down")):
        from fleet_platform.api.routes.ingest import _check_ingest_rate_limit

        assert _check_ingest_rate_limit("node-y") is True
