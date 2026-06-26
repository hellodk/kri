"""Tests for cancel playbook job endpoint (#342) and timeout settings (#343)."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


def test_ansible_timeout_is_10_seconds():
    """ANSIBLE_TIMEOUT must be 10s so unreachable hosts fail within 5 min.
    Moved from envvars to playbooks/ansible.cfg (#353): timeout = 10 under [defaults].
    """
    import configparser
    from pathlib import Path

    cfg_path = Path(__file__).parent.parent.parent / "playbooks" / "ansible.cfg"
    cfg = configparser.ConfigParser()
    cfg.read(str(cfg_path))
    val = cfg.get("defaults", "timeout", fallback=None)
    assert val is not None, "timeout must be set in playbooks/ansible.cfg [defaults]"
    assert int(val.strip()) == 10, f"timeout must be 10s (to avoid long hangs on unreachable hosts), got {val!r}"


def test_ansible_ssh_retries_is_2():
    """3 total SSH attempts (initial + 2 retries).
    Moved from envvars to playbooks/ansible.cfg (#353): retries = 2 under [ssh_connection].
    """
    import configparser
    from pathlib import Path

    cfg_path = Path(__file__).parent.parent.parent / "playbooks" / "ansible.cfg"
    cfg = configparser.ConfigParser()
    cfg.read(str(cfg_path))
    val = cfg.get("ssh_connection", "retries", fallback=None)
    assert val is not None, "retries must be set in playbooks/ansible.cfg [ssh_connection]"
    assert int(val.strip()) == 2, f"retries must be 2, got {val!r}"


def test_ansible_connect_timeout_removed():
    """ANSIBLE_CONNECT_TIMEOUT must not be set in the envvars passed to ansible_runner."""
    from datetime import UTC, datetime, timedelta
    from unittest.mock import MagicMock, patch

    import fleet_platform.workers.playbook_tasks as pt

    job_id = str(uuid.uuid4())

    mock_job = MagicMock()
    mock_job.status = "running"
    # Use a stale started_at to bypass the duplicate guard
    mock_job.started_at = datetime.now(UTC) - timedelta(seconds=pt._DUPLICATE_GUARD_SECONDS + 60)
    mock_job.playbook = "deploy.yml"
    mock_job.target_type = "node"
    mock_job.target_id = str(uuid.uuid4())
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

    captured_envvars: dict = {}

    def fake_run_async(**kwargs):
        captured_envvars.update(kwargs.get("envvars", {}))
        return (mock_thread, mock_runner)

    with (
        patch("fleet_platform.workers.playbook_tasks.get_sync_db", return_value=mock_db),
        patch("fleet_platform.workers.playbook_tasks.ansible_runner") as mock_ar,
        patch("fleet_platform.workers.playbook_tasks._resolve_playbook_path") as mock_rpp,
        patch("fleet_platform.workers.playbook_tasks._resolve_hosts") as mock_rh,
        patch("fleet_platform.workers.playbook_tasks._write_static_inventory", return_value="/tmp/inv.ini"),
        patch("fleet_platform.workers.playbook_tasks._flush_stdout"),
    ):
        mock_ar.run_async.side_effect = fake_run_async
        mock_rpp.return_value = (MagicMock(is_dir=lambda: False, __str__=lambda s: "deploy.yml"), MagicMock())
        mock_rh.return_value = [
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
        pt.run_playbook(job_id)

    assert mock_ar.run_async.called, "run_async was never called — test setup may be wrong"
    assert "ANSIBLE_CONNECT_TIMEOUT" not in captured_envvars, (
        "ANSIBLE_CONNECT_TIMEOUT is not a real Ansible env var and must not be in envvars"
    )


def test_ansible_job_has_celery_task_id_column():
    from sqlalchemy import inspect as sa_inspect

    from fleet_platform.models.ansible_job import AnsibleJob

    cols = {c.key for c in sa_inspect(AnsibleJob).columns}
    assert "celery_task_id" in cols, "celery_task_id column must exist on AnsibleJob"


def test_ansible_job_has_cancelled_at_column():
    from sqlalchemy import inspect as sa_inspect

    from fleet_platform.models.ansible_job import AnsibleJob

    cols = {c.key for c in sa_inspect(AnsibleJob).columns}
    assert "cancelled_at" in cols, "cancelled_at column must exist on AnsibleJob"


def test_cancel_route_returns_409_on_completed_job():
    """Cannot cancel a job that's already in a terminal state."""

    async def _run():
        from fastapi import HTTPException

        from fleet_platform.api.routes.ansible import cancel_playbook_job

        mock_job = MagicMock()
        mock_job.status = "completed"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_job

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)
        claims = {"sub": "test-user"}

        with pytest.raises(HTTPException) as exc_info:
            await cancel_playbook_job(uuid.uuid4(), db=db, claims=claims)
        assert exc_info.value.status_code == 409

    asyncio.run(_run())


def test_cancel_route_returns_409_on_failed_job():
    """Cannot cancel a job that already failed."""

    async def _run():
        from fastapi import HTTPException

        from fleet_platform.api.routes.ansible import cancel_playbook_job

        mock_job = MagicMock()
        mock_job.status = "failed"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_job

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)
        claims = {"sub": "test-user"}

        with pytest.raises(HTTPException) as exc_info:
            await cancel_playbook_job(uuid.uuid4(), db=db, claims=claims)
        assert exc_info.value.status_code == 409

    asyncio.run(_run())


def test_cancel_route_returns_404_on_missing_job():
    """Returns 404 when job_id does not exist."""

    async def _run():
        from fastapi import HTTPException

        from fleet_platform.api.routes.ansible import cancel_playbook_job

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)
        claims = {"sub": "test-user"}

        with pytest.raises(HTTPException) as exc_info:
            await cancel_playbook_job(uuid.uuid4(), db=db, claims=claims)
        assert exc_info.value.status_code == 404

    asyncio.run(_run())


def test_cancel_route_cancels_running_job():
    """Successfully cancels a running job — status becomes 'cancelled'."""

    async def _run():
        from unittest.mock import patch

        from fleet_platform.api.routes.ansible import cancel_playbook_job

        mock_job = MagicMock()
        mock_job.status = "running"
        mock_job.celery_task_id = "test-celery-task-id"
        mock_job.stdout = "some output"
        mock_job.playbook = "test.yml"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_job

        db = AsyncMock()
        db.execute = AsyncMock(return_value=mock_result)
        db.commit = AsyncMock()
        claims = {"sub": "operator@kri"}

        mock_celery = MagicMock()
        mock_celery.control.revoke = MagicMock()

        with (
            # #750: cancel_playbook_job (and its celery_app/audit deps) lives in
            # the jobs sub-module now; patch them where they are used.
            patch("fleet_platform.api.routes.ansible.jobs.celery_app", mock_celery, create=True),
            patch("fleet_platform.api.routes.ansible.jobs.audit", new=AsyncMock()),
        ):
            result = await cancel_playbook_job(uuid.uuid4(), db=db, claims=claims)

        assert result["status"] == "cancelled"
        assert mock_job.status == "cancelled"
        assert mock_job.cancelled_at is not None
        assert "[CANCELLED]" in mock_job.stdout

    asyncio.run(_run())
