"""Tests for #156: playbook_tasks must not commit var files to git.

Race condition risk: multiple concurrent playbook runs would conflict on the
git index lock. The fix removes all git operations from the Celery worker.
"""

from pathlib import Path

MODULE = (Path(__file__).parent.parent.parent / "fleet_platform/workers/playbook_tasks.py").read_text()


def test_no_git_import_in_module():
    assert "import git" not in MODULE, (
        "playbook_tasks must not import gitpython — git ops from worker cause race conditions"
    )


def test_no_commit_var_files_function():
    assert "_commit_var_files" not in MODULE, "_commit_var_files was removed to prevent git index lock races"


def test_no_repo_root_constant():
    assert "_REPO_ROOT" not in MODULE, "_REPO_ROOT was only used for git operations and should be removed"


def test_extravars_never_written_to_persistent_var_files():
    """#346: extravars must not be written to persistent host_vars/group_vars.

    The _write_var_file helper was removed because:
    1. Secrets leaked across runs — each run inherited previous extravars
    2. Concurrency collisions — two concurrent runs clobber the same file
    3. Redundancy — ansible_runner.run_async(extravars=...) already delivers at highest precedence
    """
    assert "_write_var_file" not in MODULE, "_write_var_file was removed — extravars via run_async only"
    assert 'playbooks_dir / "host_vars' not in MODULE, "host_vars must not be composed with playbooks_dir"
    assert 'playbooks_dir / "group_vars' not in MODULE, "group_vars must not be composed with playbooks_dir"


def test_no_git_repo_instantiation():
    assert "git.Repo" not in MODULE


def test_no_git_commit_call():
    assert "index.commit" not in MODULE
