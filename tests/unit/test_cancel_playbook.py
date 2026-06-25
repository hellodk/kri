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
    """ANSIBLE_CONNECT_TIMEOUT is not a real Ansible env var and must not be set."""
    import inspect

    import fleet_platform.workers.playbook_tasks as pt

    source = inspect.getsource(pt.run_playbook)
    assert "ANSIBLE_CONNECT_TIMEOUT" not in source, (
        "ANSIBLE_CONNECT_TIMEOUT is not a real Ansible env var — must be removed"
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
