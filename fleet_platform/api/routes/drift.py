# fleet_platform/api/routes/drift.py
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from fleet_platform.api.deps import get_db
from fleet_platform.core.auth import get_current_user, require_role
from fleet_platform.models.drift import DesiredStateBaseline, DriftRecord
from fleet_platform.models.node import Node
from fleet_platform.schemas.common import PaginatedResponse
from fleet_platform.schemas.drift import (
    DriftRecordResponse,
    DriftSummaryResponse,
    drift_severity,
)
from fleet_platform.workers.drift_tasks import compute_drift

router = APIRouter(prefix="/api/v1/drift")

_SEVERITY_RANGES = {
    "clean":    (0, 5),
    "low":      (6, 20),
    "medium":   (21, 50),
    "high":     (51, 80),
    "critical": (81, 100),
}


@router.get("", response_model=PaginatedResponse[DriftSummaryResponse])
async def list_drift(
    severity: str | None = None,
    page: int = 1,
    per_page: int = 25,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """List all nodes ordered by drift_score descending."""
    query = select(Node)

    if severity:
        if severity not in _SEVERITY_RANGES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"severity must be one of {list(_SEVERITY_RANGES)}",
            )
        lo, hi = _SEVERITY_RANGES[severity]
        query = query.where(Node.drift_score >= lo, Node.drift_score <= hi)

    query = query.order_by(Node.drift_score.desc())
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar_one()
    result = await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    nodes = result.scalars().all()

    items = []
    for node in nodes:
        dr_result = await db.execute(
            select(DriftRecord, DesiredStateBaseline)
            .outerjoin(DesiredStateBaseline, DesiredStateBaseline.id == DriftRecord.baseline_id)
            .where(DriftRecord.node_id == node.id)
            .order_by(DriftRecord.computed_at.desc())
            .limit(1)
        )
        row = dr_result.first()
        computed_at = row[0].computed_at if row else None
        baseline_name = row[1].name if row and row[1] else None

        items.append(DriftSummaryResponse(
            node_id=node.id,
            hostname=node.hostname,
            drift_score=node.drift_score,
            severity=drift_severity(node.drift_score),
            computed_at=computed_at,
            baseline_name=baseline_name,
        ))

    return PaginatedResponse(items=items, total=total, page=page, per_page=per_page)


@router.get("/{node_id}/latest", response_model=DriftRecordResponse)
async def get_node_drift_latest(
    node_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Return the most recent drift record for a node with full diff detail."""
    result = await db.execute(
        select(DriftRecord, DesiredStateBaseline)
        .outerjoin(DesiredStateBaseline, DesiredStateBaseline.id == DriftRecord.baseline_id)
        .where(DriftRecord.node_id == node_id)
        .order_by(DriftRecord.computed_at.desc())
        .limit(1)
    )
    row = result.first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No drift records found for this node",
        )

    dr, baseline = row
    return DriftRecordResponse(
        node_id=dr.node_id,
        baseline_id=dr.baseline_id,
        baseline_name=baseline.name if baseline else None,
        computed_at=dr.computed_at,
        drift_score=dr.drift_score,
        severity=drift_severity(dr.drift_score),
        missing_packages=dr.missing_packages,
        extra_packages=dr.extra_packages,
        version_mismatches=dr.version_mismatches,
        service_drift=dr.service_drift,
        config_drift=dr.config_drift,
    )


@router.get("/{node_id}/history", response_model=PaginatedResponse[DriftSummaryResponse])
async def get_node_drift_history(
    node_id: uuid.UUID,
    page: int = 1,
    per_page: int = 50,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Return paginated drift score history for a node (newest first)."""
    total = (await db.execute(
        select(func.count()).where(DriftRecord.node_id == node_id)
    )).scalar_one()

    result = await db.execute(
        select(DriftRecord)
        .where(DriftRecord.node_id == node_id)
        .order_by(DriftRecord.computed_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    records = result.scalars().all()

    items = [
        DriftSummaryResponse(
            node_id=r.node_id,
            hostname=None,
            drift_score=r.drift_score,
            severity=drift_severity(r.drift_score),
            computed_at=r.computed_at,
            baseline_name=None,
        )
        for r in records
    ]
    return PaginatedResponse(items=items, total=total, page=page, per_page=per_page)


@router.post("/{node_id}/compute", status_code=202)
async def trigger_drift_compute(
    node_id: uuid.UUID,
    _: dict = Depends(require_role("operator", "admin")),
):
    """Enqueue a drift recomputation for a node."""
    compute_drift.delay(str(node_id))
    return {"status": "queued", "node_id": str(node_id)}
