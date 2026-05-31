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
    action.expires_at = datetime.now(UTC) - timedelta(minutes=1)  # already expired
    result = await approve(db, action)
    assert result.status == "expired"
