"""Tests for #742 — PendingAction.node_id must be nullable (None, not nil-UUID sentinel).

create_proposal with an unresolved or multi-target minion must set node_id=None,
not uuid.UUID(int=0).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from fleet_platform.services.agent_apply_svc import create_proposal

NIL_UUID = uuid.UUID(int=0)


def _make_db(node=None):
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=node)))
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _capture_pending_action(db):
    """Return the PendingAction instance passed to db.add()."""
    assert db.add.called, "db.add was never called — was PendingAction constructed?"
    return db.add.call_args[0][0]


# ---------------------------------------------------------------------------
# Multi-target (comma-separated) → node_id must be None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_proposal_multi_target_node_id_is_none():
    """Multi-target minion_id must produce node_id=None, not nil-UUID."""
    db = _make_db(node=None)

    with (
        patch("fleet_platform.services.agent_apply_svc.assert_live_action_allowed"),
        patch("fleet_platform.services.agent_apply_svc.co_sign_required", return_value=False),
    ):
        await create_proposal(
            db,
            session_id=None,
            actor="operator@example.com",
            tool_name="service_stop",
            args={"minion_id": "host1,host2,host3"},
        )

    action = _capture_pending_action(db)
    assert action.node_id is None, (
        f"Expected node_id=None for multi-target, got {action.node_id!r}. "
        "The nil-UUID sentinel uuid.UUID(int=0) must not be used."
    )
    assert action.node_id != NIL_UUID, "node_id must not be the nil-UUID sentinel"


# ---------------------------------------------------------------------------
# Unresolved single minion (DB returns no Node row) → node_id must be None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_proposal_unresolved_minion_node_id_is_none():
    """Single minion_id that doesn't resolve to a Node row must produce node_id=None."""
    db = _make_db(node=None)  # scalar_one_or_none returns None

    with (
        patch("fleet_platform.services.agent_apply_svc.assert_live_action_allowed"),
        patch("fleet_platform.services.agent_apply_svc.co_sign_required", return_value=False),
    ):
        await create_proposal(
            db,
            session_id=None,
            actor="operator@example.com",
            tool_name="service_stop",
            args={"minion_id": "unknown-host"},
        )

    action = _capture_pending_action(db)
    assert action.node_id is None, (
        f"Expected node_id=None for unresolved minion, got {action.node_id!r}. "
        "The nil-UUID sentinel uuid.UUID(int=0) must not be used."
    )
    assert action.node_id != NIL_UUID, "node_id must not be the nil-UUID sentinel"


# ---------------------------------------------------------------------------
# No minion_id at all → node_id must be None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_proposal_no_minion_id_node_id_is_none():
    """When no minion_id or target is present, node_id must be None."""
    db = _make_db(node=None)

    with (
        patch("fleet_platform.services.agent_apply_svc.assert_live_action_allowed"),
        patch("fleet_platform.services.agent_apply_svc.co_sign_required", return_value=False),
    ):
        await create_proposal(
            db,
            session_id=None,
            actor="operator@example.com",
            tool_name="service_stop",
            args={},
        )

    action = _capture_pending_action(db)
    assert action.node_id is None, f"Expected node_id=None when no minion_id, got {action.node_id!r}."
    assert action.node_id != NIL_UUID, "node_id must not be the nil-UUID sentinel"


# ---------------------------------------------------------------------------
# Resolved single minion → node_id must be the real node's UUID
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_proposal_resolved_minion_node_id_is_real_uuid():
    """When minion resolves to a real Node, node_id must be that node's id."""
    real_uuid = uuid.uuid4()
    mock_node = MagicMock()
    mock_node.id = real_uuid

    db = _make_db(node=mock_node)

    with (
        patch("fleet_platform.services.agent_apply_svc.assert_live_action_allowed"),
        patch("fleet_platform.services.agent_apply_svc.co_sign_required", return_value=False),
    ):
        await create_proposal(
            db,
            session_id=None,
            actor="operator@example.com",
            tool_name="service_stop",
            args={"minion_id": "known-host"},
        )

    action = _capture_pending_action(db)
    assert action.node_id == real_uuid, f"Expected node_id={real_uuid!r}, got {action.node_id!r}"
    assert action.node_id != NIL_UUID, "Real node must not map to nil-UUID"
