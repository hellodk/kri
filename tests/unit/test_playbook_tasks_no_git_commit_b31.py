"""Tests for #156: playbook_tasks must not commit var files to git.

Race condition risk: multiple concurrent playbook runs would conflict on the
git index lock. The fix removes all git operations from the Celery worker.

Absence regression invariants: hardened with AST inspection and hasattr
checks instead of raw substring matching.
"""

import ast
from pathlib import Path

_PATH = Path(__file__).parent.parent.parent / "fleet_platform/workers/playbook_tasks.py"


def test_no_git_import_in_module():
    """No 'import git' or 'from git import ...' in playbook_tasks — git ops cause race conditions."""
    tree = ast.parse(_PATH.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "git", (
                    "playbook_tasks must not import gitpython — git ops from worker cause race conditions"
                )
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "git", "playbook_tasks must not import from gitpython"


def test_no_commit_var_files_function():
    import fleet_platform.workers.playbook_tasks as pt

    assert not hasattr(pt, "_commit_var_files"), "_commit_var_files was removed to prevent git index lock races"


def test_no_repo_root_constant():
    import fleet_platform.workers.playbook_tasks as pt

    assert not hasattr(pt, "_REPO_ROOT"), "_REPO_ROOT was only used for git operations and should be removed"


def test_extravars_never_written_to_persistent_var_files():
    """#346: extravars must not be written to persistent host_vars/group_vars.

    The _write_var_file helper was removed because:
    1. Secrets leaked across runs — each run inherited previous extravars
    2. Concurrency collisions — two concurrent runs clobber the same file
    3. Redundancy — ansible_runner.run_async(extravars=...) already delivers at highest precedence
    """
    import fleet_platform.workers.playbook_tasks as pt

    assert not hasattr(pt, "_write_var_file"), "_write_var_file was removed — extravars via run_async only"

    # AST: playbooks_dir must not be path-joined with host_vars or group_vars.
    # (Path(tmpdir) / "host_vars" for SSH-password inventory is fine; it's the
    #  playbooks_dir composition that leaked extravars across runs.)
    tree = ast.parse(_PATH.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            right = node.right
            if isinstance(right, ast.Constant) and isinstance(right.value, str):
                if "host_vars" in right.value or "group_vars" in right.value:
                    left_src = ast.unparse(node.left)
                    assert "playbooks_dir" not in left_src, (
                        f"playbooks_dir must not be composed with host_vars/group_vars (Fix #346): {left_src!r}"
                    )


def test_no_git_repo_instantiation():
    """AST check: no git.Repo(...) call present in the module."""
    tree = ast.parse(_PATH.read_text())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "Repo"
            and isinstance(node.value, ast.Name)
            and node.value.id == "git"
        ):
            raise AssertionError("git.Repo must not be instantiated in playbook_tasks")


def test_no_git_commit_call():
    """AST check: no index.commit(...) call present in the module."""
    tree = ast.parse(_PATH.read_text())
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "commit"
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "index"
        ):
            raise AssertionError("index.commit must not be called in playbook_tasks")
