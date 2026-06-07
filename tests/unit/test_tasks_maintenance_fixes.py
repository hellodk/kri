"""Tests for #444, #445, #450, #456, #462 fixes — updated with behavioural assertions (#505)."""

from pathlib import Path

_WORKTREE = Path(__file__).resolve().parents[2]
_TASKS_SRC = (_WORKTREE / "fleet_platform/workers/ansible_tasks.py").read_text()
_MAINT_SRC = (_WORKTREE / "fleet_platform/workers/maintenance.py").read_text()


def test_bootstrap_acks_late_false():
    assert "acks_late=False" in _TASKS_SRC, "bootstrap_node decorator must have acks_late=False"


def test_bootstrap_no_ssh_password_param():
    import ast

    tree = ast.parse(_TASKS_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "bootstrap_node":
            args = [a.arg for a in node.args.args]
            assert "ssh_password" not in args, "bootstrap_node must not accept ssh_password"


def test_mark_stale_excludes_maintenance_mode():
    # Find mark_stale_nodes function body
    start = _MAINT_SRC.find("def mark_stale_nodes(")
    segment = _MAINT_SRC[start : start + 2000]
    assert "maintenance_mode" in segment, "mark_stale_nodes must filter maintenance_mode nodes"


def test_reap_orphaned_bootstraps_updates_stuck_node(monkeypatch):
    """reap_orphaned_bootstraps must update both BootstrapRun rows and stuck Node rows.

    This test fails if the function is removed or no longer performs the node status update.
    Behavioural replacement for the former name-presence-only check (#505).
    """
    import uuid as _uuid

    from fleet_platform.workers.maintenance import reap_orphaned_bootstraps

    stuck_node_id = _uuid.uuid4()
    executed_stmts = []

    # Call sequence: execute(SELECT) → .scalars().all(), execute(UPDATE BootstrapRun),
    # execute(UPDATE Node).  We return different objects per call.
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

    # Must return a 'reaped' count (not error)
    assert "reaped" in result

    # Must have executed at least 3 statements:
    # 1. SELECT stuck node ids
    # 2. UPDATE BootstrapRun (mark failed)
    # 3. UPDATE Node (mark bootstrap_status=failed)
    assert len(executed_stmts) >= 3, (
        f"reap_orphaned_bootstraps must issue at least 3 SQL statements (SELECT + 2x UPDATE), got {len(executed_stmts)}"
    )


def test_cleanup_handles_null_finished_at():
    start = _MAINT_SRC.find("def cleanup_old_bootstrap_runs")
    segment = _MAINT_SRC[start : start + 1000]
    assert "is_(None)" in segment or "IS NULL" in segment.upper(), "cleanup must handle NULL finished_at"
