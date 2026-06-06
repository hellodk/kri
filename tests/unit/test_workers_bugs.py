"""Tests for worker bug fixes: #459, #468, #469, #470, P3-3."""

import re
from pathlib import Path

_TASKS = Path("fleet_platform/workers/playbook_tasks.py").read_text()
_SALT = Path("fleet_platform/workers/salt_presence_tasks.py").read_text()
_SALT_TASKS = Path("fleet_platform/workers/salt_tasks.py").read_text()
_MAINTENANCE = Path("fleet_platform/workers/maintenance.py").read_text()


def test_lock_key_includes_playbook():
    """#459: Redis lock key must include playbook name to avoid blocking all playbooks on same target."""
    # Find lock_key or lock( call with the key string
    match = re.search(r'lock_key\s*=\s*f["\'](.+?)["\']', _TASKS)
    if not match:
        # Check for lock( directly with an f-string key
        match = re.search(r'r\.lock\(\s*\n?\s*f["\'](.+?)["\']', _TASKS, re.DOTALL)
    assert match, "lock_key or r.lock(f'...') assignment not found in playbook_tasks.py"
    key_template = match.group(1)
    assert "playbook" in key_template.lower(), f"lock key '{key_template}' must include playbook name (#459)"


def test_sync_presence_filters_maintenance():
    """#468: sync_minion_presence must not update nodes that are in maintenance_mode."""
    start = _SALT.find("def sync_minion_presence")
    assert start != -1, "sync_minion_presence function not found"
    segment = _SALT[start : start + 3000]
    assert "maintenance_mode" in segment, (
        "sync_minion_presence must check maintenance_mode before updating node status (#468)"
    )


def test_dead_tz_code_removed():
    """P3-3: Dead timezone fallback branch must be removed — PostgreSQL timestamptz is always aware."""
    assert "if job.started_at.tzinfo is None" not in _TASKS, (
        "Dead timezone branch 'if job.started_at.tzinfo is None' must be removed (P3-3)"
    )


def test_salt_runner_call_logs_warning_not_debug():
    """#469 Part A: Salt API failures must log at warning/error level, not debug."""
    # Find _runner_call in salt_presence_tasks — the except block logs the error
    match = re.search(
        r"except\s+Exception[^:]*:\s*\n\s*(logger\.\w+)\(",
        _SALT,
    )
    assert match, "Could not find except Exception log call in salt_presence_tasks.py"
    log_call = match.group(1)
    assert log_call in ("logger.warning", "logger.error"), (
        f"Salt API runner call failure logs at '{log_call}' — must be warning or error (#469)"
    )


def test_salt_credentials_not_frozen_at_module_level():
    """#469 Part B: Salt API credentials must not be frozen at module level in salt_tasks.py.

    Module-level os.environ.get() freezes the value at import time.
    Credentials should be read inside functions so env changes take effect.
    """
    # Check that module-level credential constants do NOT exist in salt_tasks.py
    # We accept them in salt_presence_tasks.py only if they're in _runner_call
    # For salt_tasks.py specifically, check whether _SALT_API_URL etc. are module-level
    module_level_pattern = re.compile(
        r"^_SALT_API_(?:URL|USER|PASSWORD|EAUTH)\s*=\s*os\.environ",
        re.MULTILINE,
    )
    # This is the file to check for frozen creds
    assert not module_level_pattern.search(_SALT_TASKS), (
        "salt_tasks.py has module-level _SALT_API_* = os.environ.get() — "
        "credentials are frozen at import time and won't reflect runtime env changes (#469)"
    )


def test_coalesce_uses_cast():
    """#470: func.coalesce on AnsibleJob.stdout must use cast(String) to avoid NullType.

    The fix uses func.concat(func.coalesce(cast(..., String), ""), _ORPHAN_MESSAGE)
    so the old bare `func.coalesce(...) + _ORPHAN_MESSAGE` pattern must be gone.
    """
    # The old NullType pattern must be absent
    assert 'func.coalesce(AnsibleJob.stdout, "") + _ORPHAN_MESSAGE' not in _MAINTENANCE, (
        "Old NullType coalesce expression still present — must be replaced with cast + func.concat (#470)"
    )
    # The fix: func.concat wrapping coalesce(cast(...)) must be present
    assert "func.concat" in _MAINTENANCE, "func.concat not found in maintenance.py — fix for #470 not applied"
    assert "cast" in _MAINTENANCE, "cast() not found in maintenance.py — fix for #470 not applied"
    assert "_ORPHAN_MESSAGE" in _MAINTENANCE, "_ORPHAN_MESSAGE reference disappeared from maintenance.py"
