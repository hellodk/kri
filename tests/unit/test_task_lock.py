"""Unit tests for #153 — Redis task deduplication."""

from unittest.mock import MagicMock, patch

import pytest

from fleet_platform.services.task_lock import unique_task


def test_unique_task_runs_when_lock_acquired():
    mock_redis = MagicMock()
    mock_redis.set.return_value = True  # lock acquired

    with patch("fleet_platform.services.task_lock._get_sync_redis", return_value=mock_redis):

        @unique_task()
        def my_task():
            return "ran"

        result = my_task()

    assert result == "ran"
    mock_redis.delete.assert_called_once()


def test_unique_task_skips_when_lock_held():
    mock_redis = MagicMock()
    mock_redis.set.return_value = None  # lock already held

    with patch("fleet_platform.services.task_lock._get_sync_redis", return_value=mock_redis):

        @unique_task()
        def my_task():
            return "ran"

        result = my_task()

    assert result is None
    mock_redis.delete.assert_not_called()


def test_unique_task_releases_lock_on_exception():
    mock_redis = MagicMock()
    mock_redis.set.return_value = True

    with patch("fleet_platform.services.task_lock._get_sync_redis", return_value=mock_redis):

        @unique_task()
        def failing_task():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            failing_task()

    mock_redis.delete.assert_called_once()


def test_key_fn_produces_per_node_key():
    mock_redis = MagicMock()
    mock_redis.set.return_value = True

    with patch("fleet_platform.services.task_lock._get_sync_redis", return_value=mock_redis):

        @unique_task(key_fn=lambda args, kwargs: f"drift:{args[0]}")
        def compute_drift(node_id):
            return f"computed:{node_id}"

        result = compute_drift("node-abc")

    assert result == "computed:node-abc"
    call_args = mock_redis.set.call_args
    assert "drift:node-abc" in call_args[0][0]


def test_drift_tasks_uses_unique_task():
    with open("fleet_platform/workers/drift_tasks.py") as f:
        src = f.read()
    assert "unique_task" in src, "drift_tasks must use @unique_task for compute_drift"


def test_get_sync_redis_uses_settings_url():
    """_get_sync_redis must instantiate a connection using settings.redis_url (coverage L12-14)."""
    mock_settings = MagicMock()
    mock_settings.redis_url = "redis://localhost:6379/0"
    with (
        patch("fleet_platform.core.config.settings", mock_settings),
        patch("fleet_platform.services.task_lock.sync_redis") as mock_sync_redis,
    ):
        from fleet_platform.services.task_lock import _get_sync_redis

        _get_sync_redis()
    mock_sync_redis.from_url.assert_called_once_with("redis://localhost:6379/0", decode_responses=True)


def test_health_tasks_uses_unique_task():
    with open("fleet_platform/workers/ansible_tasks.py") as f:
        src = f.read()
    assert "unique_task" in src, "ansible_tasks must use @unique_task for refresh_all_node_grains"
