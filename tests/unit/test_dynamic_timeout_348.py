# tests/unit/test_dynamic_timeout_348.py
"""TDD tests for #348: dynamic per-job playbook timeout + runner cancellation.

Layer 1 — behavioral tests (task attributes, run_async call, SoftTimeLimitExceeded handler).
Layer 2 — model/schema tests.
Layer 3 — contract sync (TypeScript file).
"""

import uuid
from pathlib import Path
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Layer 1 — source-contract tests
# ---------------------------------------------------------------------------


def test_decorator_has_soft_time_limit_7200():
    """run_playbook task must declare soft_time_limit=7200 as the absolute ceiling (#348)."""
    import fleet_platform.workers.playbook_tasks as pt

    assert pt.run_playbook.soft_time_limit == 7200, (
        f"run_playbook.soft_time_limit={pt.run_playbook.soft_time_limit} — must be 7200 (#348)"
    )


def test_decorator_has_time_limit_7260():
    """run_playbook task must declare time_limit=7260 (7200 + 60s hard kill buffer)."""
    import fleet_platform.workers.playbook_tasks as pt

    assert pt.run_playbook.time_limit == 7260, (
        f"run_playbook.time_limit={pt.run_playbook.time_limit} — must be 7260 (#348)"
    )


def _make_stale_job(timeout_seconds: int = 3600):
    """Return a mock AnsibleJob with a stale started_at that bypasses the duplicate guard."""
    from datetime import UTC, datetime, timedelta

    import fleet_platform.workers.playbook_tasks as pt

    job = MagicMock()
    job.status = "running"
    job.started_at = datetime.now(UTC) - timedelta(seconds=pt._DUPLICATE_GUARD_SECONDS + 60)
    job.playbook = "deploy.yml"
    job.target_type = "node"
    job.target_id = str(uuid.uuid4())
    job.extravars = {}
    job.timeout_seconds = timeout_seconds
    return job


def _make_db_mock(job):
    db = MagicMock()
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__ = MagicMock(return_value=False)
    db.execute.return_value.scalar_one_or_none.return_value = job
    db.execute.return_value.scalar_one.return_value = job
    return db


