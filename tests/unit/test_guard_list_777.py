"""Tests for #777: _DEPLANING_TOOLS must match the registered write-live tool set.

Requirements:
  - 'disable_node' is NOT in _DEPLANING_TOOLS (no such ToolSpec registered).
  - 'bootstrap_node' IS in _DEPLANING_TOOLS (registered write_live).
  - Every registered write_live tool that can take a node offline is guarded.
  - No phantom (unregistered) tool names appear in _DEPLANING_TOOLS.
"""

from __future__ import annotations

from fleet_platform.agent.guards import _DEPLANING_TOOLS
from fleet_platform.agent.tools import build_default_registry


def _registered_write_live_names() -> set[str]:
    return {t.name for t in build_default_registry().all() if t.side_effect == "write_live"}


# ── disable_node must NOT be present ─────────────────────────────────────────


def test_disable_node_not_in_deplaning_tools():
    """disable_node has no ToolSpec; a phantom entry in the guard is a false sense of security."""
    assert "disable_node" not in _DEPLANING_TOOLS


# ── bootstrap_node must be present ───────────────────────────────────────────


def test_bootstrap_node_in_deplaning_tools():
    """bootstrap_node is a registered write_live tool and must be guarded."""
    assert "bootstrap_node" in _DEPLANING_TOOLS


# ── No phantom entries ────────────────────────────────────────────────────────


def test_no_phantom_tools_in_deplaning_set():
    """Every name in _DEPLANING_TOOLS must be a registered tool."""
    registered = _registered_write_live_names()
    phantoms = _DEPLANING_TOOLS - registered
    assert not phantoms, f"Phantom (unregistered) tool names in _DEPLANING_TOOLS: {phantoms}"


# ── All node-affecting write_live tools are guarded ──────────────────────────


def test_all_write_live_tools_in_deplaning_set():
    """Every approval-required live tool must appear in _DEPLANING_TOOLS so the
    protected-node guard fires for each of them.
    """
    live_names = _registered_write_live_names()
    unguarded = live_names - _DEPLANING_TOOLS
    assert not unguarded, f"write_live tools not in _DEPLANING_TOOLS (unguarded): {unguarded}"


# ── Smoke-test: protected node is still refused for guarded tools ─────────────


def test_bootstrap_node_on_protected_node_is_refused():
    import pytest

    from fleet_platform.agent.guards import GuardError, assert_live_action_allowed

    with pytest.raises(GuardError, match="planner"):
        assert_live_action_allowed("bootstrap_node", {"minion_id": "mm1"})
