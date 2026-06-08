# tests/integration/test_node_action_execution_614.py
"""Integration tests for guarded Salt execution on action approval — #614.

These tests require a live PostgreSQL instance. They are NOT run in the
unit-test gate — they run at merge time or when explicitly invoked:
    pytest tests/integration/test_node_action_execution_614.py
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.asyncio


async def _create_node(db: AsyncSession, minion_id: str) -> "Node":  # noqa: F821
    """Helper: insert a minimal Node row and return it."""
    from fleet_platform.models.node import Node

    node = Node(
        id=uuid.uuid4(),
        minion_id=minion_id,
        hostname=minion_id,
        status="online",
    )
    db.add(node)
    await db.commit()
    await db.refresh(node)
    return node


async def _create_pending_action(
    db: AsyncSession,
    node_id: uuid.UUID,
    action_type: str = "process_stop",
    params: dict | None = None,
    expired: bool = False,
) -> "PendingAction":  # noqa: F821
    """Helper: insert a PendingAction and return it."""
    from fleet_platform.services.pending_action_svc import create_pending_action

    action = await create_pending_action(
        db,
        node_id=node_id,
        action_type=action_type,
        params=params or {"pid": 1234, "name": "python"},
        requested_by="test-operator",
    )
    if expired:
        action.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()
        await db.refresh(action)
    return action


async def test_approve_dispatches_salt_cmd(db: AsyncSession):
    """Happy path: approve a process_stop → status=executed, run_salt_cmd.delay called once."""
    from fleet_platform.api.routes.node_actions import approve_action

    node = await _create_node(db, f"test-node-{uuid.uuid4()}")
    action = await _create_pending_action(db, node.id, "process_stop", {"pid": 9999, "name": "python"})

    mock_task = MagicMock()
    with patch("fleet_platform.workers.salt_tasks.run_salt_cmd") as mock_run:
        mock_run.delay.return_value = mock_task
        result = await approve_action(token=action.approval_token, db=db)

    assert result["status"] == "executed"
    assert "dispatched" in result["message"]
    mock_run.delay.assert_called_once()
    call_kwargs = mock_run.delay.call_args
    assert call_kwargs.kwargs["function"] == "ps.kill_pid"
    assert call_kwargs.kwargs["target_minions"] == [node.minion_id]
    assert "signal=15" in call_kwargs.kwargs["args"]

    await db.refresh(action)
    assert action.status == "executed"


async def test_approve_expired_token_not_dispatched(db: AsyncSession):
    """Expired token → status=expired, Salt never called."""
    from fleet_platform.api.routes.node_actions import approve_action

    node = await _create_node(db, f"test-node-{uuid.uuid4()}")
    action = await _create_pending_action(db, node.id, expired=True)

    with patch("fleet_platform.workers.salt_tasks.run_salt_cmd") as mock_run:
        result = await approve_action(token=action.approval_token, db=db)

    assert result["status"] == "expired"
    mock_run.delay.assert_not_called()


async def test_reject_sets_status_no_dispatch_and_writes_audit(db: AsyncSession):
    """Reject → status=rejected, Salt never called, audit row written."""
    from sqlalchemy import select

    from fleet_platform.api.routes.node_actions import reject_action
    from fleet_platform.models.audit import AuditEvent

    node = await _create_node(db, f"test-node-{uuid.uuid4()}")
    action = await _create_pending_action(db, node.id, "service_stop", {"service": "com.example.nginx"})
    action_id = action.id
    action_type = action.action_type

    with patch("fleet_platform.workers.salt_tasks.run_salt_cmd") as mock_run:
        result = await reject_action(token=action.approval_token, db=db)

    assert result["status"] == "rejected"
    mock_run.delay.assert_not_called()

    await db.refresh(action)
    assert action.status == "rejected"

    # Verify audit row
    audit_rows = (
        (
            await db.execute(
                select(AuditEvent).where(
                    AuditEvent.action == f"{action_type}_rejected",
                    AuditEvent.resource_id == node.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) >= 1
    assert str(action_id) in str(audit_rows[0].new_value)


async def test_approve_protected_target_blocked_at_execution(db: AsyncSession):
    """If a protected target sneaks past request-time check, execution is refused."""
    from fastapi import HTTPException

    from fleet_platform.api.routes.node_actions import approve_action

    node = await _create_node(db, f"test-node-{uuid.uuid4()}")
    # Bypass _validate_action_params by inserting directly with a protected name
    from fleet_platform.models.pending_action import PendingAction as _PA

    action = _PA(
        id=uuid.uuid4(),
        node_id=node.id,
        action_type="process_stop",
        params='{"pid": 1, "name": "sshd"}',
        status="pending",
        requested_by="test",
        approval_token=f"tok-{uuid.uuid4().hex}",
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
        created_at=datetime.now(UTC),
    )
    db.add(action)
    await db.commit()
    await db.refresh(action)

    with patch("fleet_platform.workers.salt_tasks.run_salt_cmd") as mock_run:
        with pytest.raises(HTTPException) as exc_info:
            await approve_action(token=action.approval_token, db=db)

    assert exc_info.value.status_code == 403
    assert "sshd" in exc_info.value.detail
    mock_run.delay.assert_not_called()