def _patch_playbook_infra(mock_ar, job, *, thread=None, runner=None):
    """Return a patch-stack context that lets run_playbook reach run_async."""
    from unittest.mock import MagicMock, patch

    if thread is None:
        thread = MagicMock()
        thread.is_alive.return_value = False
    if runner is None:
        runner = MagicMock()
        runner.status = "successful"
        runner.rc = 0

    mock_rpp = MagicMock(return_value=(MagicMock(is_dir=lambda: False, __str__=lambda s: "deploy.yml"), MagicMock()))
    mock_rh = MagicMock(
        return_value=[
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
    )

    return (
        patch("fleet_platform.workers.playbook_tasks.get_sync_db", return_value=_make_db_mock(job)),
        patch("fleet_platform.workers.playbook_tasks._resolve_playbook_path", mock_rpp),
        patch("fleet_platform.workers.playbook_tasks._resolve_hosts", mock_rh),
        patch("fleet_platform.workers.playbook_tasks._write_static_inventory", return_value="/tmp/inv.ini"),
        patch("fleet_platform.workers.playbook_tasks._flush_stdout"),
    )


def test_run_async_receives_timeout_kwarg():
    """ansible_runner.run_async must be called with timeout=<job.timeout_seconds> (#348)."""
    from contextlib import ExitStack
    from unittest.mock import MagicMock, patch

    import fleet_platform.workers.playbook_tasks as pt

    job = _make_stale_job(timeout_seconds=3600)
    job_id = str(uuid.uuid4())

    mock_thread = MagicMock()
    mock_thread.is_alive.return_value = False
    mock_runner = MagicMock()
    mock_runner.status = "successful"
    mock_runner.rc = 0

    with patch("fleet_platform.workers.playbook_tasks.ansible_runner") as mock_ar, ExitStack() as stack:
        for p in _patch_playbook_infra(mock_ar, job, thread=mock_thread, runner=mock_runner):
            stack.enter_context(p)
        mock_ar.run_async.return_value = (mock_thread, mock_runner)
        pt.run_playbook(job_id)

    assert mock_ar.run_async.called, "run_async was never called"
    _, kwargs = mock_ar.run_async.call_args
    assert "timeout" in kwargs, "run_async must be called with a timeout= kwarg (#348)"
    assert kwargs["timeout"] == 3600, (
        f"run_async timeout kwarg must equal job.timeout_seconds (3600), got {kwargs['timeout']}"
    )


def test_soft_time_limit_handler_cancels_runner():
    """SoftTimeLimitExceeded must trigger runner.cancel() (#348)."""
    from contextlib import ExitStack
    from unittest.mock import MagicMock, patch

    from celery.exceptions import SoftTimeLimitExceeded

    import fleet_platform.workers.playbook_tasks as pt

    job = _make_stale_job()
    job_id = str(uuid.uuid4())

    mock_runner = MagicMock()
    mock_thread = MagicMock()
    # is_alive raises SoftTimeLimitExceeded — simulates Celery signal firing mid-loop
    mock_thread.is_alive.side_effect = SoftTimeLimitExceeded()

    with patch("fleet_platform.workers.playbook_tasks.ansible_runner") as mock_ar, ExitStack() as stack:
        for p in _patch_playbook_infra(mock_ar, job, thread=mock_thread, runner=mock_runner):
            stack.enter_context(p)
        mock_ar.run_async.return_value = (mock_thread, mock_runner)
        result = pt.run_playbook(job_id)

    assert result["status"] == "timeout", f"Expected timeout, got {result!r}"
    mock_runner.cancel.assert_called(), "SoftTimeLimitExceeded handler must call runner.cancel() (#348)"


def test_soft_time_limit_handler_joins_thread():
    """SoftTimeLimitExceeded must trigger thread.join() (best-effort cleanup) (#348)."""
    from contextlib import ExitStack
    from unittest.mock import MagicMock, patch

    from celery.exceptions import SoftTimeLimitExceeded

    import fleet_platform.workers.playbook_tasks as pt

    job = _make_stale_job()
    job_id = str(uuid.uuid4())

    mock_runner = MagicMock()
    mock_thread = MagicMock()
    mock_thread.is_alive.side_effect = SoftTimeLimitExceeded()

    with patch("fleet_platform.workers.playbook_tasks.ansible_runner") as mock_ar, ExitStack() as stack:
        for p in _patch_playbook_infra(mock_ar, job, thread=mock_thread, runner=mock_runner):
            stack.enter_context(p)
        mock_ar.run_async.return_value = (mock_thread, mock_runner)
        result = pt.run_playbook(job_id)

    assert result["status"] == "timeout", f"Expected timeout, got {result!r}"
    mock_thread.join.assert_called(), "SoftTimeLimitExceeded handler must call thread.join() (#348)"


def test_migration_039_file_exists():
    """Migration 039_ansible_job_timeout.py must exist in the migrations/versions dir."""
    migrations_dir = Path(__file__).parent.parent.parent / "fleet_platform" / "db" / "migrations" / "versions"
    # Accept 038 or 039 depending on the branch stacking
    candidates = list(migrations_dir.glob("*_ansible_job_timeout.py"))
    assert candidates, "Migration file *_ansible_job_timeout.py must exist in fleet_platform/db/migrations/versions/"


def test_migration_has_add_column_timeout_seconds():
    """The timeout migration must add a timeout_seconds column to ansible_jobs.

    Behavioral testing of Alembic migrations requires a live DB transaction; we use
    ast.parse to structurally verify the upgrade() function contains the right call.
    """
    import ast

    migrations_dir = Path(__file__).parent.parent.parent / "fleet_platform" / "db" / "migrations" / "versions"
    candidates = list(migrations_dir.glob("*_ansible_job_timeout.py"))
    assert candidates, "Migration file missing"

    tree = ast.parse(candidates[0].read_text())

    add_column_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_column"
    ]
    assert add_column_calls, "Migration must call op.add_column(...)"

    timeout_col_found = any(
        any(isinstance(n, ast.Constant) and n.value == "timeout_seconds" for n in ast.walk(call))
        for call in add_column_calls
    )
    assert timeout_col_found, "Migration must add a column named 'timeout_seconds'"


def test_duplicate_guard_and_lock_ttl_updated():
    """_DUPLICATE_GUARD_SECONDS and _TARGET_LOCK_TTL must be updated to 7260 (#348)."""
    import fleet_platform.workers.playbook_tasks as pt

    assert pt._DUPLICATE_GUARD_SECONDS >= 7260, (
        f"_DUPLICATE_GUARD_SECONDS={pt._DUPLICATE_GUARD_SECONDS} must be >= 7260 (#348)"
    )
    assert pt._TARGET_LOCK_TTL >= 7260, f"_TARGET_LOCK_TTL={pt._TARGET_LOCK_TTL} must be >= 7260 (#348)"


