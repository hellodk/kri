"""Unit tests for #153 — Redis task deduplication (+ #1048 token ownership)."""

from unittest.mock import ANY, MagicMock, patch

import pytest

from fleet_platform.services.task_lock import unique_task


class FakeRedis:
    """In-memory stand-in with SET-nx/ex and atomic compare-and-delete."""

    def __init__(self):
        self.store: dict = {}
        self.expiry: dict = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        if ex is not None:
            self.expiry[key] = ex
        return True

    def eval(self, script, numkeys, key, token):
        # Mirrors the compare-and-delete Lua: only the owner deletes.
        if self.store.get(key) == token:
            del self.store[key]
            self.expiry.pop(key, None)
            return 1
        return 0

    def get(self, key):
        return self.store.get(key)


def test_unique_task_runs_when_lock_acquired():
    mock_redis = MagicMock()
    mock_redis.set.return_value = True  # lock acquired
    mock_redis.eval.return_value = 1  # owner released

    with patch("fleet_platform.services.task_lock._get_sync_redis", return_value=mock_redis):

        @unique_task()
        def my_task():
            return "ran"

        result = my_task()

    assert result == "ran"
    # Lock value must be a unique token, not a constant (#1048).
    mock_redis.set.assert_called_once_with("task_lock:my_task", ANY, nx=True, ex=300)
    assert mock_redis.set.call_args[0][1] != "1"
    mock_redis.eval.assert_called_once()


def test_unique_task_skips_when_lock_held():
    mock_redis = MagicMock()
    mock_redis.set.return_value = None  # lock already held

    with patch("fleet_platform.services.task_lock._get_sync_redis", return_value=mock_redis):

        @unique_task()
        def my_task():
            return "ran"

        result = my_task()

    assert result is None
    mock_redis.eval.assert_not_called()


def test_unique_task_releases_lock_on_exception():
    mock_redis = MagicMock()
    mock_redis.set.return_value = True
    mock_redis.eval.return_value = 1

    with patch("fleet_platform.services.task_lock._get_sync_redis", return_value=mock_redis):

        @unique_task()
        def failing_task():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            failing_task()

    mock_redis.eval.assert_called_once()


def test_owner_releases_own_lock():
    fake = FakeRedis()

    with patch("fleet_platform.services.task_lock._get_sync_redis", return_value=fake):

        @unique_task(key_fn=lambda args, kwargs: "owned")
        def task():
            assert fake.store["task_lock:owned"]  # token stored
            return "ok"

        assert task() == "ok"

    assert "task_lock:owned" not in fake.store


def test_non_owner_cannot_delete_expired_or_reowned_lock():
    """Lock expired + re-acquired by worker B while A was still running: A's
    finisher must NOT delete B's live lock (#1048)."""
    fake = FakeRedis()

    with patch("fleet_platform.services.task_lock._get_sync_redis", return_value=fake):

        @unique_task(key_fn=lambda args, kwargs: "contested")
        def slow_task_a():
            assert fake.store["task_lock:contested"]  # A holds it via its token
            # Simulate expiry + re-acquire by another worker mid-flight.
            fake.store["task_lock:contested"] = "token-B"
            return "done"

        assert slow_task_a() == "done"

    # Worker B's lock survived A's release attempt.
    assert fake.store["task_lock:contested"] == "token-B"


def test_ttl_override_per_call_site():
    mock_redis = MagicMock()
    mock_redis.set.return_value = True
    mock_redis.eval.return_value = 1

    with patch("fleet_platform.services.task_lock._get_sync_redis", return_value=mock_redis):

        @unique_task(ttl=2400)
        def long_running_task():
            return "ran"

        long_running_task()

    assert mock_redis.set.call_args.kwargs["ex"] == 2400


def test_default_ttl_unchanged_for_compute_drift_style_tasks():
    mock_redis = MagicMock()
    mock_redis.set.return_value = True
    mock_redis.eval.return_value = 1

    with patch("fleet_platform.services.task_lock._get_sync_redis", return_value=mock_redis):

        @unique_task(key_fn=lambda args, kwargs: f"drift:{args[0]}")
        def compute_drift(node_id):
            return f"computed:{node_id}"

        result = compute_drift("node-abc")

    assert result == "computed:node-abc"
    call_args = mock_redis.set.call_args
    assert "drift:node-abc" in call_args[0][0]
    assert call_args.kwargs["ex"] == 300
    assert compute_drift.lock_ttl == 300


def test_refresh_all_node_grains_uses_extended_ttl():
    from fleet_platform.workers import ansible_tasks

    assert hasattr(ansible_tasks, "unique_task"), (
        "ansible_tasks must import @unique_task — required for refresh_all_node_grains deduplication (#153)"
    )
    fn = getattr(ansible_tasks.refresh_all_node_grains, "run", ansible_tasks.refresh_all_node_grains)
    assert getattr(fn, "lock_ttl", None) == 2400, (
        "refresh_all_node_grains must hold its lock for ttl=2400 (grain sweep outlasts the 300s default)"
    )


def test_drift_tasks_uses_unique_task():
    from fleet_platform.workers import drift_tasks

    assert hasattr(drift_tasks, "unique_task"), (
        "drift_tasks must import @unique_task — required for compute_drift deduplication (#153)"
    )


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
