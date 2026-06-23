"""Tests for destructive action approval gate (#291)."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from fleet_platform.models.pending_action import PendingAction


def _db_with_rowcounts(*rowcounts: int) -> AsyncMock:
    """AsyncMock DB whose successive execute() calls return the given rowcounts.

    approve()/reject() now perform an atomic compare-and-swap UPDATE and branch
    on ``result.rowcount`` (TOCTOU-safe, #644), so tests drive that directly.
    """
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    results = []
    for rc in rowcounts:
        r = MagicMock()
        r.rowcount = rc
        results.append(r)
    db.execute = AsyncMock(side_effect=results)
    return db


def test_forbidden_action_blocked():
    assert PendingAction.is_forbidden("process_kill") is True
    assert PendingAction.is_forbidden("process_stop") is False


def test_destructive_classification():
    assert PendingAction.is_destructive("process_stop") is True
    assert PendingAction.is_destructive("service_disable") is True
    assert PendingAction.is_destructive("service_start") is False
    assert PendingAction.is_destructive("process_resume") is False


@pytest.mark.asyncio
async def test_create_pending_action():
    from fleet_platform.services.pending_action_svc import create_pending_action

    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()

    node_id = uuid.uuid4()
    action = await create_pending_action(
        db,
        node_id=node_id,
        action_type="process_stop",
        params={"pid": 1234},
        requested_by="admin@kri",
    )
    db.add.assert_called_once()
    assert action.action_type == "process_stop"
    assert action.status == "pending"
    assert action.approval_token  # non-empty
    assert action.expires_at > action.created_at


@pytest.mark.asyncio
async def test_expire_does_not_approve_expired():
    """Expired pending action: claim CAS matches 0 rows, then it's settled expired (#644)."""
    from fleet_platform.services.pending_action_svc import approve

    # 1st execute (claim) affects 0 rows; 2nd execute (expire) affects 1 row.
    db = _db_with_rowcounts(0, 1)
    action = MagicMock()
    _, claimed = await approve(db, action)
    assert claimed is False
    assert db.execute.await_count == 2


@pytest.mark.asyncio
async def test_approve_marks_approved():
    """The single caller that wins the pending->approved CAS is claimed=True (#644)."""
    from fleet_platform.services.pending_action_svc import approve

    db = _db_with_rowcounts(1)  # claim wins
    action = MagicMock()
    out, claimed = await approve(db, action)
    assert claimed is True
    assert out is action
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_approve_noop_when_already_approved():
    """A losing/duplicate approve gets claimed=False and never re-dispatches (#644)."""
    from fleet_platform.services.pending_action_svc import approve

    db = _db_with_rowcounts(0, 0)  # claim loses, nothing to expire
    action = MagicMock()
    _, claimed = await approve(db, action)
    assert claimed is False


@pytest.mark.asyncio
async def test_reject_marks_rejected():
    """The caller that wins the pending->rejected CAS is claimed=True (#644)."""
    from fleet_platform.services.pending_action_svc import reject

    db = _db_with_rowcounts(1)
    action = MagicMock()
    out, claimed = await reject(db, action)
    assert claimed is True
    assert out is action
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_get_by_token_returns_none_for_missing():
    from fleet_platform.services.pending_action_svc import get_by_token

    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_by_token(db, "nonexistent-token")
    assert result is None


@pytest.mark.asyncio
async def test_get_by_token_returns_action():
    from fleet_platform.services.pending_action_svc import get_by_token

    db = AsyncMock()
    mock_action = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_action
    db.execute = AsyncMock(return_value=mock_result)

    result = await get_by_token(db, "valid-token")
    assert result is mock_action


@pytest.mark.asyncio
async def test_expire_old_returns_count():
    from fleet_platform.services.pending_action_svc import expire_old

    db = AsyncMock()
    db.commit = AsyncMock()
    mock_result = MagicMock()
    mock_result.rowcount = 3  # type: ignore[attr-defined]
    db.execute = AsyncMock(return_value=mock_result)

    count = await expire_old(db)
    assert count == 3
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_reject_noop_when_already_approved():
    """reject() must not overwrite a non-pending action: CAS matches 0 rows, claimed=False (#644)."""
    from fleet_platform.services.pending_action_svc import reject

    db = _db_with_rowcounts(0)  # already approved → no pending row to transition
    action = MagicMock()
    _, claimed = await reject(db, action)
    assert claimed is False


@pytest.mark.asyncio
async def test_reject_noop_when_already_rejected():
    """Idempotent: rejecting an already-rejected action transitions nothing (claimed=False) (#644)."""
    from fleet_platform.services.pending_action_svc import reject

    db = _db_with_rowcounts(0)
    action = MagicMock()
    _, claimed = await reject(db, action)
    assert claimed is False
