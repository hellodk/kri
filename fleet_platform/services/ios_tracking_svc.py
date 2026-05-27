"""iOS-specific tracking service: Xcode/macOS versions, certs, Jenkins agents."""

from __future__ import annotations

import json
import urllib.request
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.models.ios_tracking import Certificate, JenkinsAgent
from fleet_platform.models.node import Node

if TYPE_CHECKING:
    pass


async def update_node_from_grains(node_id: uuid.UUID, grains: dict, db: AsyncSession) -> None:
    """Extract iOS-relevant fields from Salt grains and update the Node row."""
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        return

    # macOS version
    macos_ver = grains.get("osrelease")
    if macos_ver:
        node.macos_version = str(macos_ver)  # type: ignore[attr-defined]

    # Xcode version: try grain key first, then brew_pkgs
    xcode_ver = grains.get("xcode_version")
    if not xcode_ver:
        brew_pkgs = grains.get("brew_pkgs", {})
        if isinstance(brew_pkgs, dict):
            xcode_ver = brew_pkgs.get("xcode-select", "")
    if xcode_ver:
        node.xcode_version = str(xcode_ver)  # type: ignore[attr-defined]


async def check_jenkins_agent(agent_id: uuid.UUID, db: AsyncSession) -> None:
    """Poll Jenkins API for agent online status and update the row."""
    result = await db.execute(select(JenkinsAgent).where(JenkinsAgent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        return

    try:
        url = f"{agent.jenkins_url.rstrip('/')}/computer/{agent.agent_name}/api/json?tree=offline"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:  # nosec B310
            data = json.loads(resp.read())
        if data.get("offline") is False:
            agent.status = "online"
        else:
            agent.status = "offline"
    except Exception:
        agent.status = "unknown"

    agent.last_checked_at = datetime.now(UTC)
    await db.commit()


async def get_expiring_certs(db: AsyncSession, days: int = 30) -> list[Certificate]:
    """Return certs expiring within the given number of days."""
    cutoff = date.today() + timedelta(days=days)
    result = await db.execute(
        select(Certificate).where(Certificate.expiry_date <= cutoff).order_by(Certificate.expiry_date)
    )
    return list(result.scalars().all())
