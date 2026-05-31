"""Tests for destructive action approval gate (#291)."""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from fleet_platform.models.pending_action import PendingAction


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
    from datetime import UTC, datetime, timedelta

    from fleet_platform.services.pending_action_svc import approve

    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    action = MagicMock()
    action.status = "pending"
    action.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    result = await approve(db, action)
    assert result.status == "expired"


@pytest.mark.asyncio
async def test_approve_marks_approved():
    from datetime import UTC, datetime, timedelta

    from fleet_platform.services.pending_action_svc import approve

    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    action = MagicMock()
    action.status = "pending"
    action.expires_at = datetime.now(UTC) + timedelta(minutes=10)
    result = await approve(db, action)
    assert result.status == "approved"
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_approve_noop_when_already_approved():
    from fleet_platform.services.pending_action_svc import approve

    db = AsyncMock()
    action = MagicMock()
    action.status = "approved"  # already done
    result = await approve(db, action)
    assert result.status == "approved"
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_reject_marks_rejected():
    from fleet_platform.services.pending_action_svc import reject

    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    action = MagicMock()
    action.status = "pending"
    result = await reject(db, action)
    assert result.status == "rejected"
    db.commit.assert_called_once()


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
    """reject() must not overwrite an already-approved action (audit integrity)."""
    from fleet_platform.services.pending_action_svc import reject
    db = AsyncMock()
    action = MagicMock()
    action.status = "approved"
    result = await reject(db, action)
    assert result.status == "approved"
    db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_reject_noop_when_already_rejected():
    """Idempotent: rejecting an already-rejected action is a no-op."""
    from fleet_platform.services.pending_action_svc import reject
    db = AsyncMock()
    action = MagicMock()
    action.status = "rejected"
    result = await reject(db, action)
    assert result.status == "rejected"
    db.commit.assert_not_called()
