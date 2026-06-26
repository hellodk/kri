"""Unit tests for Celery reliability configuration (issue #95)."""

# A single resolved host entry, as _resolve_hosts() would return, used to drive
# run_playbook past host resolution in the behavioral playbook tests below.
_FAKE_HOST = {
    "hostname": "h",
    "ip": "1.2.3.4",
    "ssh_user": "admin",
    "ssh_password": "",
    "ssh_key": "",
    "auth_mode": "password",
    "credential_source": "node",
}


def test_celery_task_acks_late_enabled():
    from fleet_platform.workers.celery_app import celery_app

    assert celery_app.conf.task_acks_late is True, (
        "task_acks_late must be True to prevent silent task loss on worker crash"
    )


def test_celery_task_reject_on_worker_lost():
    from fleet_platform.workers.celery_app import celery_app

    assert celery_app.conf.task_reject_on_worker_lost is True, (
        "task_reject_on_worker_lost must be True so tasks are re-queued when worker dies"
    )


def test_celery_soft_time_limit_set():
    from fleet_platform.workers.celery_app import celery_app

    assert celery_app.conf.task_soft_time_limit == 1800, (
        "task_soft_time_limit should be 1800 s (30 min) to raise SoftTimeLimitExceeded"
    )


def test_celery_hard_time_limit_set():
    from fleet_platform.workers.celery_app import celery_app

    assert celery_app.conf.task_time_limit == 2100, (
        "task_time_limit should be 2100 s (35 min) — hard kill if soft limit is ignored"
    )


def test_celery_hard_limit_greater_than_soft():
    from fleet_platform.workers.celery_app import celery_app

    assert celery_app.conf.task_time_limit > celery_app.conf.task_soft_time_limit, (
        "Hard time limit must exceed soft time limit"
    )


def test_scan_node_security_has_autoretry():
    """Fix #130 — autoretry_for makes max_retries actually trigger on failure."""
    from fleet_platform.workers.security_tasks import scan_node_security

    assert scan_node_security.autoretry_for == (Exception,), (
        "scan_node_security must autoretry_for=(Exception,) so max_retries triggers"
    )
    assert scan_node_security.max_retries == 2


def test_scan_node_security_retry_backoff():
    from fleet_platform.workers.security_tasks import scan_node_security

    assert scan_node_security.retry_backoff is True
    assert scan_node_security.retry_backoff_max == 300
    assert scan_node_security.retry_jitter is True


def test_ios_tasks_uses_sync_db():
    """Fix #112 — check_all_jenkins_agents must use get_sync_db(), not asyncio.run()."""
    from unittest.mock import MagicMock, patch

    from fleet_platform.workers.ios_tasks import check_all_jenkins_agents

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalars.return_value.all.return_value = []

    with patch("fleet_platform.workers.ios_tasks.get_sync_db", return_value=mock_db) as mock_gsd:
        check_all_jenkins_agents.run()

    assert mock_gsd.called, "check_all_jenkins_agents must call get_sync_db() — not asyncio.run()"


