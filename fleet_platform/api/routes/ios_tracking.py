"""iOS fleet tracking API: certs, Jenkins agents, Xcode/macOS versions."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user, require_role
from fleet_platform.models.ios_tracking import Certificate, JenkinsAgent
from fleet_platform.models.node import Node

router = APIRouter(prefix="/api/v1/ios")


# ── Schemas ───────────────────────────────────────────────────────────


class AddCertBody(BaseModel):
    name: str
    cert_type: str
    team_id: str | None = None
    expiry_date: date
    fingerprint: str | None = None


class UpsertJenkinsBody(BaseModel):
    jenkins_url: str
    agent_name: str


# ── Helpers ───────────────────────────────────────────────────────────


def _cert_out(c: Certificate) -> dict:
    return {
        "id": str(c.id),
        "node_id": str(c.node_id),
        "name": c.name,
        "cert_type": c.cert_type,
        "team_id": c.team_id,
        "expiry_date": c.expiry_date.isoformat() if c.expiry_date else None,
        "fingerprint": c.fingerprint,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }


def _agent_out(a: JenkinsAgent) -> dict:
    return {
        "id": str(a.id),
        "node_id": str(a.node_id),
        "jenkins_url": a.jenkins_url,
        "agent_name": a.agent_name,
        "status": a.status,
        "last_checked_at": a.last_checked_at,
        "created_at": a.created_at,
    }


# ── Fleet Overview ────────────────────────────────────────────────────


@router.get("/nodes")
async def list_ios_nodes(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """All nodes with xcode/macos versions, jenkins status, cert counts."""
    result = await db.execute(select(Node))
    nodes = result.scalars().all()

    items = []
    for node in nodes:
        # Cert count and next expiry
        cert_result = await db.execute(
            select(func.count(), func.min(Certificate.expiry_date)).where(Certificate.node_id == node.id)
        )
        cert_count, next_expiry = cert_result.one()

        # Jenkins agent
        agent_result = await db.execute(select(JenkinsAgent).where(JenkinsAgent.node_id == node.id))
        agent = agent_result.scalar_one_or_none()

        items.append(
            {
                "node_id": str(node.id),
                "minion_id": node.minion_id,
                "hostname": node.hostname,
                "status": node.status,
                "macos_version": node.macos_version,
                "xcode_version": node.xcode_version,
                "cert_count": cert_count or 0,
                "next_cert_expiry": next_expiry.isoformat() if next_expiry else None,
                "jenkins_status": agent.status if agent else None,
            }
        )

    return {"items": items, "total": len(items)}


@router.get("/nodes/{node_id}")
async def get_ios_node_detail(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Detail for one node: full cert list, jenkins agent info, xcode/macos versions."""
    result = await db.execute(select(Node).where(Node.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    # Certs
    certs_result = await db.execute(
        select(Certificate).where(Certificate.node_id == node_id).order_by(Certificate.expiry_date)
    )
    certs = certs_result.scalars().all()

    # Jenkins agent
    agent_result = await db.execute(select(JenkinsAgent).where(JenkinsAgent.node_id == node_id))
    agent = agent_result.scalar_one_or_none()

    return {
        "node_id": str(node.id),
        "minion_id": node.minion_id,
        "hostname": node.hostname,
        "status": node.status,
        "macos_version": node.macos_version,
        "xcode_version": node.xcode_version,
        "certificates": [_cert_out(c) for c in certs],
        "jenkins_agent": _agent_out(agent) if agent else None,
    }


# ── Certificates ──────────────────────────────────────────────────────


@router.post("/nodes/{node_id}/certificates", status_code=201)
async def add_certificate(
    node_id: uuid.UUID,
    body: AddCertBody,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    result = await db.execute(select(Node).where(Node.id == node_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Node not found")

    now = datetime.now(UTC)
    cert = Certificate(
        node_id=node_id,
        name=body.name,
        cert_type=body.cert_type,
        team_id=body.team_id,
        expiry_date=body.expiry_date,
        fingerprint=body.fingerprint,
        created_at=now,
        updated_at=now,
    )
    db.add(cert)
    await db.commit()
    return _cert_out(cert)


@router.delete("/certificates/{cert_id}", status_code=204)
async def delete_certificate(
    cert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    result = await db.execute(select(Certificate).where(Certificate.id == cert_id))
    cert = result.scalar_one_or_none()
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    await db.delete(cert)
    await db.commit()


# ── Jenkins Agents ────────────────────────────────────────────────────


@router.get("/nodes/{node_id}/jenkins")
async def get_jenkins_agent(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    result = await db.execute(select(JenkinsAgent).where(JenkinsAgent.node_id == node_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Jenkins agent not configured for this node")
    return _agent_out(agent)


@router.put("/nodes/{node_id}/jenkins")
async def upsert_jenkins_agent(
    node_id: uuid.UUID,
    body: UpsertJenkinsBody,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    node_result = await db.execute(select(Node).where(Node.id == node_id))
    if not node_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Node not found")

    result = await db.execute(select(JenkinsAgent).where(JenkinsAgent.node_id == node_id))
    agent = result.scalar_one_or_none()

    if agent:
        agent.jenkins_url = body.jenkins_url
        agent.agent_name = body.agent_name
    else:
        agent = JenkinsAgent(
            node_id=node_id,
            jenkins_url=body.jenkins_url,
            agent_name=body.agent_name,
            status="unknown",
            created_at=datetime.now(UTC),
        )
        db.add(agent)

    await db.commit()
    return _agent_out(agent)


@router.post("/nodes/{node_id}/jenkins/check")
async def check_jenkins_now(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    result = await db.execute(select(JenkinsAgent).where(JenkinsAgent.node_id == node_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Jenkins agent not configured for this node")

    from fleet_platform.services.ios_tracking_svc import check_jenkins_agent

    await check_jenkins_agent(agent.id, db)

    # Re-fetch after update
    result2 = await db.execute(select(JenkinsAgent).where(JenkinsAgent.id == agent.id))
    agent = result2.scalar_one()
    return _agent_out(agent)


# ── Expiring Certs ────────────────────────────────────────────────────


@router.get("/expiring-certs")
async def get_expiring_certs(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    from fleet_platform.services.ios_tracking_svc import get_expiring_certs

    certs = await get_expiring_certs(db, days=days)
    return {
        "items": [_cert_out(c) for c in certs],
        "total": len(certs),
        "days": days,
    }
