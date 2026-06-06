# tests/unit/test_target_lock_351.py
"""Tests for #351: per-target Redis advisory lock in run_playbook.

Prevents two concurrent playbook runs against the same node/group — package-manager
races, conflicting state, etc.

Five test scenarios:
1. Source-contract: _TARGET_LOCK_PREFIX and blocking=False present in module source.
2. Lock unavailable (acquire returns False) → target-locked response; job failed; no run_async.
3. Lock acquired → flow proceeds (run_async reached); lock.release() called once even on exception.
4. Redis connection error on acquire → proceeds without lock (warn + open); no crash.
5. Lock key includes both target_type and target_id.
"""

import uuid
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pending_job(target_type="node", target_id=None):
    """Return a MagicMock job in 'pending' state with a known target."""
    job = MagicMock()
    job.status = "pending"
    job.started_at = None
    job.target_type = target_type
    job.target_id = target_id or str(uuid.uuid4())
    job.playbook = "test.yml"
    job.extravars = {}
    return job


def _make_mock_db(job):
    """Context-manager-compatible DB mock. scalar_one_or_none and scalar_one return job."""
    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    db.execute.return_value.scalar_one_or_none.return_value = job
    db.execute.return_value.scalar_one.return_value = job
    return db


def _mock_runner_pair():
    """Return (mock_thread, mock_runner_obj) as ansible_runner.run_async would."""
    thread = MagicMock()
    thread.is_alive.return_value = False
    runner = MagicMock()
    runner.status = "successful"
    runner.rc = 0
    return thread, runner


# ---------------------------------------------------------------------------
# Test 1: source-contract
# ---------------------------------------------------------------------------


def test_target_lock_prefix_constant_present():
    """_TARGET_LOCK_PREFIX must be defined and start with 'kri:'."""
    import fleet_platform.workers.playbook_tasks as pt

    assert hasattr(pt, "_TARGET_LOCK_PREFIX"), "_TARGET_LOCK_PREFIX constant must be defined in playbook_tasks (#351)"
    assert pt._TARGET_LOCK_PREFIX.startswith("kri:"), (
        f"_TARGET_LOCK_PREFIX must start with 'kri:', got {pt._TARGET_LOCK_PREFIX!r}"
    )


def test_target_lock_uses_blocking_false_in_source():
    """The lock acquire call must use blocking=False so it never blocks the worker queue."""
    import inspect

    import fleet_platform.workers.playbook_tasks as pt

    source = inspect.getsource(pt)
    assert "blocking=False" in source, "run_playbook must use blocking=False when acquiring the per-target lock (#351)"


# ---------------------------------------------------------------------------
# Test 2: lock unavailable → target-locked
# ---------------------------------------------------------------------------


def test_lock_unavailable_returns_target_locked():
    """When the target lock cannot be acquired (another run is in progress),
    run_playbook must:
    - return {"status": "target-locked", ...}
    - set job.status = "failed"
    - set job.stdout containing "Another run is in progress"
    - NOT call ansible_runner.run_async
    """
    job_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())
    job = _make_pending_job(target_type="node", target_id=target_id)
    mock_db = _make_mock_db(job)

    mock_lock = MagicMock()
    mock_lock.acquire.return_value = False  # lock already held

    mock_redis_instance = MagicMock()
    mock_redis_instance.lock.return_value = mock_lock

    with (
        patch("fleet_platform.workers.playbook_tasks.get_sync_db", return_value=mock_db),
        patch("fleet_platform.workers.playbook_tasks.sync_redis") as mock_sync_redis,
        patch("fleet_platform.workers.playbook_tasks.ansible_runner") as mock_ar,
    ):
        mock_sync_redis.Redis.from_url.return_value = mock_redis_instance
        mock_sync_redis.RedisError = Exception  # make isinstance check work

        from fleet_platform.workers.playbook_tasks import run_playbook

        result = run_playbook(job_id)

    assert result["status"] == "target-locked", f"Expected target-locked, got {result!r}"
    assert result.get("job_id") == job_id

    # job must be marked failed
    assert job.status == "failed", f"job.status must be 'failed', got {job.status!r}"

    # stdout must contain the expected message
    assert "Another run is in progress" in (job.stdout or ""), (
        f"job.stdout must mention 'Another run is in progress', got {job.stdout!r}"
    )

    # ansible_runner.run_async must NOT have been called
    mock_ar.run_async.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: lock acquired → flow proceeds; release called exactly once
