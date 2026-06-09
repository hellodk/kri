"""Unit tests for _build_salt_invocation and service.disable allowlist — #614."""

import pytest
from fastapi import HTTPException

from fleet_platform.api.routes.node_actions import _build_salt_invocation
from fleet_platform.services.platform_settings_svc import _DEFAULT_SALT_FUNCTIONS

# ---------------------------------------------------------------------------
# _build_salt_invocation
# ---------------------------------------------------------------------------


class TestBuildSaltInvocation:
    # --- process actions ---

    def test_process_stop_maps_to_sigterm(self):
        fn, args = _build_salt_invocation("process_stop", {"pid": 123})
        assert fn == "ps.kill_pid"
        assert args == ["123", "signal=15"]

    def test_process_suspend_maps_to_sigstop(self):
        fn, args = _build_salt_invocation("process_suspend", {"pid": 456})
        assert fn == "ps.kill_pid"
        assert args == ["456", "signal=17"]

    def test_process_resume_maps_to_sigcont(self):
        fn, args = _build_salt_invocation("process_resume", {"pid": 789})
        assert fn == "ps.kill_pid"
        assert args == ["789", "signal=19"]

    def test_process_pid_coerced_to_string(self):
        fn, args = _build_salt_invocation("process_stop", {"pid": 42})
        assert args[0] == "42"

    def test_unknown_process_action_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _build_salt_invocation("process_kill", {"pid": 1})
        assert exc_info.value.status_code == 400
        assert "process_kill" in exc_info.value.detail

    # --- service actions ---

    def test_service_stop_maps_correctly(self):
        fn, args = _build_salt_invocation("service_stop", {"service": "com.example.nginx"})
        assert fn == "service.stop"
        assert args == ["com.example.nginx"]

    def test_service_disable_maps_correctly(self):
        fn, args = _build_salt_invocation("service_disable", {"service": "com.example.myapp"})
        assert fn == "service.disable"
        assert args == ["com.example.myapp"]

    def test_service_start_maps_correctly(self):
        fn, args = _build_salt_invocation("service_start", {"service": "nginx"})
        assert fn == "service.start"
        assert args == ["nginx"]

    def test_service_restart_maps_correctly(self):
        fn, args = _build_salt_invocation("service_restart", {"service": "nginx"})
        assert fn == "service.restart"
        assert args == ["nginx"]

    def test_unknown_service_action_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _build_salt_invocation("service_nuke", {"service": "foo"})
        assert exc_info.value.status_code == 400
        assert "service_nuke" in exc_info.value.detail

    # --- completely unknown action type ---

    def test_unknown_action_type_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _build_salt_invocation("reboot", {})
        assert exc_info.value.status_code == 400
        assert "reboot" in exc_info.value.detail

    def test_empty_action_type_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _build_salt_invocation("", {})
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# _DEFAULT_SALT_FUNCTIONS allowlist — service.disable and service.enable
# ---------------------------------------------------------------------------


class TestDefaultSaltFunctionsAllowlist:
    def test_service_disable_in_default_allowlist(self):
        assert "service.disable" in _DEFAULT_SALT_FUNCTIONS

    def test_service_enable_in_default_allowlist(self):
        assert "service.enable" in _DEFAULT_SALT_FUNCTIONS

    def test_ps_kill_pid_in_default_allowlist(self):
        # Needed by process_stop / process_suspend / process_resume
        assert "ps.kill_pid" in _DEFAULT_SALT_FUNCTIONS

    def test_service_stop_still_present(self):
        assert "service.stop" in _DEFAULT_SALT_FUNCTIONS

    def test_service_restart_still_present(self):
        assert "service.restart" in _DEFAULT_SALT_FUNCTIONS
