"""Agent apply-with-approval service (#714).

Turns an agent's awaiting-approval live tool into a ``PendingAction``, runs the
co-sign state machine (operator approval, plus an admin co-sign when an action
hits more than ``CO_SIGN_THRESHOLD`` targets), and — on full approval — executes
the tool **as the original operator** so the audit row, not the approver, owns
the change (confused-deputy avoidance).

Status flow:
    pending ──approve(op|admin)──▶ approved ──execute──▶ executing/executed
        │
        └──approve, co_sign_required──▶ awaiting_cosign ──admin co-sign──▶ approved ──▶ …
    pending/awaiting_cosign ──reject──▶ rejected
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.agent.guards import assert_live_action_allowed, co_sign_required
from fleet_platform.models.node import Node
from fleet_platform.models.pending_action import PendingAction

# Agent live actions get a longer approval window than manual node actions (#715).
APPROVAL_TTL = timedelta(hours=4)


class ApprovalError(ValueError):
    """Raised when an approval/co-sign transition is not permitted."""


def _target_count(args: dict) -> int:
    raw = str(args.get("minion_id") or args.get("target") or "")
    if "," in raw:
        return len([p for p in raw.split(",") if p.strip()])
    return 1


async def create_proposal(
    db: AsyncSession,
    *,
    session_id: uuid.UUID | None,
    actor: str,
    tool_name: str,
    args: dict[str, Any],
    dry_run_result: Any = None,
) -> PendingAction:
    """Create a pending agent action. Guards are re-checked here; a guarded
    action raises before any row is written."""
    assert_live_action_allowed(tool_name, args)

    minion_id = str(args.get("minion_id") or args.get("target") or "")
    node = None
    if minion_id and "," not in minion_id:
        node = (await db.execute(_node_q(minion_id))).scalar_one_or_none()
    count = _target_count(args)
    now = datetime.now(UTC)

    action = PendingAction(
        node_id=node.id if node else None,
        action_type=tool_name,
        params=json.dumps(args),
        requested_by=actor,
        status="pending",
        created_at=now,
        expires_at=now + APPROVAL_TTL,
        session_id=session_id,
        proposed_by_agent=True,
        tool_name=tool_name,
        target_count=count,
        dry_run_result=(json.dumps(dry_run_result) if dry_run_result is not None else None),
        co_sign_required=co_sign_required(count),
    )
    db.add(action)
    await db.commit()
    await db.refresh(action)
    return action


def _node_q(minion_id: str):
    from sqlalchemy import select

    return select(Node).where(Node.minion_id == minion_id)


async def approve_proposal(
    db: AsyncSession,
    action: PendingAction,
    *,
    approver_email: str,
    approver_role: str,
) -> dict[str, Any]:
    """Advance the co-sign state machine; execute when fully approved."""
    # Re-fetch under a row-level lock to serialise concurrent approve requests
    # and prevent TOCTOU double-execution / co-sign bypass (#735).
    locked: PendingAction | None = (
        await db.execute(select(PendingAction).where(PendingAction.id == action.id).with_for_update())
    ).scalar_one_or_none()
    if locked is None:
        raise ApprovalError("action not found")
    action = locked

    now = datetime.now(UTC)
    if action.status in ("executed", "executing", "rejected", "failed", "expired"):
        raise ApprovalError(f"action is already {action.status}")
    if action.expires_at and action.expires_at < now:
        action.status = "expired"
        await db.commit()
        raise ApprovalError("approval window has expired")

    if action.status == "pending":
        # Separation-of-duties: the person who requested (or triggered) an action
        # must not be able to approve it themselves (#772).
        if approver_email == action.requested_by:
            raise ApprovalError("approver must differ from the action requester; self-approval is not permitted")
        action.approved_by = approver_email
        action.approved_at = now
        if action.co_sign_required:
            action.status = "awaiting_cosign"
            await db.commit()
            return {"status": "awaiting_cosign", "message": "First approval recorded; an admin must co-sign."}
        action.status = "approved"
        await db.commit()
        return await _execute(db, action)

    if action.status == "awaiting_cosign":
        # Co-sign must be a *different* human and an admin (#714, #716 d5/d6).
        if approver_role != "admin":
            raise ApprovalError("co-sign requires an admin")
        if approver_email == action.approved_by:
            raise ApprovalError("co-sign must be a different person than the first approver")
        action.co_signed_by = approver_email
        action.co_signed_at = now
        action.status = "approved"
        await db.commit()
        return await _execute(db, action)

    raise ApprovalError(f"cannot approve action in status {action.status!r}")


async def reject_proposal(db: AsyncSession, action: PendingAction, *, approver_email: str) -> dict[str, Any]:
    # Re-fetch under a row-level lock to serialise concurrent reject/approve requests (#735).
    locked: PendingAction | None = (
        await db.execute(select(PendingAction).where(PendingAction.id == action.id).with_for_update())
    ).scalar_one_or_none()
    if locked is None:
        raise ApprovalError("action not found")
    action = locked
    if action.status in ("executed", "executing", "failed"):
        raise ApprovalError(f"action is already {action.status}")
    action.status = "rejected"
    await db.commit()
    return {"status": "rejected"}


async def _execute(db: AsyncSession, action: PendingAction) -> dict[str, Any]:
    """Run the approved tool as the ORIGINAL operator (action.requested_by)."""
    from fleet_platform.agent.audit import audit_tool_dispatch
    from fleet_platform.agent.executor import Executor
    from fleet_platform.agent.registry import ToolCtx
    from fleet_platform.agent.tools import build_default_registry

    args = json.loads(action.params or "{}")
    executor = Executor(
        build_default_registry(),
        audit_hook=audit_tool_dispatch,
        guard_hook=assert_live_action_allowed,
    )
    ctx = ToolCtx(
        actor=action.requested_by,  # confused-deputy guarantee: the human owns the change
        role="operator",
        db=db,
        session_id=action.session_id,
    )
    action.status = "executing"
    await db.commit()

    result = await executor.dispatch_approved(action.tool_name or action.action_type, args, ctx)
    action.status = "executed" if result.ok else "failed"
    action.executed_at = datetime.now(UTC)
    await db.commit()
    return {
        "status": action.status,
        "tool": action.tool_name,
        "ok": result.ok,
        "result": result.result,
        "error": result.error,
        "executed_as": action.requested_by,
    }
