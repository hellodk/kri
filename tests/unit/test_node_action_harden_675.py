"""Unit tests for the guarded compute-harden / unharden node action — #675.

Covers the three pieces the feature adds:
  * Salt invocation mapping  (harden -> state.apply base.harden_compute, and inverse)
  * Approval classification   (harden is destructive/gated; unharden executes immediately)
  * Param validation          (node-wide actions take no per-target params)
"""

import pytest
from fastapi import HTTPException

from fleet_platform.api.routes.node_actions import (
    _build_salt_invocation,
    _validate_action_params,
)
from fleet_platform.models.pending_action import PendingAction

# ---------------------------------------------------------------------------
# _build_salt_invocation — harden / unharden mapping
# ---------------------------------------------------------------------------


class TestHardenSaltMapping:
    def test_harden_maps_to_state_apply_harden_compute(self):
        fn, args = _build_salt_invocation("harden", {})
        assert fn == "state.apply"
        assert args == ["base.harden_compute"]

    def test_unharden_maps_to_state_apply_unharden_compute(self):
        fn, args = _build_salt_invocation("unharden", {})
        assert fn == "state.apply"
        assert args == ["base.unharden_compute"]

    def test_mapping_ignores_extraneous_params(self):
        # Node-wide actions ignore params; presence of junk must not change the call.
        fn, args = _build_salt_invocation("harden", {"service": "nginx", "pid": "1"})
        assert (fn, args) == ("state.apply", ["base.harden_compute"])


# ---------------------------------------------------------------------------
# Approval classification
# ---------------------------------------------------------------------------


class TestHardenClassification:
    def test_harden_is_destructive(self):
        # harden disables a service set -> must go through the email approval gate.
        assert PendingAction.is_destructive("harden") is True

    def test_unharden_is_not_destructive(self):
        # unharden is the recovery path -> executes immediately, no approval friction.
        assert PendingAction.is_destructive("unharden") is False

    def test_harden_is_not_forbidden(self):
        assert PendingAction.is_forbidden("harden") is False
        assert PendingAction.is_forbidden("unharden") is False


# ---------------------------------------------------------------------------
# Param validation — node-wide actions take no per-target params
# ---------------------------------------------------------------------------


class TestHardenValidation:
    def test_harden_validation_passes_with_empty_params(self):
        # Must not raise — there is no per-target denylist check for node-wide actions.
        _validate_action_params("harden", {})

    def test_unharden_validation_passes_with_empty_params(self):
        _validate_action_params("unharden", {})

    def test_harden_validation_ignores_arbitrary_params(self):
        # Even a protected-looking name in params must not raise: harden has no target.
        _validate_action_params("harden", {"service": "sshd"})


# ---------------------------------------------------------------------------
# Regression: existing process/service mappings still raise on unknowns
# ---------------------------------------------------------------------------


class TestUnknownActionStillRaises:
    def test_unknown_action_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _build_salt_invocation("obliterate", {})
        assert exc_info.value.status_code == 400
