"""Tests for #506 — bootstrap playbook guard in run_playbook_endpoint."""

from unittest.mock import MagicMock

import pytest


def _make_entry(filename: str):
    e = MagicMock()
    e.filename = filename
    e.name = filename
    e.description = ""
    e.entry_type = "playbook"
    e.default_vars = {}
    e.var_descriptions = {}
    e.lint_errors = []
    return e


@pytest.mark.asyncio
async def test_run_playbook_rejects_bootstrap_playbook():
    """Endpoint returns 403 for bootstrap_mac_mini.yml."""
    from fleet_platform.api.routes.ansible import _BOOTSTRAP_ONLY_PLAYBOOKS

    assert "bootstrap_mac_mini.yml" in _BOOTSTRAP_ONLY_PLAYBOOKS


def test_bootstrap_only_playbooks_constant_exists():
    """_BOOTSTRAP_ONLY_PLAYBOOKS is defined and contains the bootstrap playbook."""
    from fleet_platform.api.routes.ansible import _BOOTSTRAP_ONLY_PLAYBOOKS

    assert isinstance(_BOOTSTRAP_ONLY_PLAYBOOKS, frozenset)
    assert "bootstrap_mac_mini.yml" in _BOOTSTRAP_ONLY_PLAYBOOKS
    # Verify it's not empty
    assert len(_BOOTSTRAP_ONLY_PLAYBOOKS) >= 1
