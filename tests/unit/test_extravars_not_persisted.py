"""Tests for #346: extravars must never be written to persistent host_vars/group_vars.

P0 Security fix: extravars were persisted to playbooks_dir/host_vars/{hostname}.yml
and playbooks_dir/group_vars/{label}.yml, causing:
1. Secret leakage across runs (each run inherited previous run's extravars)
2. Concurrency collisions (two concurrent runs clobber the same file)
3. Redundancy (extravars are already passed at highest precedence via run_async)

The fix removes the _write_var_file helper and all calls to it, relying solely on
ansible_runner.run_async(extravars=job.extravars) to pass variables.
"""

from pathlib import Path

import pytest

MODULE = (Path(__file__).parent.parent.parent / "fleet_platform/workers/playbook_tasks.py").read_text()


def test_write_var_file_function_removed():
    """_write_var_file helper must be removed entirely (#346)."""
    assert "_write_var_file" not in MODULE, (
        "_write_var_file helper was removed — extravars must not be written to persistent files"
    )


def test_host_vars_never_composed_with_playbooks_dir():
    """host_vars directory must never be composed with playbooks_dir in playbook_tasks."""
    assert "host_vars" not in MODULE or 'playbooks_dir / "host_vars"' not in MODULE, (
        "host_vars must not be written to persistent disk — all extravars via run_async(extravars=...)"
    )


def test_group_vars_never_composed_with_playbooks_dir():
    """group_vars directory must never be composed with playbooks_dir in playbook_tasks."""
    assert "group_vars" not in MODULE or 'playbooks_dir / "group_vars"' not in MODULE, (
        "group_vars must not be written to persistent disk — all extravars via run_async(extravars=...)"
    )


def test_yaml_import_removed():
    """yaml import (as _yaml) must be removed — no longer needed without _write_var_file."""
    assert "import yaml as _yaml" not in MODULE, "yaml import removed — _write_var_file was the only use (#346)"


def test_extravars_delivery_via_run_async_preserved():
    """extravars must still be delivered via ansible_runner.run_async(extravars=...)."""
    assert "extravars=job.extravars" in MODULE, (
        "extravars delivery via run_async is the exclusive mechanism for passing job variables"
    )


def test_cannot_import_write_var_file():
    """Importing _write_var_file must raise ImportError (function was deleted)."""
    with pytest.raises(ImportError):
        from fleet_platform.workers.playbook_tasks import _write_var_file  # noqa: F401


def test_no_playbooks_dir_var_file_composition():
    """No composition of playbooks_dir with host_vars or group_vars paths."""
    assert 'playbooks_dir / "host_vars' not in MODULE
    assert 'playbooks_dir / "group_vars' not in MODULE
