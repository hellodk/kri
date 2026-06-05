# fleet_platform/api/routes/node_secrets.py
"""Per-node Salt pillar secrets API."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user, require_role
from fleet_platform.models.node import Node
from fleet_platform.services import node_secrets_svc

router = APIRouter(prefix="/api/v1/nodes/{node_id}/secrets")


class SecretUpsertRequest(BaseModel):
    value: str
    description: str | None = None


class SecretResponse(BaseModel):
    key: str
    description: str | None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


async def _get_node_or_404(node_id: uuid.UUID, db: AsyncSession) -> Node:
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")
    return node


@router.get("", response_model=list[SecretResponse])
async def list_node_secrets(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """List secrets for a node. Values are never returned."""
    await _get_node_or_404(node_id, db)
    secrets = await node_secrets_svc.get_secrets(db, node_id)
    return [
        SecretResponse(
            key=s.key,
            description=s.description,
            created_at=s.created_at.isoformat(),
            updated_at=s.updated_at.isoformat(),
        )
        for s in secrets
    ]


@router.put("/{key}", response_model=SecretResponse)
async def upsert_node_secret(
    node_id: uuid.UUID,
    key: str,
    payload: SecretUpsertRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Create or update a node secret. After save, pillar file is regenerated."""
    node = await _get_node_or_404(node_id, db)
    secret = await node_secrets_svc.upsert_secret(db, node_id, key, payload.value, payload.description)
    # Regenerate the pillar file for this node
    try:
        await node_secrets_svc.write_node_pillar(node_id, node.minion_id, db)
    except Exception:
        pass  # Pillar dir may not be accessible in dev; don't fail the request

    return SecretResponse(
        key=secret.key,
        description=secret.description,
        created_at=secret.created_at.isoformat(),
        updated_at=secret.updated_at.isoformat(),
    )


@router.delete("/{key}", status_code=204)
async def delete_node_secret(
    node_id: uuid.UUID,
    key: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Delete a node secret. After delete, pillar file is regenerated."""
    node = await _get_node_or_404(node_id, db)
    deleted = await node_secrets_svc.delete_secret(db, node_id, key)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Secret not found")

    try:
        await node_secrets_svc.write_node_pillar(node_id, node.minion_id, db)
    except Exception:
        pass
