"""Tests for worker bug fixes: #459, #468, #469, #470, P3-3.

Behavioral conversion (#800): most assertions used to scrape worker module source
for regexes/substrings. They now drive the real functions/tasks and assert on
observable behaviour — the SQL constructed, the log emitted, the node rows
mutated, and the live module namespace. Two assertions remain source-contract
(annotated below) because they verify the *absence* of code that can only be
observed by inspecting the run_playbook source.
"""

import logging
import re
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy.dialects import postgresql

_TASKS = Path("fleet_platform/workers/playbook_tasks.py").read_text()


def _compiled(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


# ---------------------------------------------------------------------------
# #459 — Redis lock key must include the playbook name
# ---------------------------------------------------------------------------


def test_lock_key_includes_playbook():
    """#459: Redis lock key must include playbook name to avoid blocking all playbooks on same target."""
    # behavioral conversion blocked: the lock key is composed deep inside the
    # run_playbook Celery task body and is only observable by launching the full
    # task (live Redis + DB + ansible-runner). Verified here as a source contract.
    match = re.search(r'lock_key\s*=\s*f["\'](.+?)["\']', _TASKS)
    if not match:
        match = re.search(r'r\.lock\(\s*\n?\s*f["\'](.+?)["\']', _TASKS, re.DOTALL)
    assert match, "lock_key or r.lock(f'...') assignment not found in playbook_tasks.py"
    key_template = match.group(1)
    assert "playbook" in key_template.lower(), f"lock key '{key_template}' must include playbook name (#459)"


# ---------------------------------------------------------------------------
# #468 — sync_minion_presence must skip maintenance-mode nodes
# ---------------------------------------------------------------------------


def test_sync_presence_filters_maintenance():
    """A minion reported 'up' that is in maintenance_mode must NOT be flipped online (#468)."""
    import uuid

    from fleet_platform.workers import salt_presence_tasks as spt

    master_id = uuid.uuid4()
    master = MagicMock()
    master.id = master_id
    master.name = "m1"
    master.api_url = "https://salt.example:8000"
    master.api_user = "saltapi"
    master.api_password_enc = "enc"
    master.api_eauth = "pam"
    master.is_default = True
    master.tls_verify = False

    node_maint = MagicMock(minion_id="mac-maint", maintenance_mode=True, salt_master_id=master_id, status="offline")
    node_normal = MagicMock(minion_id="mac-normal", maintenance_mode=False, salt_master_id=master_id, status="offline")

    db_masters = MagicMock()
    db_masters.execute.return_value.scalars.return_value.all.return_value = [master]
    db_nodes = MagicMock()
    db_nodes.execute.return_value.scalars.return_value.all.return_value = [node_maint, node_normal]

    @contextmanager
    def ctx(db):
        yield db

    get_db = MagicMock(side_effect=[ctx(db_masters), ctx(db_nodes)])

    with (
        patch.object(spt, "get_sync_db", get_db),
        patch("fleet_platform.services.platform_settings_svc.decrypt_secret", return_value="pw"),
        patch.object(spt, "_runner_call", return_value=["mac-maint", "mac-normal"]),
    ):
        result = spt.sync_minion_presence()

    assert node_normal.status == "online", "a non-maintenance up minion must be marked online"
    assert node_maint.status == "offline", "a maintenance-mode minion must NOT be flipped online (#468)"
    assert result["online"] == 1


# ---------------------------------------------------------------------------
# P3-3 — dead timezone fallback branch removed
# ---------------------------------------------------------------------------


def test_dead_tz_code_removed():
    """P3-3: Dead timezone fallback branch must be removed — PostgreSQL timestamptz is always aware."""
    # behavioral conversion blocked: this asserts the *absence* of a removed
    # branch inside run_playbook; absence of dead code is only observable by
    # inspecting the module source, not by exercising behaviour.
    assert "if job.started_at.tzinfo is None" not in _TASKS, (
        "Dead timezone branch 'if job.started_at.tzinfo is None' must be removed (P3-3)"
    )


# ---------------------------------------------------------------------------
# #469 Part A — salt-api runner call failures log at warning, not debug
# ---------------------------------------------------------------------------


def test_salt_runner_call_logs_warning_not_debug(caplog):
    """A failing salt-api runner call must return None and log a WARNING (#469 Part A)."""
    from fleet_platform.workers import salt_presence_tasks as spt

    with (
        patch.object(spt.requests, "post", side_effect=RuntimeError("connection refused")),
        caplog.at_level(logging.WARNING, logger="fleet_platform.workers.salt_presence_tasks"),
    ):
        result = spt._runner_call("https://salt:8000", "user", "pw", "pam", False, "manage.up")

    assert result is None
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "a failed salt-api runner call must log at WARNING or higher (#469)"


# ---------------------------------------------------------------------------
# #469 Part B — salt-api credentials must not be frozen at module import time
# ---------------------------------------------------------------------------


def test_salt_credentials_not_frozen_at_module_level():
    """salt_tasks must not bind _SALT_API_* credentials at module import time (#469 Part B).

    Module-level os.environ.get() freezes the value at import; credentials must be
    read inside functions. Behavioral guard: the live module namespace must expose
    no frozen _SALT_API_* constants.
    """
    from fleet_platform.workers import salt_tasks

    frozen = [
        name
        for name in ("_SALT_API_URL", "_SALT_API_USER", "_SALT_API_PASSWORD", "_SALT_API_EAUTH")
        if hasattr(salt_tasks, name)
    ]
    assert not frozen, (
        f"salt_tasks has module-level frozen credential constant(s) {frozen} — "
        "credentials must be read at call time so runtime env changes take effect (#469)"
    )


# ---------------------------------------------------------------------------
# #470 — orphan-reaper stdout coalesce must cast to String (avoid NullType)
# ---------------------------------------------------------------------------


def test_coalesce_uses_cast():
    """reap_orphaned_jobs must build its stdout UPDATE with concat(coalesce(cast(...)))  (#470).

    The #470 regression was a NullType error from bare func.coalesce on a nullable
    Text column. We compile the actual UPDATE the task constructs and assert the
    CAST + CONCAT + COALESCE wrapping is present — proving the statement is
    well-typed rather than scraping the source for the expression.
    """
    from fleet_platform.workers import maintenance

    db = MagicMock()
    db.execute.return_value = MagicMock(rowcount=0)

    @contextmanager
    def fake_db():
        yield db

    with patch.object(maintenance, "get_sync_db", fake_db):
        maintenance.reap_orphaned_jobs()

    sql = _compiled(db.execute.call_args_list[0].args[0]).lower()
    assert "concat" in sql, f"stdout update must use func.concat (#470); got:\n{sql}"
    assert "coalesce" in sql, f"stdout update must use func.coalesce (#470); got:\n{sql}"
    assert "cast" in sql, f"stdout update must cast stdout to String to avoid NullType (#470); got:\n{sql}"
