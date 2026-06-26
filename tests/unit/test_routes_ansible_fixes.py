"""Tests for ansible.py route fixes."""

import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

_WORKTREE = Path(__file__).resolve().parents[2]


def test_extravars_scrub_helper_exists():
    # Behavioral: the helper must be importable and callable from the ansible package
    from fleet_platform.api.routes.ansible import _scrub_extravars

    assert callable(_scrub_extravars), "_scrub_extravars must be a callable defined in the ansible package"


def test_extravars_scrub_removes_sensitive():
    # Import and call the helper directly
    from fleet_platform.api.routes.ansible import _scrub_extravars

    result = _scrub_extravars({"ansible_ssh_pass": "secret", "playbook": "site.yml"})
    assert result["ansible_ssh_pass"] == "***"
    assert result["playbook"] == "site.yml"


def _make_cancel_db(fake_job):
    """Return an AsyncMock db with execute() resolving to a MagicMock result."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = fake_job
    db.execute.return_value = result
    return db


def test_cancel_uses_email_actor():
    """cancel_playbook_job must resolve the actor from the 'email' JWT claim (#342)."""
    import asyncio
    import uuid
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock, MagicMock, patch

    from fleet_platform.api.routes.ansible.jobs import cancel_playbook_job

    job_id = uuid.uuid4()
    fake_job = MagicMock()
    fake_job.status = "running"
    fake_job.celery_task_id = None
    fake_job.stdout = ""
    fake_job.playbook = "site.yml"

    db = _make_cancel_db(fake_job)

    async def run():
        with patch("fleet_platform.api.routes.ansible.jobs.audit", new_callable=AsyncMock):
            with patch("fleet_platform.api.routes.ansible.jobs.datetime") as dt_mock:
                dt_mock.now.return_value = datetime(2024, 1, 1, tzinfo=UTC)
                dt_mock.UTC = UTC
                return await cancel_playbook_job(
                    job_id=job_id,
                    db=db,
                    claims={"email": "tester@example.com"},
                )

    asyncio.run(run())
    assert "tester@example.com" in fake_job.stdout, "cancel must use email claim as the actor identity"


def test_cancel_audit_before_commit():
    """audit() must be awaited before db.commit() in cancel_playbook_job (#342)."""
    import asyncio
    import uuid
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock, MagicMock, patch

    from fleet_platform.api.routes.ansible.jobs import cancel_playbook_job

    job_id = uuid.uuid4()
    fake_job = MagicMock()
    fake_job.status = "pending"
    fake_job.celery_task_id = None
    fake_job.stdout = ""
    fake_job.playbook = "site.yml"

    db = _make_cancel_db(fake_job)
    call_order: list[str] = []

    async def track_audit(*a, **kw):
        call_order.append("audit")

    async def track_commit():
        call_order.append("commit")

    db.commit = AsyncMock(side_effect=track_commit)

    async def run():
        with patch("fleet_platform.api.routes.ansible.jobs.audit", side_effect=track_audit):
            with patch("fleet_platform.api.routes.ansible.jobs.datetime") as dt_mock:
                dt_mock.now.return_value = datetime(2024, 1, 1, tzinfo=UTC)
                dt_mock.UTC = UTC
                await cancel_playbook_job(job_id=job_id, db=db, claims={"email": "admin@test"})

    asyncio.run(run())
    assert call_order == ["audit", "commit"], (
        f"audit() must be called before db.commit() in cancel; got order: {call_order}"
    )


def test_bootstrap_delay_no_ssh_password():
    """bootstrap_node.delay() must never forward ssh_password — plaintext on Redis broker (#495).

    Hardened with AST inspection of the call-site in bootstrap_svc.py to ensure
    no 'ssh_password' keyword argument is passed to .delay().
    """
    svc_src = (_WORKTREE / "fleet_platform/services/bootstrap_svc.py").read_text()
    tree = ast.parse(svc_src)

    found_delay = False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "delay"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "bootstrap_node"
        ):
            found_delay = True
            kw_names = [kw.arg for kw in node.keywords]
            assert "ssh_password" not in kw_names, (
                f"bootstrap_node.delay() must not pass ssh_password — plaintext on Redis broker (#495); "
                f"got kwargs: {kw_names}"
            )

    assert found_delay, "bootstrap_svc must dispatch via bootstrap_node.delay()"
