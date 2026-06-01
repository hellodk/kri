"""macOS configuration profile management API."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
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
    _: dict = Depends(require_role("admin")),
):
    """Create a new macOS configuration profile (admin only)."""
    profile = await mobileconfig_svc.create_profile(db, body)
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
    _: dict = Depends(require_role("admin")),
):
    """Delete a macOS configuration profile (admin only)."""
    profile = await mobileconfig_svc.get_profile(db, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
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
    assignment = await mobileconfig_svc.assign_to_group(
        db, profile_id, body.group_id, actor
    )
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

    Creates a pending deployment log entry for each node. The actual Ansible
    execution is handled asynchronously by the Automation Hub worker.
    """
    profile = await mobileconfig_svc.get_profile(db, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")

    actor = current_user.get("sub", "unknown")
    now = datetime.now(UTC)
    log_ids: list[str] = []

    for node_id in body.node_ids:
        log = ProfileDeploymentLog(
            profile_id=profile_id,
            node_id=node_id,
            action=body.action,
            status="pending",
            deployed_by=actor,
            deployed_at=now,
        )
        db.add(log)
        log_ids.append(str(log.id) if log.id else "pending")

    await db.commit()

    return {
        "profile_id": str(profile_id),
        "action": body.action,
        "node_count": len(body.node_ids),
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
