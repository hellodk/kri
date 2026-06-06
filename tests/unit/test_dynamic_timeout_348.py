# tests/unit/test_dynamic_timeout_348.py
"""TDD tests for #348: dynamic per-job playbook timeout + runner cancellation.

Layer 1 — source-contract tests (grep module source / file system).
Layer 2 — model/schema tests.
Layer 3 — contract sync (TypeScript file).
"""

import inspect
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# Layer 1 — source-contract tests
# ---------------------------------------------------------------------------


def test_decorator_has_soft_time_limit_7200():
    """run_playbook decorator must raise the static ceiling to soft_time_limit=7200."""
    import fleet_platform.workers.playbook_tasks as pt

    source = inspect.getsource(pt)
    assert "soft_time_limit=7200" in source, (
        "run_playbook decorator must set soft_time_limit=7200 (per-job ceiling for #348)"
    )


def test_decorator_has_time_limit_7260():
    """run_playbook decorator must set time_limit=7260 (7200 + 60s hard kill buffer)."""
    import fleet_platform.workers.playbook_tasks as pt

    source = inspect.getsource(pt)
    assert "time_limit=7260" in source, "run_playbook decorator must set time_limit=7260 for #348"


def test_run_async_receives_timeout_kwarg():
    """ansible_runner.run_async must be called with a timeout= keyword so ansible-runner
    kills the subprocess when the per-job timeout expires."""
    import fleet_platform.workers.playbook_tasks as pt

    source = inspect.getsource(pt)
    assert "timeout=timeout" in source, (
        "run_async must be called with timeout=timeout so ansible-runner owns the kill (#348)"
    )


def test_soft_time_limit_handler_cancels_runner():
    """SoftTimeLimitExceeded handler must call runner.cancel() before the DB write."""
    import fleet_platform.workers.playbook_tasks as pt

    source = inspect.getsource(pt)
    assert "runner.cancel()" in source, "SoftTimeLimitExceeded handler must cancel the ansible-runner subprocess (#348)"


def test_soft_time_limit_handler_joins_thread():
    """SoftTimeLimitExceeded handler must join the runner thread (best-effort)."""
    import fleet_platform.workers.playbook_tasks as pt

    source = inspect.getsource(pt)
    assert "thread.join(" in source, "SoftTimeLimitExceeded handler must join the runner thread (#348)"


def test_migration_039_file_exists():
    """Migration 039_ansible_job_timeout.py must exist in the migrations/versions dir."""
    migrations_dir = Path(__file__).parent.parent.parent / "fleet_platform" / "db" / "migrations" / "versions"
    # Accept 038 or 039 depending on the branch stacking
    candidates = list(migrations_dir.glob("*_ansible_job_timeout.py"))
    assert candidates, "Migration file *_ansible_job_timeout.py must exist in fleet_platform/db/migrations/versions/"


def test_migration_has_add_column_timeout_seconds():
    """The timeout migration must add a timeout_seconds column to ansible_jobs."""
    migrations_dir = Path(__file__).parent.parent.parent / "fleet_platform" / "db" / "migrations" / "versions"
    candidates = list(migrations_dir.glob("*_ansible_job_timeout.py"))
    assert candidates, "Migration file missing"
    content = candidates[0].read_text()
    assert "timeout_seconds" in content, "Migration must add timeout_seconds column"
    assert "add_column" in content, "Migration must use op.add_column"


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
    """frontend/src/api/playbooks.ts must contain 'timeout_seconds' for contract sync."""
    ts_file = Path(__file__).parent.parent.parent / "frontend" / "src" / "api" / "playbooks.ts"
    assert ts_file.exists(), f"TypeScript file not found: {ts_file}"
    content = ts_file.read_text()
    assert "timeout_seconds" in content, (
        "frontend/src/api/playbooks.ts must include timeout_seconds for AnsibleJob contract sync (#348)"
    )
