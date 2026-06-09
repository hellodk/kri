"""Unit tests for protected-target denylist + param validation — #615."""

import pytest
from fastapi import HTTPException

from fleet_platform.api.routes.node_actions import _validate_action_params
from fleet_platform.models.pending_action import PendingAction

# ---------------------------------------------------------------------------
# PendingAction.is_protected_target
# ---------------------------------------------------------------------------


class TestIsProtectedTarget:
    def test_salt_minion_exact(self):
        assert PendingAction.is_protected_target("salt-minion") is True

    def test_salt_master_exact(self):
        assert PendingAction.is_protected_target("salt-master") is True

    def test_sshd_exact(self):
        assert PendingAction.is_protected_target("sshd") is True

    def test_sshd_uppercase(self):
        assert PendingAction.is_protected_target("SSHD") is True

    def test_sshd_mixed_case(self):
        assert PendingAction.is_protected_target("Sshd") is True

    def test_launchd_label_com_openssh_sshd(self):
        # launchd label -> bare segment "sshd"
        assert PendingAction.is_protected_target("com.openssh.sshd") is True

    def test_launchd_label_com_apple_mdnsresponder(self):
        # bare segment -> "mDNSResponder" -> lower -> "mdnsresponder"
        assert PendingAction.is_protected_target("com.apple.mDNSResponder") is True

    def test_configd(self):
        assert PendingAction.is_protected_target("configd") is True

    def test_securityd(self):
        assert PendingAction.is_protected_target("securityd") is True

    def test_exo(self):
        assert PendingAction.is_protected_target("exo") is True

    def test_kernel_task(self):
        assert PendingAction.is_protected_target("kernel_task") is True

    def test_launchd(self):
        assert PendingAction.is_protected_target("launchd") is True

    def test_not_protected_nginx(self):
        assert PendingAction.is_protected_target("nginx") is False

    def test_not_protected_my_app(self):
        assert PendingAction.is_protected_target("my-app") is False

    def test_not_protected_python(self):
        assert PendingAction.is_protected_target("python") is False

    def test_empty_string(self):
        assert PendingAction.is_protected_target("") is False


# ---------------------------------------------------------------------------
# _validate_action_params
# ---------------------------------------------------------------------------


class TestValidateActionParams:
    # --- process_* ---

    def test_process_stop_non_digit_pid_raises_422(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_action_params("process_stop", {"pid": "abc"})
        assert exc_info.value.status_code == 422
        assert "pid" in exc_info.value.detail.lower()

    def test_process_stop_empty_pid_raises_422(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_action_params("process_stop", {"pid": ""})
        assert exc_info.value.status_code == 422

    def test_process_stop_protected_name_raises_403(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_action_params("process_stop", {"pid": "1234", "name": "sshd"})
        assert exc_info.value.status_code == 403
        assert "sshd" in exc_info.value.detail

    def test_process_stop_launchd_protected_name_raises_403(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_action_params("process_stop", {"pid": "42", "name": "com.openssh.sshd"})
        assert exc_info.value.status_code == 403

    def test_process_stop_invalid_name_chars_raises_422(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_action_params("process_stop", {"pid": "100", "name": "bad;name"})
        assert exc_info.value.status_code == 422

    def test_process_stop_name_with_star_raises_422(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_action_params("process_stop", {"pid": "100", "name": "my*app"})
        assert exc_info.value.status_code == 422

    def test_process_stop_name_with_space_raises_422(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_action_params("process_stop", {"pid": "100", "name": "my app"})
        assert exc_info.value.status_code == 422

    def test_process_stop_valid_no_name(self):
        # No exception expected
        _validate_action_params("process_stop", {"pid": "123"})

    def test_process_stop_valid_with_safe_name(self):
        # No exception expected
        _validate_action_params("process_stop", {"pid": "123", "name": "python"})

    def test_process_stop_valid_with_complex_safe_name(self):
        # Dots, dashes, underscores are allowed
        _validate_action_params("process_stop", {"pid": "999", "name": "com.acme.myapp"})

    # --- service_* ---

    def test_service_stop_protected_raises_403(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_action_params("service_stop", {"service": "com.apple.sshd"})
        assert exc_info.value.status_code == 403

    def test_service_stop_salt_minion_raises_403(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_action_params("service_stop", {"service": "salt-minion"})
        assert exc_info.value.status_code == 403

    def test_service_stop_safe_service_ok(self):
        # com.acme.myapp -> bare "myapp" -> not protected
        _validate_action_params("service_stop", {"service": "com.acme.myapp"})

    def test_service_stop_nginx_ok(self):
        _validate_action_params("service_stop", {"service": "nginx"})

    def test_service_stop_invalid_chars_raises_422(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_action_params("service_stop", {"service": "bad service!"})
        assert exc_info.value.status_code == 422

    def test_service_stop_empty_service_raises_422(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_action_params("service_stop", {"service": ""})
        assert exc_info.value.status_code == 422

    # --- non-matching action type (no validation applied) ---

    def test_unrecognised_action_type_no_raise(self):
        # Neither process_ nor service_ prefix — pass through unchecked
        _validate_action_params("reboot", {"target": "all"})