# ---------------------------------------------------------------------------


def test_lock_acquired_flow_proceeds_and_released():
    """When the lock is acquired, run_playbook must reach ansible_runner.run_async
    and call lock.release() exactly once even when the run succeeds."""
    job_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())
    job = _make_pending_job(target_type="node", target_id=target_id)
    mock_db = _make_mock_db(job)

    mock_lock = MagicMock()
    mock_lock.acquire.return_value = True  # lock acquired

    mock_redis_instance = MagicMock()
    mock_redis_instance.lock.return_value = mock_lock

    thread, runner_obj = _mock_runner_pair()

    with (
        patch("fleet_platform.workers.playbook_tasks.get_sync_db", return_value=mock_db),
        patch("fleet_platform.workers.playbook_tasks.sync_redis") as mock_sync_redis,
        patch("fleet_platform.workers.playbook_tasks.ansible_runner") as mock_ar,
        patch("fleet_platform.workers.playbook_tasks._resolve_playbook_path") as mock_resolve,
        patch("fleet_platform.workers.playbook_tasks._resolve_hosts") as mock_hosts,
        patch("fleet_platform.workers.playbook_tasks._write_static_inventory", return_value="/tmp/inv.ini"),
    ):
        mock_sync_redis.Redis.from_url.return_value = mock_redis_instance
        mock_sync_redis.RedisError = Exception

        mock_ar.run_async.return_value = (thread, runner_obj)
        mock_resolve.return_value = (
            MagicMock(is_dir=lambda: False, __str__=lambda s: "test.yml"),
            MagicMock(),
        )
        mock_hosts.return_value = [
            {
                "hostname": "mac-01",
                "ip": "10.0.0.1",
                "ssh_user": "admin",
                "ssh_password": "",
                "ssh_key": "",
                "auth_mode": "password",
                "credential_source": "node",
            }
        ]

        from fleet_platform.workers.playbook_tasks import run_playbook

        run_playbook(job_id)

    # run_async must have been called (flow proceeded past the lock)
    mock_ar.run_async.assert_called_once()

    # lock.release() must have been called exactly once in the finally block
    mock_lock.release.assert_called_once()


def test_lock_released_even_when_run_raises():
    """lock.release() must be called in finally even when the inner run raises."""
    job_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())
    job = _make_pending_job(target_type="node", target_id=target_id)
    mock_db = _make_mock_db(job)

    mock_lock = MagicMock()
    mock_lock.acquire.return_value = True

    mock_redis_instance = MagicMock()
    mock_redis_instance.lock.return_value = mock_lock

    with (
        patch("fleet_platform.workers.playbook_tasks.get_sync_db", return_value=mock_db),
        patch("fleet_platform.workers.playbook_tasks.sync_redis") as mock_sync_redis,
        patch("fleet_platform.workers.playbook_tasks.ansible_runner") as mock_ar,
        patch("fleet_platform.workers.playbook_tasks._resolve_playbook_path") as mock_resolve,
        patch("fleet_platform.workers.playbook_tasks._resolve_hosts") as mock_hosts,
        patch("fleet_platform.workers.playbook_tasks._write_static_inventory", return_value="/tmp/inv.ini"),
    ):
        mock_sync_redis.Redis.from_url.return_value = mock_redis_instance
        mock_sync_redis.RedisError = Exception

        # Make run_async raise to simulate a crash mid-run
        mock_ar.run_async.side_effect = RuntimeError("simulated crash")
        mock_resolve.return_value = (
            MagicMock(is_dir=lambda: False, __str__=lambda s: "test.yml"),
            MagicMock(),
        )
        mock_hosts.return_value = [
            {
                "hostname": "mac-01",
                "ip": "10.0.0.1",
                "ssh_user": "admin",
                "ssh_password": "",
                "ssh_key": "",
                "auth_mode": "password",
                "credential_source": "node",
            }
        ]

        from fleet_platform.workers.playbook_tasks import run_playbook

        try:
            run_playbook(job_id)
        except RuntimeError:
            pass  # expected — the re-raise in the except block

    # Even with an exception, lock.release() must have been called
    mock_lock.release.assert_called_once()


