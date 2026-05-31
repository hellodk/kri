"""HTTP endpoints for destructive node action approval gate (#291)."""
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.audit import audit
from fleet_platform.core.auth import require_role
from fleet_platform.models.node import Node
from fleet_platform.models.pending_action import PendingAction
from fleet_platform.services import pending_action_svc

router = APIRouter(prefix="/api/v1/nodes", tags=["node-actions"])
actions_router = APIRouter(prefix="/api/v1/actions", tags=["node-actions"])


class NodeActionRequest(BaseModel):
    action_type: str
    params: dict = {}


class PendingActionResponse(BaseModel):
    id: uuid.UUID
    node_id: uuid.UUID
    action_type: str
    status: str
    expires_at: datetime
    message: str

    model_config = {"from_attributes": True}


@router.post("/{node_id}/actions", response_model=PendingActionResponse, status_code=202)
async def request_node_action(
    node_id: uuid.UUID,
    payload: NodeActionRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Request a node action. Destructive actions are gated behind email approval."""
    if PendingAction.is_forbidden(payload.action_type):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Action '{payload.action_type}' is not permitted. "
                "Remote force-kill is disabled for safety. Use the service manager or SSH."
            ),
        )

    node_result = await db.execute(select(Node).where(Node.id == node_id))
    node = node_result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    if not PendingAction.is_destructive(payload.action_type):
        # Non-destructive: execute immediately (placeholder — actual Salt call TBD)
        await audit(
            db,
            actor=claims["sub"],
            action=payload.action_type,
            resource_type="node",
            resource_id=node_id,
            new_value=payload.params,
        )
        return PendingActionResponse(
            id=uuid.uuid4(),
            node_id=node_id,
            action_type=payload.action_type,
            status="executed",
            expires_at=datetime.now(UTC),
            message=f"Action '{payload.action_type}' queued for execution.",
        )

    action = await pending_action_svc.create_pending_action(
        db,
        node_id=node_id,
        action_type=payload.action_type,
        params=payload.params,
        requested_by=claims["sub"],
    )

    # Send approval email (non-blocking — failure must not block the response)
    try:
        await pending_action_svc._send_approval_email(action, node, claims["sub"])
    except Exception:
        pass  # email failure must not block

    await audit(
        db,
        actor=claims["sub"],
        action=f"{payload.action_type}_requested",
        resource_type="node",
        resource_id=node_id,
        new_value={"action_id": str(action.id), "params": payload.params},
    )

    return PendingActionResponse(
        id=action.id,
        node_id=action.node_id,
        action_type=action.action_type,
        status=action.status,
        expires_at=action.expires_at,
        message="Approval email sent. Action will expire in 15 minutes.",
    )


@actions_router.get("/{token}/approve")
async def approve_action(token: str, db: AsyncSession = Depends(get_db)):
    """Approve a pending destructive action via the emailed approval link."""
    action = await pending_action_svc.get_by_token(db, token)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    action = await pending_action_svc.approve(db, action)
    if action.status == "expired":
        return {"status": "expired", "message": "This approval link has expired."}
    if action.status == "approved":
        # TODO: dispatch actual Salt execution
        return {"status": "approved", "message": f"Action '{action.action_type}' approved and queued."}
    return {"status": action.status}


@actions_router.get("/{token}/reject")
async def reject_action(token: str, db: AsyncSession = Depends(get_db)):
    """Reject a pending destructive action via the emailed rejection link."""
    action = await pending_action_svc.get_by_token(db, token)
    if not action:
        raise HTTPException(status_code=404, detail="Action not found")
    action = await pending_action_svc.reject(db, action)
    return {"status": "rejected", "message": "Action rejected."}
