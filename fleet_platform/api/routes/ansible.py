# fleet_platform/api/routes/ansible.py
import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import hash_password, require_role
from fleet_platform.models.node import Node
from fleet_platform.schemas.ansible import BootstrapRequest, BootstrapResponse
from fleet_platform.workers.ansible_tasks import bootstrap_node

router = APIRouter(prefix="/api/v1/ansible")


@router.post("/bootstrap", response_model=BootstrapResponse, status_code=202)
async def bootstrap(
    payload: BootstrapRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    result = await db.execute(
        select(Node).where(Node.minion_id == payload.minion_id)
    )
    node = result.scalar_one_or_none()

    if node and node.bootstrap_status == "bootstrapping":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Node is already being bootstrapped",
        )

    placeholder_token = secrets.token_urlsafe(32)

    if node is None:
        node = Node(
            minion_id=payload.minion_id,
            hostname=payload.minion_id.split(".")[0],
            ip_address=payload.target_ip,
            status="unknown",
            drift_score=0,
            node_token_hash=hash_password(placeholder_token),
            first_seen_at=datetime.now(UTC),
            bootstrap_status="pending",
            bootstrap_ip=payload.target_ip,
        )
        db.add(node)
        await db.commit()
        await db.refresh(node)
    else:
        node.bootstrap_status = "pending"
        node.bootstrap_ip = payload.target_ip
        await db.commit()

    task = bootstrap_node.delay(str(node.id), payload.target_ip)

    return BootstrapResponse(
        node_id=node.id,
        minion_id=node.minion_id,
        job_id=task.id,
        bootstrap_status="pending",
        message="Bootstrap queued. Node will appear in fleet once Salt minion connects.",
    )


@router.get("/bootstrap/{node_id}/status")
async def bootstrap_status(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return {
        "node_id": str(node.id),
        "minion_id": node.minion_id,
        "bootstrap_status": node.bootstrap_status,
        "bootstrap_ip": node.bootstrap_ip,
        "bootstrap_error": node.bootstrap_error,
    }