# ---------------------------------------------------------------------------
# Test 4: Redis connection error → degrade open (proceed without lock)
# ---------------------------------------------------------------------------


def test_redis_connection_error_degrades_open():
    """When Redis is unreachable on acquire, run_playbook must:
    - log a warning (not raise)
    - proceed to call ansible_runner.run_async (no crash, no block)
    """
    job_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())
    job = _make_pending_job(target_type="node", target_id=target_id)
    mock_db = _make_mock_db(job)

    thread, runner_obj = _mock_runner_pair()

    with (
        patch("fleet_platform.workers.playbook_tasks.get_sync_db", return_value=mock_db),
        patch("fleet_platform.workers.playbook_tasks.sync_redis") as mock_sync_redis,
        patch("fleet_platform.workers.playbook_tasks.ansible_runner") as mock_ar,
        patch("fleet_platform.workers.playbook_tasks._resolve_playbook_path") as mock_resolve,
        patch("fleet_platform.workers.playbook_tasks._resolve_hosts") as mock_hosts,
        patch("fleet_platform.workers.playbook_tasks._write_static_inventory", return_value="/tmp/inv.ini"),
    ):
        # Make Redis.from_url raise a RedisError
        class _FakeRedisError(Exception):
            pass

        mock_sync_redis.RedisError = _FakeRedisError
        mock_sync_redis.Redis.from_url.side_effect = _FakeRedisError("connection refused")

        mock_ar.run_async.return_value = (thread, runner_obj)
        mock_resolve.return_value = (
            MagicMock(is_dir=lambda: False, __str__=lambda s: "test.yml"),
            MagicMock(),
        )
        mock_hosts.return_value = [
            {
                "hostname": "mac-01",
                "ip": "10.0.0.1",
                "ssh_user": "admin",
                "ssh_password": "",
                "ssh_key": "",
                "auth_mode": "password",
                "credential_source": "node",
            }
        ]

        from fleet_platform.workers.playbook_tasks import run_playbook

        # Must not raise
        result = run_playbook(job_id)

    # Flow must proceed past the lock failure — run_async must have been called
    mock_ar.run_async.assert_called_once()

    # Must NOT be target-locked
    assert result.get("status") != "target-locked", "Redis failure must degrade open — not block the run"


# ---------------------------------------------------------------------------
# Test 5: lock key includes target_type AND target_id
# ---------------------------------------------------------------------------


def test_lock_key_includes_target_type_and_target_id():
    """The Redis lock key must embed both target_type and target_id so different
    targets get independent locks."""
    job_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())
    job = _make_pending_job(target_type="group", target_id=target_id)
    mock_db = _make_mock_db(job)

    mock_lock = MagicMock()
    mock_lock.acquire.return_value = False  # lock held — simplest path to inspect the key

    mock_redis_instance = MagicMock()
    mock_redis_instance.lock.return_value = mock_lock

    with (
        patch("fleet_platform.workers.playbook_tasks.get_sync_db", return_value=mock_db),
        patch("fleet_platform.workers.playbook_tasks.sync_redis") as mock_sync_redis,
        patch("fleet_platform.workers.playbook_tasks.ansible_runner"),
    ):
        mock_sync_redis.Redis.from_url.return_value = mock_redis_instance
        mock_sync_redis.RedisError = Exception

        from fleet_platform.workers.playbook_tasks import run_playbook

        run_playbook(job_id)

    # Inspect what key was passed to r.lock(...)
    assert mock_redis_instance.lock.called, "r.lock() must have been called"
    lock_key = mock_redis_instance.lock.call_args[0][0]  # first positional arg
    assert "group" in lock_key, f"Lock key must include target_type 'group', got {lock_key!r}"
    assert target_id in lock_key, f"Lock key must include target_id, got {lock_key!r}"
