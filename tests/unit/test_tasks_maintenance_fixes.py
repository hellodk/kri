"""Tests for #444, #445, #450, #456, #462 fixes — updated with behavioural assertions (#505).

Behavioral conversion (#800): the decorator/signature/WHERE-clause checks used to
scrape ``ansible_tasks.py`` / ``maintenance.py`` source for substrings. They now
introspect the live Celery task objects and drive the real beat tasks against a
mocked sync session, asserting on the SQL that is actually constructed and on the
task's runtime configuration.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from sqlalchemy.dialects import postgresql


def _compiled(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


# ---------------------------------------------------------------------------
# #444 — bootstrap_node Celery task configuration / signature
# ---------------------------------------------------------------------------


def test_bootstrap_acks_late_false():
    """bootstrap_node must run with acks_late=False to prevent double-bootstrap on SIGKILL."""
    from fleet_platform.workers.ansible_tasks import bootstrap_node

    assert bootstrap_node.acks_late is False


def test_bootstrap_no_ssh_password_param():
    """bootstrap_node's real signature must not accept an ssh_password argument."""
    import inspect

    from fleet_platform.workers.ansible_tasks import bootstrap_node

    params = inspect.signature(bootstrap_node.run).parameters
    assert "ssh_password" not in params, "bootstrap_node must not accept ssh_password"


# ---------------------------------------------------------------------------
# #456 — mark_stale_nodes must exclude maintenance-mode nodes
# ---------------------------------------------------------------------------


def test_mark_stale_excludes_maintenance_mode():
    """Both UPDATEs issued by mark_stale_nodes must filter out maintenance_mode nodes."""
    from fleet_platform.workers import maintenance

    db = MagicMock()
    db.execute.return_value = MagicMock(rowcount=0)

    @contextmanager
    def fake_db():
        yield db

    with (
        patch.object(maintenance, "get_sync_db", fake_db),
        patch.object(maintenance, "get_setting_sync", return_value=None),
        patch.object(maintenance, "sync_redis", MagicMock()),
    ):
        maintenance.mark_stale_nodes()

    updates = [_compiled(c.args[0]) for c in db.execute.call_args_list]
    assert updates, "mark_stale_nodes must issue UPDATE statements"
    for sql in updates:
        assert "maintenance_mode" in sql, f"mark_stale_nodes UPDATE must filter maintenance_mode (#456); got:\n{sql}"


# ---------------------------------------------------------------------------
# #445 Part B — cleanup_old_bootstrap_runs must handle NULL finished_at
# ---------------------------------------------------------------------------


def test_cleanup_handles_null_finished_at():
    """The DELETE built by cleanup_old_bootstrap_runs must include a finished_at IS NULL branch."""
    from fleet_platform.workers import maintenance

    setting_result = MagicMock()
    setting_result.scalar_one_or_none.return_value = None  # → default retention (30 days)
    delete_result = MagicMock(rowcount=0)

    db = MagicMock()
    db.execute.side_effect = [setting_result, delete_result]

    @contextmanager
    def fake_db():
        yield db

    with patch.object(maintenance, "get_sync_db", fake_db):
        result = maintenance.cleanup_old_bootstrap_runs()

    assert result["cutoff_days"] == 30
    delete_stmt = _compiled(db.execute.call_args_list[1].args[0])
    assert "finished_at IS NULL" in delete_stmt, (
        f"cleanup must delete stuck rows with NULL finished_at (#445 Part B); got:\n{delete_stmt}"
    )


# ---------------------------------------------------------------------------
# #445 Part C — reap_orphaned_bootstraps updates both BootstrapRun and Node rows
# ---------------------------------------------------------------------------


def test_reap_orphaned_bootstraps_updates_stuck_node(monkeypatch):
    """reap_orphaned_bootstraps must update both BootstrapRun rows and stuck Node rows.

    This test fails if the function is removed or no longer performs the node status update.
    Behavioural replacement for the former name-presence-only check (#505).
    """
    import uuid as _uuid

    from fleet_platform.workers.maintenance import reap_orphaned_bootstraps

    stuck_node_id = _uuid.uuid4()
    executed_stmts = []

    call_counter = {"n": 0}

    class FakeSelectResult:
        def scalars(self):
            return self

        def all(self):
            return [stuck_node_id]

    class FakeUpdateResult:
        rowcount = 1

    def fake_execute(stmt):
        executed_stmts.append(stmt)
        n = call_counter["n"]
        call_counter["n"] += 1
        if n == 0:
            return FakeSelectResult()
        return FakeUpdateResult()

    class FakeDB:
        def execute(self, stmt):
            return fake_execute(stmt)

        def commit(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(
        "fleet_platform.workers.maintenance.get_sync_db",
        lambda: FakeDB(),
    )

    result = reap_orphaned_bootstraps()

    assert "reaped" in result

    assert len(executed_stmts) >= 3, (
        f"reap_orphaned_bootstraps must issue at least 3 SQL statements (SELECT + 2x UPDATE), got {len(executed_stmts)}"
    )