# ---------------------------------------------------------------------------
# Layer 2 — model / schema tests
# ---------------------------------------------------------------------------


def test_ansible_job_model_has_timeout_seconds():
    """AnsibleJob model must have a timeout_seconds column with default 1800."""
    from fleet_platform.models.ansible_job import AnsibleJob

    col = AnsibleJob.__table__.c.get("timeout_seconds")
    assert col is not None, "AnsibleJob model must have a timeout_seconds column (#348)"
    # Check the server_default
    assert col.server_default is not None, "timeout_seconds must have a server_default='1800'"


def test_playbook_run_request_rejects_timeout_below_60():
    """PlaybookRunRequest must reject timeout_seconds < 60 (ValidationError)."""
    from pydantic import ValidationError

    from fleet_platform.schemas.playbook import PlaybookRunRequest

    try:
        PlaybookRunRequest(
            playbook="deploy.yml",
            target_type="node",
            target_id=str(uuid.uuid4()),
            timeout_seconds=10,
        )
        raise AssertionError("ValidationError expected for timeout_seconds=10")
    except ValidationError:
        pass  # expected


def test_playbook_run_request_rejects_timeout_above_21600():
    """PlaybookRunRequest must reject timeout_seconds > 21600 (ValidationError)."""
    from pydantic import ValidationError

    from fleet_platform.schemas.playbook import PlaybookRunRequest

    try:
        PlaybookRunRequest(
            playbook="deploy.yml",
            target_type="node",
            target_id=str(uuid.uuid4()),
            timeout_seconds=99999,
        )
        raise AssertionError("ValidationError expected for timeout_seconds=99999")
    except ValidationError:
        pass  # expected


def test_playbook_run_request_accepts_valid_timeout():
    """PlaybookRunRequest must accept timeout_seconds=3600."""
    from fleet_platform.schemas.playbook import PlaybookRunRequest

    req = PlaybookRunRequest(
        playbook="deploy.yml",
        target_type="node",
        target_id=str(uuid.uuid4()),
        timeout_seconds=3600,
    )
    assert req.timeout_seconds == 3600


def test_playbook_run_request_default_timeout():
    """PlaybookRunRequest must default timeout_seconds to 1800."""
    from fleet_platform.schemas.playbook import PlaybookRunRequest

    req = PlaybookRunRequest(
        playbook="deploy.yml",
        target_type="node",
        target_id=str(uuid.uuid4()),
    )
    assert req.timeout_seconds == 1800


def test_ansible_job_response_has_timeout_seconds():
    """AnsibleJobResponse must include timeout_seconds field."""
    from datetime import datetime, timezone

    from fleet_platform.schemas.playbook import AnsibleJobResponse

    resp = AnsibleJobResponse(
        id=uuid.uuid4(),
        playbook="deploy.yml",
        target_type="node",
        target_label="mac-01",
        extravars={},
        status="completed",
        triggered_by="admin@example.com",
        started_at=None,
        completed_at=None,
        stdout=None,
        rc=None,
        created_at=datetime.now(timezone.utc),
        timeout_seconds=3600,
    )
    assert resp.timeout_seconds == 3600


def test_ansible_job_response_default_timeout():
    """AnsibleJobResponse must default timeout_seconds to 1800."""
    from datetime import datetime, timezone

    from fleet_platform.schemas.playbook import AnsibleJobResponse

    resp = AnsibleJobResponse(
        id=uuid.uuid4(),
        playbook="deploy.yml",
        target_type="node",
        target_label="mac-01",
        extravars={},
        status="completed",
        triggered_by="admin@example.com",
        started_at=None,
        completed_at=None,
        stdout=None,
        rc=None,
        created_at=datetime.now(timezone.utc),
    )
    assert resp.timeout_seconds == 1800


# ---------------------------------------------------------------------------
# Layer 3 — TypeScript contract sync
# ---------------------------------------------------------------------------


def test_frontend_playbooks_ts_has_timeout_seconds():
    """frontend/src/api/playbooks.ts must contain 'timeout_seconds' for contract sync.

    TypeScript cannot be parsed with Python's ast module; content search is the only
    available mechanism for this cross-language API-contract guard.
    """
    ts_file = Path(__file__).parent.parent.parent / "frontend" / "src" / "api" / "playbooks.ts"
    assert ts_file.exists(), f"TypeScript file not found: {ts_file}"
    content = ts_file.read_text()
    assert "timeout_seconds" in content, (
        "frontend/src/api/playbooks.ts must include timeout_seconds for AnsibleJob contract sync (#348)"
    )
