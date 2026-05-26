# fleet_platform/api/routes/fleet_health.py
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import require_role
from fleet_platform.models.node import Node
from fleet_platform.models.node_health_snapshot import NodeHealthSnapshot
from fleet_platform.schemas.fleet_health import CollectResponse, NodeHealthSnapshotResponse

router = APIRouter(prefix="/api/v1/fleet-health", tags=["fleet-health"])


def _to_response(snapshot: NodeHealthSnapshot, hostname: str | None) -> NodeHealthSnapshotResponse:
    return NodeHealthSnapshotResponse(
        id=snapshot.id,
        node_id=snapshot.node_id,
        minion_id=snapshot.minion_id,
        hostname=hostname,
        collected_at=snapshot.collected_at,
        disk_root_used_gb=snapshot.disk_root_used_gb,
        disk_root_total_gb=snapshot.disk_root_total_gb,
        disk_root_pct=snapshot.disk_root_pct,
        disk_root_inodes_pct=snapshot.disk_root_inodes_pct,
        mem_total_gb=snapshot.mem_total_gb,
        mem_available_gb=snapshot.mem_available_gb,
        mem_used_pct=snapshot.mem_used_pct,
        cpu_load_1m=snapshot.cpu_load_1m,
        cpu_load_5m=snapshot.cpu_load_5m,
        cpu_load_15m=snapshot.cpu_load_15m,
        uptime_seconds=snapshot.uptime_seconds,
        gpu_name=snapshot.gpu_name,
        gpu_vram_mb=snapshot.gpu_vram_mb,
        cpu_power_mw=snapshot.cpu_power_mw,
        gpu_power_mw=snapshot.gpu_power_mw,
        thermal_pressure=snapshot.thermal_pressure,
        error=snapshot.error,
    )


@router.get("", response_model=list[NodeHealthSnapshotResponse])
async def get_fleet_health(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Return the latest health snapshot for each node."""
    rows = await db.execute(
        text("""
            SELECT s.*, n.hostname
            FROM (
                SELECT DISTINCT ON (node_id) *
                FROM node_health_snapshots
                ORDER BY node_id, collected_at DESC
            ) s
            JOIN nodes n ON n.id = s.node_id
            ORDER BY n.hostname NULLS LAST
        """)
    )
    results = rows.mappings().all()

    snapshots = []
    for row in results:
        snap = NodeHealthSnapshot(**{k: v for k, v in row.items() if k != "hostname"})
        snapshots.append(_to_response(snap, row.get("hostname")))
    return snapshots


@router.post("/collect", response_model=CollectResponse, status_code=202)
async def trigger_collection(
    _: dict = Depends(require_role("admin")),
):
    """Trigger an immediate health collection from all online nodes."""
    from fleet_platform.workers.health_tasks import collect_fleet_health

    collect_fleet_health.delay()
    return CollectResponse(status="queued", message="Health collection task queued.")


@router.get("/{node_id}/history", response_model=list[NodeHealthSnapshotResponse])
async def get_node_health_history(
    node_id: uuid.UUID,
    hours: int = Query(default=24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role("operator", "admin")),
):
    """Return health snapshots for a node over the last N hours (default 24, max 168)."""
    node = await db.get(Node, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    since = datetime.now(UTC) - timedelta(hours=hours)
    result = await db.execute(
        select(NodeHealthSnapshot)
        .where(
            NodeHealthSnapshot.node_id == node_id,
            NodeHealthSnapshot.collected_at >= since,
        )
        .order_by(NodeHealthSnapshot.collected_at.asc())
    )
    snapshots = result.scalars().all()
    return [_to_response(s, node.hostname) for s in snapshots]