def test_alert_tasks_no_asyncio_run_at_top_level():
    """Fix #112 — run_alert_evaluation must use asyncio.new_event_loop(), not asyncio.run()."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from fleet_platform.workers.alert_tasks import run_alert_evaluation

    mock_loop = MagicMock()
    mock_loop.run_until_complete = MagicMock()
    mock_loop.close = MagicMock()

    with (
        patch("asyncio.run", side_effect=AssertionError("asyncio.run must not be called — use new_event_loop()")),
        patch("fleet_platform.workers.alert_tasks.asyncio.new_event_loop", return_value=mock_loop),
        patch("fleet_platform.db.session.AsyncSessionLocal"),
        patch("fleet_platform.services.alert_svc.evaluate_alerts", new_callable=AsyncMock),
    ):
        run_alert_evaluation.run()

    mock_loop.run_until_complete.assert_called_once()


def test_playbook_task_uses_run_async():
    """run_playbook must call ansible_runner.run_async() (not blocking run()) for streaming.

    run_async returns a (thread, runner) pair and lets us poll events and flush
    partial stdout to DB every 30s so the UI shows progress before completion.
    Using blocking ansible_runner.run() means stdout is NULL until the entire
    playbook finishes (potentially 20+ minutes with no feedback).
    """
    import uuid as _uuid
    from datetime import UTC, datetime, timedelta
    from unittest.mock import MagicMock, patch

    import fleet_platform.workers.playbook_tasks as pt

    job_id = str(_uuid.uuid4())
    mock_job = MagicMock()
    mock_job.status = "running"
    mock_job.started_at = datetime.now(UTC) - timedelta(seconds=pt._DUPLICATE_GUARD_SECONDS + 60)
    mock_job.playbook = "deploy.yml"
    mock_job.target_type = "node"
    mock_job.target_id = str(_uuid.uuid4())
    mock_job.extravars = {}
    mock_job.timeout_seconds = 1800

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalar_one_or_none.return_value = mock_job
    mock_db.execute.return_value.scalar_one.return_value = mock_job

    mock_thread = MagicMock()
    mock_thread.is_alive.return_value = False
    mock_runner = MagicMock()
    mock_runner.status = "successful"
    mock_runner.rc = 0

    with (
        patch("fleet_platform.workers.playbook_tasks.get_sync_db", return_value=mock_db),
        patch("fleet_platform.workers.playbook_tasks.ansible_runner") as mock_ar,
        patch("fleet_platform.workers.playbook_tasks._resolve_playbook_path") as mock_rpp,
        patch("fleet_platform.workers.playbook_tasks._resolve_hosts") as mock_rh,
        patch("fleet_platform.workers.playbook_tasks._write_static_inventory", return_value="/tmp/inv.ini"),
        patch("fleet_platform.workers.playbook_tasks._flush_stdout"),
    ):
        mock_ar.run_async.return_value = (mock_thread, mock_runner)
        mock_rpp.return_value = (MagicMock(is_dir=lambda: False, __str__=lambda s: "deploy.yml"), MagicMock())
        mock_rh.return_value = [_FAKE_HOST]
        pt.run_playbook(job_id)

    (
        mock_ar.run_async.assert_called_once(),
        (
            "run_playbook must use ansible_runner.run_async() not ansible_runner.run() "
            "so stdout can be flushed to DB incrementally during the run."
        ),
    )
    mock_ar.run.assert_not_called()


def test_playbook_task_flushes_logs_periodically():
    """run_playbook must define _LOG_BATCH_INTERVAL and expose _flush_stdout for periodic DB writes."""
    from fleet_platform.workers import playbook_tasks as pt

    assert hasattr(pt, "_LOG_BATCH_INTERVAL"), "run_playbook must define _LOG_BATCH_INTERVAL"
    assert isinstance(pt._LOG_BATCH_INTERVAL, (int, float)) and pt._LOG_BATCH_INTERVAL > 0, (
        "_LOG_BATCH_INTERVAL must be a positive number (seconds between DB flushes)"
    )
    assert callable(getattr(pt, "_flush_stdout", None)), (
        "run_playbook must define a _flush_stdout callable to write partial logs to DB"
    )


def test_playbook_task_handles_soft_time_limit():
    """run_playbook must catch SoftTimeLimitExceeded and return status='timeout'."""
    from datetime import UTC, datetime, timedelta
    from unittest.mock import MagicMock, patch

    from celery.exceptions import SoftTimeLimitExceeded

    import fleet_platform.workers.playbook_tasks as pt

    job_id = str(__import__("uuid").uuid4())
    mock_job = MagicMock()
    mock_job.status = "running"
    mock_job.started_at = datetime.now(UTC) - timedelta(seconds=pt._DUPLICATE_GUARD_SECONDS + 60)
    mock_job.playbook = "deploy.yml"
    mock_job.target_type = "node"
    mock_job.target_id = str(__import__("uuid").uuid4())
    mock_job.extravars = {}
    mock_job.timeout_seconds = 1800

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.execute.return_value.scalar_one_or_none.return_value = mock_job
    mock_db.execute.return_value.scalar_one.return_value = mock_job

    with (
        patch("fleet_platform.workers.playbook_tasks.get_sync_db", return_value=mock_db),
        patch("fleet_platform.workers.playbook_tasks.ansible_runner") as mock_ar,
        patch("fleet_platform.workers.playbook_tasks._resolve_playbook_path") as mock_rpp,
        patch("fleet_platform.workers.playbook_tasks._resolve_hosts") as mock_rh,
        patch("fleet_platform.workers.playbook_tasks._write_static_inventory", return_value="/tmp/inv.ini"),
        patch("fleet_platform.workers.playbook_tasks._flush_stdout"),
    ):
        mock_ar.run_async.side_effect = SoftTimeLimitExceeded()
        mock_rpp.return_value = (MagicMock(is_dir=lambda: False, __str__=lambda s: "deploy.yml"), MagicMock())
        mock_rh.return_value = [_FAKE_HOST]
        result = pt.run_playbook(job_id)

    assert result["status"] == "timeout", (
        f"run_playbook must catch SoftTimeLimitExceeded and return status='timeout', got {result!r}"
    )
