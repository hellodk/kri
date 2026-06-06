# fleet_platform/api/routes/group_secrets.py
"""Group-scoped Salt pillar secrets API."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user, require_role
from fleet_platform.models.group import Group
from fleet_platform.services import group_secrets_svc

router = APIRouter(prefix="/api/v1/groups/{group_id}/secrets")


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


async def _get_group_or_404(group_id: uuid.UUID, db: AsyncSession) -> Group:
    result = await db.execute(select(Group).where(Group.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return group


@router.get("", response_model=list[SecretResponse])
async def list_group_secrets(
    group_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    await _get_group_or_404(group_id, db)
    secrets = await group_secrets_svc.get_secrets(db, group_id)
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
async def upsert_group_secret(
    group_id: uuid.UUID,
    key: str,
    payload: SecretUpsertRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    await _get_group_or_404(group_id, db)
    secret = await group_secrets_svc.upsert_secret(db, group_id, key, payload.value, payload.description)
    try:
        await group_secrets_svc.write_group_pillar(group_id, db)
        await group_secrets_svc.rebuild_top_sls(db)
    except Exception:
        pass

    return SecretResponse(
        key=secret.key,
        description=secret.description,
        created_at=secret.created_at.isoformat(),
        updated_at=secret.updated_at.isoformat(),
    )


@router.delete("/{key}", status_code=204)
async def delete_group_secret(
    group_id: uuid.UUID,
    key: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    await _get_group_or_404(group_id, db)
    deleted = await group_secrets_svc.delete_secret(db, group_id, key)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Secret not found")

    try:
        await group_secrets_svc.write_group_pillar(group_id, db)
        await group_secrets_svc.rebuild_top_sls(db)
    except Exception:
        pass
