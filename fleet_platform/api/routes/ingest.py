# fleet_platform/api/routes/ingest.py
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.models.facts import NodeFact
from fleet_platform.models.node import Node
from fleet_platform.schemas.ingest import GrainIngestPayload
from fleet_platform.services.node_status import verify_node_token
from fleet_platform.workers.drift_tasks import compute_drift

router = APIRouter(prefix="/api/v1/ingest")


async def _resolve_node(minion_id: str, token: str, db: AsyncSession) -> Node:
    """Look up node by minion_id and verify token. Raises 404 or 401."""
    result = await db.execute(select(Node).where(Node.minion_id == minion_id))
    node = result.scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Node not found")
    if not verify_node_token(token, node.node_token_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid node token")
    return node


def _extract_node_updates(grains: dict) -> dict:
    """Map Salt grain keys to Node column values."""
    ip = None
    for iface_ips in grains.get("ip4_interfaces", {}).values():
        if iface_ips:
            ip = iface_ips[0]
            break

    mem_mb = grains.get("mem_total")
    ram_gb = Decimal(str(round(mem_mb / 1024, 2))) if mem_mb else None

    return {
        "hostname": grains.get("id") or grains.get("host"),
        "ip_address": ip,
        "os_version": grains.get("osrelease"),
        "os_build": grains.get("osbuild"),
        "hardware_model": grains.get("productname"),
        "cpu_cores": grains.get("num_cpus"),
        "ram_gb": ram_gb,
        "status": "online",
        "last_seen_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }


@router.post("/grains")
async def ingest_grains(
    payload: GrainIngestPayload,
    x_node_token: str | None = Header(alias="X-Node-Token", default=None),
    db: AsyncSession = Depends(get_db),
):
    if not x_node_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing X-Node-Token")

    node = await _resolve_node(payload.minion_id, x_node_token, db)

    for key, value in _extract_node_updates(payload.grains).items():
        setattr(node, key, value)

    db.add(NodeFact(
        node_id=node.id,
        collected_at=datetime.now(UTC),
        grains=payload.grains,
    ))

    await db.commit()

    compute_drift.delay(str(node.id))

    return {"status": "ok", "node_id": str(node.id)}
