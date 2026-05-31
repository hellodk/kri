"""Tests for process manager (#289)."""


def test_ps_list_processes_in_salt_allowlist():
    from fleet_platform.services.platform_settings_svc import _DEFAULT_SALT_FUNCTIONS
    assert "ps.list_processes" in _DEFAULT_SALT_FUNCTIONS


def test_ps_kill_pid_in_salt_allowlist():
    from fleet_platform.services.platform_settings_svc import _DEFAULT_SALT_FUNCTIONS
    assert "ps.kill_pid" in _DEFAULT_SALT_FUNCTIONS


def test_process_kill_is_forbidden():
    from fleet_platform.models.pending_action import PendingAction
    assert PendingAction.is_forbidden("process_kill") is True


def test_process_stop_is_destructive_not_forbidden():
    from fleet_platform.models.pending_action import PendingAction
    assert PendingAction.is_destructive("process_stop") is True
    assert PendingAction.is_forbidden("process_stop") is False


def test_process_resume_is_not_destructive():
    from fleet_platform.models.pending_action import PendingAction
    assert PendingAction.is_destructive("process_resume") is False
