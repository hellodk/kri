"""macOS configuration profile management API."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.audit import audit
from fleet_platform.core.auth import get_current_user, require_role
from fleet_platform.models.mobileconfig import ProfileDeploymentLog
from fleet_platform.schemas.mobileconfig import (
    MobileconfigProfileCreate,
    MobileconfigProfileResponse,
    ProfileComplianceResponse,
    ProfileDeployRequest,
)
from fleet_platform.services import mobileconfig_svc

router = APIRouter(prefix="/api/v1/mobileconfig")


# ── Profiles ──────────────────────────────────────────────────────────


@router.post("/profiles", response_model=MobileconfigProfileResponse, status_code=201)
async def create_profile(
    body: MobileconfigProfileCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("admin")),
):
    """Create a new macOS configuration profile (admin only)."""
    profile = await mobileconfig_svc.create_profile(db, body)
    await audit(
        db,
        actor=claims["email"],
        action="mobileconfig.profile.create",
        resource_type="mobileconfig_profile",
        resource_id=profile.id,
        new_value={"name": profile.name},
    )
    await db.commit()
    return profile


@router.get("/profiles", response_model=list[MobileconfigProfileResponse])
async def list_profiles(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """List all macOS configuration profiles."""
    profiles = await mobileconfig_svc.list_profiles(db)
    return profiles


@router.get("/profiles/{profile_id}", response_model=MobileconfigProfileResponse)
async def get_profile(
    profile_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Get a single macOS configuration profile by ID."""
    profile = await mobileconfig_svc.get_profile(db, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.delete("/profiles/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_role("admin")),
):
    """Delete a macOS configuration profile (admin only)."""
    profile = await mobileconfig_svc.get_profile(db, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    await audit(
        db,
        actor=claims["email"],
        action="mobileconfig.profile.delete",
        resource_type="mobileconfig_profile",
        resource_id=profile_id,
        new_value={"name": profile.name},
    )
    await mobileconfig_svc.delete_profile(db, profile_id)


# ── Group Assignment ───────────────────────────────────────────────────


class AssignGroupBody(BaseModel):
    group_id: uuid.UUID


@router.post("/profiles/{profile_id}/assign-group", status_code=201)
async def assign_profile_to_group(
    profile_id: uuid.UUID,
    body: AssignGroupBody,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("admin")),
):
    """Assign a profile to a group (admin only)."""
    profile = await mobileconfig_svc.get_profile(db, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    actor = current_user.get("sub", "unknown")
    assignment = await mobileconfig_svc.assign_to_group(db, profile_id, body.group_id, actor)
    await audit(
        db,
        actor=current_user.get("email", actor),
        action="mobileconfig.profile.assign_group",
        resource_type="mobileconfig_profile",
        resource_id=profile_id,
        new_value={"group_id": str(body.group_id)},
    )
    await db.commit()
    return {
        "id": str(assignment.id),
        "profile_id": str(assignment.profile_id),
        "group_id": str(assignment.group_id),
        "assigned_at": assignment.assigned_at,
    }


# ── Deploy ────────────────────────────────────────────────────────────


@router.post("/profiles/{profile_id}/deploy", status_code=202)
async def deploy_profile(
    profile_id: uuid.UUID,
    body: ProfileDeployRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_role("operator", "admin")),
):
    """Deploy or remove a profile on a set of nodes (operator+).

    Creates a pending deployment log entry for each node and dispatches a
    Celery task to run the Ansible playbook asynchronously.
    """
    from sqlalchemy import select as _select

    from fleet_platform.models.node import Node
    from fleet_platform.workers.celery_app import celery_app

    profile = await mobileconfig_svc.get_profile(db, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    actor = current_user.get("sub", "unknown")
    now = datetime.now(UTC)
    job_ids: list[str] = []

    for node_id in body.node_ids:
        node_result = await db.execute(_select(Node).where(Node.id == node_id))
        node = node_result.scalar_one_or_none()
        if node is None:
            continue

        log = ProfileDeploymentLog(
            profile_id=profile_id,
            node_id=node_id,
            action=body.action,
            status="pending",
            deployed_by=actor,
            deployed_at=now,
        )
        db.add(log)
        await db.flush()  # populate log.id before passing to Celery

        task = celery_app.send_task(
            "fleet_platform.workers.mobileconfig_tasks.deploy_mobileconfig_task",
            kwargs={
                "profile_id": str(profile_id),
                "profile_name": profile.name,
                "profile_payload_xml": profile.payload_xml if body.action == "install" else "",
                "profile_identifier": profile.profile_uuid or "",
                "node_hostname": node.hostname or node.minion_id or str(node.id),
                "action": body.action,
                "log_id": str(log.id),
            },
            queue="maintenance",
        )
        job_ids.append(task.id)

    await audit(
        db,
        actor=current_user.get("email", actor),
        action="mobileconfig.profile.deploy",
        resource_type="mobileconfig_profile",
        resource_id=profile_id,
        new_value={"action": body.action, "node_count": len(job_ids)},
    )
    await db.commit()

    return {
        "profile_id": str(profile_id),
        "action": body.action,
        "node_count": len(body.node_ids),
        "job_ids": job_ids,
        "status": "accepted",
    }


# ── Compliance ────────────────────────────────────────────────────────


@router.get("/profiles/{profile_id}/compliance", response_model=list[ProfileComplianceResponse])
async def get_profile_compliance(
    profile_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Return compliance status per node for a given profile."""
    profile = await mobileconfig_svc.get_profile(db, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    compliance = await mobileconfig_svc.get_compliance(db, profile_id)
    return compliance
