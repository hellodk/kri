"""CRUD API for the credentials store (#389), with node/group linkage (#704)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.audit import audit
from fleet_platform.core.auth import require_role
from fleet_platform.models.credential import Credential
from fleet_platform.schemas.credential import (
    CredentialCreate,
    CredentialResponse,
    CredentialUpdate,
)
from fleet_platform.services.credential_group_svc import (
    count_groups_for_credential,
    count_nodes_for_credential,
)
from fleet_platform.services.credential_resolver import nodes_using_credential
from fleet_platform.services.platform_settings_svc import encrypt_secret

router = APIRouter(prefix="/api/v1/credentials")


async def _reference_counts(credential_id: uuid.UUID, db: AsyncSession) -> tuple[int, int]:
    """Return ``(node_count, group_count)`` of references.

    #985 Phase 2b: group references, and the nodes covered by them, are counted
    via the ``credential_groups`` association — the source of truth for group
    credential links — rather than the legacy ``Group.credential_id`` column.
    """
    group_fk_count = await count_groups_for_credential(db, credential_id)
    node_fk_count = await count_nodes_for_credential(db, credential_id)
    return node_fk_count, group_fk_count


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


@router.get("/{credential_id}/nodes")
async def credential_nodes(
    credential_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Nodes whose *resolved* SSH credential is this one (#700).

    Resolution-aware reverse lookup for rotation/audit — read-only, no targeting
    semantics. ``source`` is ``'node'`` (direct FK) or ``'group:<name>'``.
    """
    result = await db.execute(select(Credential).where(Credential.id == credential_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Credential not found.")

    pairs = await nodes_using_credential(credential_id, db)
    nodes = [
        {
            "id": str(node.id),
            "minion_id": node.minion_id,
            "hostname": node.hostname,
            "source": source,
        }
        for node, source in pairs
    ]
    return {"credential_id": str(credential_id), "count": len(nodes), "nodes": nodes}


@router.delete("/{credential_id}", status_code=204)
async def delete_credential(
    credential_id: uuid.UUID,
    force: bool = Query(default=False),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("operator", "admin")),
):
    """Delete a credential by ID.

    Guarded (#726): if nodes or groups still reference the credential, returns
    409 unless ``?force=true`` is passed. ``ON DELETE SET NULL`` then nulls the
    referencing FKs. Always writes an audit record.
    """
    result = await db.execute(select(Credential).where(Credential.id == credential_id))
    credential = result.scalar_one_or_none()
    if credential is None:
        raise HTTPException(status_code=404, detail="Credential not found.")

    node_count, group_count = await _reference_counts(credential_id, db)
    total = node_count + group_count
    if total and not force:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Credential is in use by {node_count} node(s) and {group_count} group(s). "
                f"Reassign them or pass ?force=true to delete and detach (FKs set to NULL)."
            ),
        )

    await audit(
        db,
        actor=claims["email"],
        action="credential.delete" + (".force" if force and total else ""),
        resource_type="credential",
        resource_id=credential_id,
        old_value={"name": credential.name, "node_refs": node_count, "group_refs": group_count},
    )
    await db.delete(credential)
    await db.commit()
