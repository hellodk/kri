# tests/unit/test_no_double_run_350.py
"""Tests for #350: prevent playbook double-execution on SIGKILL / duplicate delivery.

Two layers:
1. Source-contract: acks_late=False on the task decorator; _DUPLICATE_GUARD_SECONDS present.
2. Behavioural guard: entry idempotency check rejects a re-delivery of a running job.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Layer 1 — source-contract tests
# ---------------------------------------------------------------------------


def test_run_playbook_has_acks_late_false():
    """run_playbook task must have acks_late=False — a SIGKILLed run must NOT be redelivered (#350)."""
    import fleet_platform.workers.playbook_tasks as pt

    assert pt.run_playbook.acks_late is False, (
        f"run_playbook.acks_late={pt.run_playbook.acks_late!r} — must be False to prevent redelivery on SIGKILL (#350)"
    )


def test_duplicate_guard_seconds_constant_present():
    """_DUPLICATE_GUARD_SECONDS must exist and be ≥ the task's time_limit (1860s)."""
    import fleet_platform.workers.playbook_tasks as pt

    assert hasattr(pt, "_DUPLICATE_GUARD_SECONDS"), (
        "_DUPLICATE_GUARD_SECONDS constant must be defined in playbook_tasks (#350)"
    )
    assert pt._DUPLICATE_GUARD_SECONDS >= 1860, (
        f"_DUPLICATE_GUARD_SECONDS={pt._DUPLICATE_GUARD_SECONDS} must be ≥ 1860 (the task hard time_limit)"
    )


# ---------------------------------------------------------------------------
# Layer 2 — behavioural guard tests
# ---------------------------------------------------------------------------


def _make_mock_db(job):
    """Return a context-manager-compatible mock DB whose first execute() returns job."""
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalar_one_or_none.return_value = job
    return mock_db


def test_duplicate_delivery_recent_running_job_is_skipped():
    """When a job is already running and started_at is recent (within guard window),
    the duplicate delivery must return status='duplicate-skipped' without calling
    ansible_runner.run_async and without mutating job.status."""
    job_id = str(uuid.uuid4())

    mock_job = MagicMock()
    mock_job.status = "running"
    mock_job.started_at = datetime.now(UTC) - timedelta(seconds=60)

    mock_db = _make_mock_db(mock_job)

    with (
        patch("fleet_platform.workers.playbook_tasks.get_sync_db", return_value=mock_db),
        patch("fleet_platform.workers.playbook_tasks.ansible_runner") as mock_runner,
    ):
        from fleet_platform.workers.playbook_tasks import run_playbook

        result = run_playbook(job_id)

    assert result["status"] == "duplicate-skipped", f"Expected duplicate-skipped, got {result!r}"
    assert result.get("job_id") == job_id

    # job.status must NOT have been mutated to 'failed' or anything else
    assert mock_job.status == "running", (
        "Duplicate guard must not mutate job.status — live run's record must stay intact"
    )

    # ansible_runner.run_async must never have been called
    mock_runner.run_async.assert_not_called()


def test_duplicate_delivery_stale_running_job_proceeds():
    """When started_at is beyond the guard window (> _DUPLICATE_GUARD_SECONDS ago),
    the guard does NOT suppress execution — the task proceeds past the guard.

    We let the call fail naturally on internals (no hosts, no playbook path etc.)
    and only assert that run_async was reached (attempted) or that the guard
    was not the exit point (status != 'duplicate-skipped')."""

    job_id = str(uuid.uuid4())

    mock_job = MagicMock()
    mock_job.status = "running"
    # started_at is 7261s ago — well beyond the guard window (updated for #348: _DUPLICATE_GUARD_SECONDS=7260)
    mock_job.started_at = datetime.now(UTC) - timedelta(seconds=7261)
    mock_job.playbook = "test.yml"
    mock_job.target_type = "node"
    mock_job.target_id = str(uuid.uuid4())
    mock_job.extravars = {}

    mock_db = _make_mock_db(mock_job)
    # Subsequent scalar_one calls (after guard) return the same job
    mock_db.execute.return_value.scalar_one.return_value = mock_job

    # Patch ansible_runner so we don't actually spawn a subprocess;
    # raise immediately so we can observe that we got past the guard.
    mock_thread = MagicMock()
    mock_thread.is_alive.return_value = False
    mock_runner_obj = MagicMock()
    mock_runner_obj.status = "failed"
    mock_runner_obj.rc = 1

    with (
        patch("fleet_platform.workers.playbook_tasks.get_sync_db", return_value=mock_db),
        patch("fleet_platform.workers.playbook_tasks.ansible_runner") as mock_ar,
        patch("fleet_platform.workers.playbook_tasks._resolve_playbook_path") as mock_resolve,
        patch("fleet_platform.workers.playbook_tasks._resolve_hosts") as mock_hosts,
        patch("fleet_platform.workers.playbook_tasks._write_static_inventory", return_value="/tmp/inv.ini"),
    ):
        mock_ar.run_async.return_value = (mock_thread, mock_runner_obj)
        mock_resolve.return_value = (MagicMock(is_dir=lambda: False, __str__=lambda s: "test.yml"), MagicMock())
        mock_hosts.return_value = [
            {
                "hostname": "h",
                "ip": "1.2.3.4",
                "ssh_user": "admin",
                "ssh_password": "",
                "ssh_key": "",
                "auth_mode": "password",
                "credential_source": "node",
            }
        ]

        from fleet_platform.workers.playbook_tasks import run_playbook

        result = run_playbook(job_id)

    # The guard must NOT have fired — we should not see duplicate-skipped
    assert result.get("status") != "duplicate-skipped", (
        "Stale running job (beyond guard window) must not be suppressed by the duplicate guard"
    )


def test_duplicate_delivery_naive_started_at_no_crash():
    """Guard must handle a tzinfo-less (naive) started_at without raising TypeError
    and must still correctly detect a recent duplicate."""
    job_id = str(uuid.uuid4())

    mock_job = MagicMock()
    mock_job.status = "running"
    # Naive datetime (no tzinfo) — as stored by an older migration or bug
    mock_job.started_at = datetime.utcnow() - timedelta(seconds=30)  # naive, 30s ago

    mock_db = _make_mock_db(mock_job)

    with (
        patch("fleet_platform.workers.playbook_tasks.get_sync_db", return_value=mock_db),
        patch("fleet_platform.workers.playbook_tasks.ansible_runner"),
    ):
        from fleet_platform.workers.playbook_tasks import run_playbook

        # Must not raise — naive datetime handling must be in place
        result = run_playbook(job_id)

    assert result["status"] == "duplicate-skipped", f"Naive started_at should still trigger guard, got {result!r}"


def test_job_not_found_still_returns_error():
    """Existing behaviour: missing job_id → error/job_not_found (unchanged)."""
    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalar_one_or_none.return_value = None

    with patch("fleet_platform.workers.playbook_tasks.get_sync_db", return_value=mock_db):
        from fleet_platform.workers.playbook_tasks import run_playbook

        result = run_playbook(str(uuid.uuid4()))

    assert result["status"] == "error"
    assert result["reason"] == "job_not_found"
