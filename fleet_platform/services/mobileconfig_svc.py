"""Service layer for macOS configuration profile management."""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.group import GroupMember
from fleet_platform.models.mobileconfig import (
    MobileconfigProfile,
    ProfileDeploymentLog,
    ProfileGroupAssignment,
)
from fleet_platform.models.node import Node
from fleet_platform.schemas.mobileconfig import MobileconfigProfileCreate


def extract_profile_uuid(payload_xml: str) -> str | None:
    """Parse PayloadUUID from a .mobileconfig plist XML string.

    Returns the UUID string if found, None otherwise (including on parse errors).
    """
    try:
        root = ET.fromstring(payload_xml)  # nosec B314 — input is operator-supplied mobileconfig plist, not user-controlled
    except ET.ParseError:
        return None

    # Plist structure: <plist><dict><key>PayloadUUID</key><string>...</string>...
    # Walk all <dict> elements at any depth to handle nested plists.
    for elem in root.iter("dict"):
        children = list(elem)
        for i, child in enumerate(children):
            if child.tag == "key" and child.text == "PayloadUUID":
                # The value is the *next* sibling element
                if i + 1 < len(children) and children[i + 1].tag == "string":
                    value = children[i + 1].text
                    if value:
                        return value
    return None


async def create_profile(
    db: AsyncSession,
    payload: MobileconfigProfileCreate,
) -> MobileconfigProfile:
    """Extract PayloadUUID from XML and persist a new profile."""
    now = datetime.now(UTC)
    profile_uuid = extract_profile_uuid(payload.payload_xml)
    profile = MobileconfigProfile(
        name=payload.name,
        description=payload.description,
        payload_xml=payload.payload_xml,
        profile_uuid=profile_uuid,
        version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


async def list_profiles(db: AsyncSession) -> list[MobileconfigProfile]:
    """Return all profiles ordered by creation date descending."""
    result = await db.execute(select(MobileconfigProfile).order_by(MobileconfigProfile.created_at.desc()))
    return list(result.scalars().all())


async def get_profile(
    db: AsyncSession,
    profile_id: uuid.UUID,
) -> MobileconfigProfile | None:
    """Return a single profile by ID, or None if not found."""
    result = await db.execute(select(MobileconfigProfile).where(MobileconfigProfile.id == profile_id))
    return result.scalar_one_or_none()


async def delete_profile(db: AsyncSession, profile_id: uuid.UUID) -> None:
    """Delete a profile and cascade to assignments and logs."""
    result = await db.execute(select(MobileconfigProfile).where(MobileconfigProfile.id == profile_id))
    profile = result.scalar_one_or_none()
    if profile is not None:
        await db.delete(profile)
        await db.commit()


async def assign_to_group(
    db: AsyncSession,
    profile_id: uuid.UUID,
    group_id: uuid.UUID,
    actor: str,
) -> ProfileGroupAssignment:
    """Assign a profile to a group (idempotent — returns existing if already assigned)."""
    # Check if already assigned
    existing = await db.execute(
        select(ProfileGroupAssignment).where(
            ProfileGroupAssignment.profile_id == profile_id,
            ProfileGroupAssignment.group_id == group_id,
        )
    )
    assignment = existing.scalar_one_or_none()
    if assignment is not None:
        return assignment

    assignment = ProfileGroupAssignment(
        profile_id=profile_id,
        group_id=group_id,
        assigned_at=datetime.now(UTC),
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    return assignment


async def get_compliance(
    db: AsyncSession,
    profile_id: uuid.UUID,
) -> list[dict]:
    """Return compliance status per node across all groups assigned to this profile.

    For each node that belongs to a group assigned to this profile, returns the
    latest deployment log status.  Nodes with no deployment log get status 'unknown'.
    """
    # Find all groups assigned to this profile
    groups_result = await db.execute(
        select(ProfileGroupAssignment.group_id).where(ProfileGroupAssignment.profile_id == profile_id)
    )
    group_ids = [row[0] for row in groups_result.all()]

    if not group_ids:
        return []

    # Find all nodes in those groups
    nodes_result = await db.execute(
        select(Node)
        .join(GroupMember, GroupMember.node_id == Node.id)
        .where(GroupMember.group_id.in_(group_ids))
        .distinct()
    )
    nodes = list(nodes_result.scalars().all())

    compliance = []
    for node in nodes:
        # Get the latest deployment log for this node+profile
        log_result = await db.execute(
            select(ProfileDeploymentLog)
            .where(
                ProfileDeploymentLog.profile_id == profile_id,
                ProfileDeploymentLog.node_id == node.id,
            )
            .order_by(ProfileDeploymentLog.deployed_at.desc())
            .limit(1)
        )
        log = log_result.scalar_one_or_none()

        if log is None:
            status = "unknown"
            last_deployed_at = None
        elif log.action == "install" and log.status == "success":
            status = "installed"
            last_deployed_at = log.deployed_at
        elif log.action == "remove" and log.status == "success":
            status = "not_installed"
            last_deployed_at = log.deployed_at
        elif log.status == "pending":
            status = "pending"
            last_deployed_at = log.deployed_at
        elif log.status == "failed":
            status = "failed"
            last_deployed_at = log.deployed_at
        else:
            status = "unknown"
            last_deployed_at = log.deployed_at

        compliance.append(
            {
                "profile_id": profile_id,
                "node_id": node.id,
                "node_hostname": node.hostname,
                "status": status,
                "last_deployed_at": last_deployed_at,
            }
        )

    return compliance
