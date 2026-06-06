"""Tests for #444, #445, #450, #456, #462 fixes."""

from pathlib import Path

_TASKS_SRC = Path("fleet_platform/workers/ansible_tasks.py").read_text()
_MAINT_SRC = Path("fleet_platform/workers/maintenance.py").read_text()


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


def test_reap_orphaned_bootstraps_task_exists():
    assert "reap_orphaned_bootstraps" in _MAINT_SRC, "reap_orphaned_bootstraps task must exist"


def test_cleanup_handles_null_finished_at():
    start = _MAINT_SRC.find("def cleanup_old_bootstrap_runs")
    segment = _MAINT_SRC[start : start + 1000]
    assert "is_(None)" in segment or "IS NULL" in segment.upper(), "cleanup must handle NULL finished_at"
