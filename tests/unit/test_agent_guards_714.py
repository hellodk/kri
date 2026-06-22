"""Unit tests for agent live-action guards (#714)."""

from __future__ import annotations

import pytest

from fleet_platform.agent import guards
from fleet_platform.agent.guards import GuardError, assert_live_action_allowed, co_sign_required


def test_protected_service_refused():
    with pytest.raises(GuardError, match="protected"):
        assert_live_action_allowed("restart_service", {"minion_id": "mm9", "service": "sshd"})


def test_protected_service_launchd_label_refused():
    with pytest.raises(GuardError, match="protected"):
        assert_live_action_allowed("restart_service", {"minion_id": "mm9", "service": "com.openssh.sshd"})


def test_salt_minion_refused():
    with pytest.raises(GuardError):
        assert_live_action_allowed("restart_service", {"minion_id": "mm9", "service": "salt-minion"})


def test_planner_self_deplane_refused():
    # mm1 serves the planner tier (default AGENT_PROTECTED_NODES).
    with pytest.raises(GuardError, match="planner"):
        assert_live_action_allowed("restart_service", {"minion_id": "mm1", "service": "nginx"})


def test_normal_action_allowed():
    # Worker minion + ordinary service is fine.
    assert_live_action_allowed("restart_service", {"minion_id": "mm9", "service": "nginx"}) is None


def test_apply_state_on_planner_node_refused():
    with pytest.raises(GuardError, match="planner"):
        assert_live_action_allowed("apply_salt_state", {"minion_id": "mm2", "state": "whatever"})


def test_co_sign_threshold():
    assert co_sign_required(1) is False
    assert co_sign_required(8) is False
    assert co_sign_required(9) is True
    assert co_sign_required(None) is False


def test_protected_nodes_env(monkeypatch):
    # The protected-node set is configurable; mm1/mm2 are the default.
    assert "mm1" in guards.PROTECTED_NODES
    assert "mm2" in guards.PROTECTED_NODES
