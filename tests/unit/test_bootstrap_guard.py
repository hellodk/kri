"""Tests for #506 — bootstrap playbook guard in run_playbook_endpoint.

Converted from vacuous source-grep tests to behavioural tests (#580):
  - test_run_playbook_rejects_bootstrap_playbook: actually calls the endpoint
    and asserts HTTP 403, so deleting the guard would make this test fail.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

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
    """Endpoint raises HTTP 403 for bootstrap_node.yml (not just grep check).

    This test will FAIL if the guard
    is removed — it calls the real route handler, not just inspects source.
    """
    from fastapi import HTTPException

    from fleet_platform.api.routes.ansible import run_playbook_endpoint

    payload = MagicMock()
    payload.playbook = "bootstrap_node.yml"
    payload.target_type = "node"
    payload.target_id = str(uuid.uuid4())
    payload.extravars = None
    payload.verbosity = 0
    payload.timeout_seconds = 300
    payload.ssh_username = None

    # Build a mock DB that returns bootstrap_node.yml from discover_all
    db = AsyncMock()
    # db.execute for PlatformSetting (sources) — return no sources
    mock_sources_result = MagicMock()
    mock_sources_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_sources_result)

    claims = {"sub": str(uuid.uuid4()), "email": "test@kri", "role": "operator"}

    with patch(
        # #750: run_playbook_endpoint (and its discover_all call) lives in the
        # playbooks sub-module now; patch it where it is used.
        "fleet_platform.api.routes.ansible.playbooks.discover_all",
        return_value=[_make_entry("bootstrap_node.yml")],
    ):
        with pytest.raises(HTTPException) as exc_info:
            await run_playbook_endpoint(payload=payload, db=db, claims=claims)

    assert exc_info.value.status_code == 403, "Bootstrap guard must return 403, not allow the playbook through"


def test_bootstrap_only_playbooks_constant_exists():
    """_BOOTSTRAP_ONLY_PLAYBOOKS is defined and contains the bootstrap playbook."""
    from fleet_platform.api.routes.ansible import _BOOTSTRAP_ONLY_PLAYBOOKS

    assert isinstance(_BOOTSTRAP_ONLY_PLAYBOOKS, frozenset)
    assert "bootstrap_node.yml" in _BOOTSTRAP_ONLY_PLAYBOOKS
    # Verify it's not empty
    assert len(_BOOTSTRAP_ONLY_PLAYBOOKS) >= 1
