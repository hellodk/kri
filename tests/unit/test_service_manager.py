"""Tests for service manager (#290)."""


def test_service_get_all_in_allowlist():
    from fleet_platform.services.platform_settings_svc import _DEFAULT_SALT_FUNCTIONS

    assert "service.get_all" in _DEFAULT_SALT_FUNCTIONS


def test_service_available_in_allowlist():
    from fleet_platform.services.platform_settings_svc import _DEFAULT_SALT_FUNCTIONS

    assert "service.available" in _DEFAULT_SALT_FUNCTIONS


def test_service_enabled_in_allowlist():
    from fleet_platform.services.platform_settings_svc import _DEFAULT_SALT_FUNCTIONS

    assert "service.enabled" in _DEFAULT_SALT_FUNCTIONS


def test_service_start_restart_are_not_destructive():
    from fleet_platform.models.pending_action import PendingAction

    assert PendingAction.is_destructive("service_start") is False
    assert PendingAction.is_destructive("service_restart") is False


def test_service_stop_disable_are_destructive():
    from fleet_platform.models.pending_action import PendingAction

    assert PendingAction.is_destructive("service_stop") is True
    assert PendingAction.is_destructive("service_disable") is True
