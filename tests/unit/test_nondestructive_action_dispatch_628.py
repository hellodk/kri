"""Unit tests for non-destructive Salt dispatch and service_enable mapping — #628."""

from pathlib import Path

import pytest
from fastapi import HTTPException

from fleet_platform.api.routes.node_actions import _build_salt_invocation

# ---------------------------------------------------------------------------
# _build_salt_invocation — service_enable mapping (#628 addition)
# ---------------------------------------------------------------------------


class TestServiceEnableMapping:
    def test_service_enable_maps_to_service_enable(self):
        fn, args = _build_salt_invocation("service_enable", {"service": "com.x"})
        assert fn == "service.enable"
        assert args == ["com.x"]

    def test_service_enable_args_is_list_with_service_name(self):
        _, args = _build_salt_invocation("service_enable", {"service": "com.example.app"})
        assert isinstance(args, list)
        assert len(args) == 1
        assert args[0] == "com.example.app"


# ---------------------------------------------------------------------------
# Existing mappings still hold after the service_enable addition
# ---------------------------------------------------------------------------


class TestExistingMappingsStillHold:
    def test_service_start_still_maps(self):
        fn, args = _build_salt_invocation("service_start", {"service": "nginx"})
        assert fn == "service.start"
        assert args == ["nginx"]

    def test_service_restart_still_maps(self):
        fn, args = _build_salt_invocation("service_restart", {"service": "nginx"})
        assert fn == "service.restart"
        assert args == ["nginx"]

    def test_service_stop_still_maps(self):
        fn, args = _build_salt_invocation("service_stop", {"service": "nginx"})
        assert fn == "service.stop"
        assert args == ["nginx"]

    def test_service_disable_still_maps(self):
        fn, args = _build_salt_invocation("service_disable", {"service": "com.example.myapp"})
        assert fn == "service.disable"
        assert args == ["com.example.myapp"]

    def test_process_resume_maps_to_sigcont_signal_19(self):
        fn, args = _build_salt_invocation("process_resume", {"pid": 42})
        assert fn == "ps.kill_pid"
        assert args == ["42", "signal=19"]

    def test_unknown_service_action_still_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _build_salt_invocation("service_nuke", {"service": "foo"})
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Source-contract: non-destructive branch in node_actions.py
# ---------------------------------------------------------------------------


class TestNonDestructiveBranchSourceContract:
    """Verify the non-destructive branch actually dispatches via Salt (not a placeholder)."""

    @pytest.fixture(scope="class")
    def source(self):
        src_path = Path(__file__).resolve().parents[2] / "fleet_platform" / "api" / "routes" / "node_actions.py"
        return src_path.read_text()

    def test_run_salt_cmd_delay_present(self, source):
        assert "run_salt_cmd.delay(" in source, "Non-destructive branch must call run_salt_cmd.delay()"

    def test_build_salt_invocation_called_with_payload_action_type(self, source):
        assert "_build_salt_invocation(payload.action_type" in source, (
            "Non-destructive branch must call _build_salt_invocation(payload.action_type, ...)"
        )

    def test_placeholder_comment_removed(self, source):
        assert "actual Salt call TBD" not in source, (
            "Placeholder comment 'actual Salt call TBD' must be removed from non-destructive branch"
        )
