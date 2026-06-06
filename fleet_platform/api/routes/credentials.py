"""CRUD API for the credentials store (#389)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import require_role
from fleet_platform.models.credential import Credential
from fleet_platform.schemas.credential import (
    CredentialCreate,
    CredentialResponse,
    CredentialUpdate,
)
from fleet_platform.services.platform_settings_svc import encrypt_secret

router = APIRouter(prefix="/api/v1/credentials")


@router.get("", response_model=list[CredentialResponse])
async def list_credentials(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Return all stored credentials (without secrets)."""
    result = await db.execute(select(Credential).order_by(Credential.created_at))
    return result.scalars().all()


@router.post("", response_model=CredentialResponse, status_code=201)
async def create_credential(
    payload: CredentialCreate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Store a new credential, encrypting the secret at rest."""
    credential = Credential(
        name=payload.name,
        kind=payload.kind,
        username=payload.username,
        secret_enc=encrypt_secret(payload.secret),
        description=payload.description,
    )
    db.add(credential)
    try:
        await db.commit()
        await db.refresh(credential)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"A credential named {payload.name!r} already exists.",
        )
    return credential


@router.patch("/{credential_id}", response_model=CredentialResponse)
async def update_credential(
    credential_id: uuid.UUID,
    payload: CredentialUpdate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Update an existing credential (all fields optional)."""
    result = await db.execute(select(Credential).where(Credential.id == credential_id))
    credential = result.scalar_one_or_none()
    if credential is None:
        raise HTTPException(status_code=404, detail="Credential not found.")

    if payload.name is not None:
        credential.name = payload.name
    if payload.description is not None:
        credential.description = payload.description
    if payload.username is not None:
        credential.username = payload.username
    if payload.secret is not None:
        credential.secret_enc = encrypt_secret(payload.secret)

    try:
        await db.commit()
        await db.refresh(credential)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"A credential named {payload.name!r} already exists.",
        )
    return credential


@router.delete("/{credential_id}", status_code=204)
async def delete_credential(
    credential_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Delete a credential by ID."""
    result = await db.execute(select(Credential).where(Credential.id == credential_id))
    credential = result.scalar_one_or_none()
    if credential is None:
        raise HTTPException(status_code=404, detail="Credential not found.")
    await db.delete(credential)
    await db.commit()
